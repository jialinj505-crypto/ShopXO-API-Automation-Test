"""框架鉴权层（core/auth.py + core/base_api.py 的鉴权分支）离线单元测试。

为什么值得单独测"框架自己"：
鉴权是所有受保护接口的前置依赖，它一旦写错，失败现象会出现在业务用例上，
排查时容易误判成"环境问题"或"产品缺陷"。所以这里用 mock 把几条底线固定下来：

1. token 会话级缓存 —— 防止每个用例重复登录（回归变慢、沙箱账号触发风控）；
2. 登录失败必须抛出带 code/msg 的真实原因 —— 防止只抛"登录失败"导致定位靠猜；
3. token 失效（-400）自动重新登录并重试原请求 —— 防止长链路跑一半因登录态过期假失败；
4. AuthType.NONE 不参与登录与自动重登 —— 防止免登录/伪造 token 的异常用例被"洗白"成假绿；
5. 日志/复现信息脱敏 —— 防止真实 token 明文进入 CI 日志与归档报告；
6. 并发取 token 只登录一次 —— 防止 xdist/多线程下重复登录或拿到脏 token。

全部用 responses 拦截 HTTP（未注册的请求会直接报错），零真实网络。
"""
import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from api_objects.user_api import UserAPI
from config.setting import API_PREFIX, BASE_URL, USER_ACCOUNTS
from core.auth import TOKEN_INVALID_CODES, AuthError, AuthType, TokenManager
from core.base_api import BaseAPI

pytestmark = pytest.mark.offline

# 真实框架拼出来的请求地址（BaseAPI.build_url），用正则注册以免被自动注入的
# token 查询参数影响 URL 匹配（responses 对带查询串的字符串 URL 会严格比对查询串）。
LOGIN_URL = f"{BASE_URL}{API_PREFIX}user/login"
INTEGRAL_URL = f"{BASE_URL}{API_PREFIX}userintegral/index"
LOGIN_PATTERN = re.compile(re.escape(LOGIN_URL) + r"([?&].*)?$")
INTEGRAL_PATTERN = re.compile(re.escape(INTEGRAL_URL) + r"([?&].*)?$")

# 故意写成一眼可识别的"密钥"，便于断言它没有明文出现在日志/上下文里
SECRET_TOKEN = "unit-test-secret-token-0123456789abcdef"

LOGIN_OK = {
    "code": 0,
    "msg": "登录成功",
    "data": {
        "id": 1,
        "username": "huace_tester",
        "token": SECRET_TOKEN,
        "user_name_view": "huace",
        "integral": 0,
    },
}


def _json_body(payload: dict) -> tuple:
    """构造 responses callback 的 (status, headers, body) 三元组。"""
    return 200, {"Content-Type": "application/json"}, json.dumps(payload, ensure_ascii=False)


def _form_body(call) -> dict:
    """把请求体（application/x-www-form-urlencoded）解析成 dict，便于断言真实入参。"""
    return {key: value[0] for key, value in parse_qs(call.request.body or "").items()}


class _RecordHandler(logging.Handler):
    """收集日志文本。

    core.logger 的 logger 设置了 propagate=False（只往自己的 handler 输出），
    pytest 的 caplog 抓不到，所以这里挂一个独立 handler 做脱敏断言。
    """

    def __init__(self, sink: list) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record.getMessage())


@pytest.fixture(autouse=True)
def isolated_auth_state(monkeypatch):
    """隔离 TokenManager 的类级缓存/账号/登录计数，避免用例之间互相污染。

    用 monkeypatch 而不是手工清理：即使用例失败也会自动还原，
    不会把脏 token 留给同进程内的其它用例（含后续真实环境用例）。
    """
    monkeypatch.setattr(TokenManager, "_tokens", {}, raising=False)
    monkeypatch.setattr(TokenManager, "_login_times", {}, raising=False)
    monkeypatch.setattr(
        TokenManager, "_accounts", {AuthType.USER: dict(USER_ACCOUNTS["default"])}, raising=False
    )


@pytest.fixture
def http():
    """启用 responses 拦截：未注册的请求会直接抛错，保证本文件零真实网络。"""
    responses.mock.reset()
    responses.mock.start()
    yield responses.mock
    responses.mock.stop(allow_assert=False)
    responses.mock.reset()


# ------------------------------------------------------------------ 缓存与复用
def test_first_get_token_logs_in_and_second_hits_cache(http):
    """防止风险：token 未做会话级缓存——每个用例都重新登录，回归变慢且易触发沙箱风控。"""
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)

    token = TokenManager.get_token(AuthType.USER)
    assert token == SECRET_TOKEN
    assert len(responses.calls) == 1, "首次取 token 必须调用登录接口"
    assert responses.calls[0].request.url == LOGIN_URL

    # 登录入参必须是真实接口约定的 accounts/pwd/type（防止框架少传/传错字段）
    payload = _form_body(responses.calls[0])
    assert payload["accounts"] == USER_ACCOUNTS["default"]["accounts"]
    assert payload["pwd"] == USER_ACCOUNTS["default"]["pwd"]
    assert payload["type"] == "username"

    assert TokenManager.get_token(AuthType.USER) == token
    assert len(responses.calls) == 1, "第二次取 token 命中缓存，不应再调用登录接口"
    assert TokenManager.login_times(AuthType.USER) == 1


def test_injected_token_skips_login(http):
    """防止风险：set_token 注入的 token 被缓存逻辑忽略，产生多余登录请求。"""
    TokenManager.set_token(AuthType.USER, "injected-token-for-unit-test")

    assert TokenManager.get_token(AuthType.USER) == "injected-token-for-unit-test"
    assert len(responses.calls) == 0, "已有 token 时不应发起任何请求"
    assert TokenManager.login_times(AuthType.USER) == 0


@pytest.mark.parametrize("trigger", ["invalidate", "force"])
def test_invalidate_and_force_trigger_relogin(http, trigger):
    """防止风险：token 失效后仍返回旧 token（清理逻辑写错），用例拿着脏 token 全线 -400。"""
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)
    TokenManager.get_token(AuthType.USER)
    assert len(responses.calls) == 1

    if trigger == "invalidate":
        TokenManager.invalidate(AuthType.USER)
        TokenManager.get_token(AuthType.USER)
    else:
        TokenManager.get_token(AuthType.USER, force=True)

    assert len(responses.calls) == 2, f"{trigger} 之后必须重新登录，而不是复用旧 token"
    assert TokenManager.login_times(AuthType.USER) == 2


def test_configure_switches_account_and_drops_cached_token(http):
    """防止风险：configure() 切换账号后仍复用旧账号 token（缓存键没跟着失效）。"""
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)
    TokenManager.get_token(AuthType.USER)

    wrong_pwd_account = dict(USER_ACCOUNTS["wrong_pwd"])
    TokenManager.configure(AuthType.USER, wrong_pwd_account)
    assert TokenManager.account(AuthType.USER) == wrong_pwd_account

    TokenManager.get_token(AuthType.USER)
    assert len(responses.calls) == 2, "切换账号后必须用新账号重新登录"
    assert _form_body(responses.calls[1])["pwd"] == USER_ACCOUNTS["wrong_pwd"]["pwd"]


# ------------------------------------------------------------------ 失败与异常
def test_login_failure_error_carries_code_and_msg(http):
    """防止风险：登录失败只抛"登录失败"，排查时不知道是密码错还是账号不存在。"""
    responses.add(responses.POST, LOGIN_PATTERN, json={"code": -4, "msg": "密码错误", "data": None})

    with pytest.raises(AuthError) as excinfo:
        TokenManager.get_token(AuthType.USER)

    message = str(excinfo.value)
    assert "-4" in message and "密码错误" in message, f"异常信息必须带真实业务码与提示，实际：{message}"
    assert len(responses.calls) == 1

    # 失败不得被当成成功缓存：第二次取 token 仍会真正发起登录（网络抖动后可自愈）
    with pytest.raises(AuthError):
        TokenManager.get_token(AuthType.USER)
    assert len(responses.calls) == 2, "登录失败被缓存，后续请求会拿着空 token 继续跑"


def test_login_success_without_token_raises_auth_error(http):
    """防止风险：登录接口 code=0 但没返回 token 时静默通过，后续请求全带无效 token。"""
    responses.add(responses.POST, LOGIN_PATTERN, json={"code": 0, "msg": "登录成功", "data": {"id": 1}})

    with pytest.raises(AuthError) as excinfo:
        TokenManager.get_token(AuthType.USER)

    assert "code=0" in str(excinfo.value), "缺少 token 时必须明确报出接口真实返回"


def test_unconfigured_auth_type_fails_before_network(http):
    """防止风险：账号没配就发请求，报错发生在深处、看不出是配置缺失。"""
    TokenManager.configure(AuthType.USER, {})

    with pytest.raises(AuthError) as excinfo:
        TokenManager.get_token(AuthType.USER)

    assert "configure" in str(excinfo.value), "应提示先调用 TokenManager.configure()"
    assert len(responses.calls) == 0, "配置缺失时不得发起任何登录请求"


def test_admin_type_cannot_use_password_login(http):
    """防止风险：把只支持账号密码的前台登录硬套到商家后台，拿到错误 token 后全线 -400。"""
    TokenManager.configure(AuthType.ADMIN, {"accounts": "admin", "pwd": "admin123"})

    with pytest.raises(AuthError) as excinfo:
        TokenManager.get_token(AuthType.ADMIN)

    assert "不支持" in str(excinfo.value)
    assert len(responses.calls) == 0, "不支持的鉴权类型不得发起任何登录请求"


# ------------------------------------------------------------------ AuthType.NONE
def test_auth_type_none_makes_no_login_call(http):
    """防止风险：免登录接口被偷偷注入 token——掩盖权限校验缺陷、污染请求参数。"""
    responses.add(responses.POST, INTEGRAL_PATTERN, json={"code": 0, "msg": "success", "data": {"data": []}})

    res = UserAPI(auth=AuthType.NONE).integral_list()

    assert res["code"] == 0
    assert len(responses.calls) == 1, "免登录请求只应有业务请求，不应有登录请求"
    assert "token" not in responses.calls[0].request.url, "AuthType.NONE 不得注入 token"
    assert TokenManager.login_times(AuthType.USER) == 0


def test_auth_type_none_does_not_relogin_on_token_invalid(http):
    """防止风险：免登录/伪造 token 的异常用例被自动重登"洗白"，异常场景变成假绿。"""
    responses.add(responses.POST, INTEGRAL_PATTERN, json={"code": -400, "msg": "登录失效，请重新登录"})

    res = UserAPI(auth=AuthType.NONE).integral_list()

    assert res["code"] == -400
    assert len(responses.calls) == 1, "AuthType.NONE 不应触发重试/重登"
    assert TokenManager.login_times(AuthType.USER) == 0


# ------------------------------------------------------------------ 失效自动重登
def _token_of(obj) -> str:
    """取出请求实际携带的 token（框架把 token 注入到 query params）。

    obj 既可能是 responses 记录的 Call（有 .request），也可能是回调里的 PreparedRequest。
    """
    request = getattr(obj, "request", obj)
    return parse_qs(urlsplit(request.url).query).get("token", [""])[0]


def _token_gated_server(valid_token: str):
    """模拟真实沙箱：请求带的 token 不等于 valid_token 就返回 -400 登录失效。"""

    def _callback(request):
        if _token_of(request) and _token_of(request) == valid_token:
            return _json_body({"code": 0, "msg": "success", "data": {"data": []}})
        return _json_body({"code": -400, "msg": "登录失效，请重新登录"})

    return _callback


def test_token_invalid_relogins_and_retries_with_fresh_token(http):
    """-400 失效自愈（修复后行为）：真的重新登录一次，并用新 token 重试原请求。

    这条用例原来固定的是缺陷行为——框架日志写着"已重新登录并重试"，实际没有发出登录请求、
    重试仍携带失效前的旧 token（必然再撞一次 -400）；两个独立的框架单测文件都复现了它。
    修复后 `_inject_token()` 区分"框架注入 / 调用方传入"，每轮重试前重新注入框架注入的 token，
    于是 `TokenManager.invalidate()` 清掉的缓存被真正重建。
    这里让服务端持续返回 -400，顺带守住"只重登一次、不无限重登"。
    """
    assert -400 in TOKEN_INVALID_CODES, "框架未把 -400 识别为 token 失效码，自动重登会失效"
    TokenManager.set_token(AuthType.USER, SECRET_TOKEN)

    issued = []

    def _login_callback(request):
        issued.append(f"login-token-{len(issued) + 1:04d}-abcdef")
        return _json_body({"code": 0, "msg": "登录成功", "data": dict(LOGIN_OK["data"], token=issued[-1])})

    responses.add_callback(responses.POST, LOGIN_PATTERN, callback=_login_callback)

    endpoint_calls = {"count": 0}

    def _integral_callback(request):
        endpoint_calls["count"] += 1
        return _json_body({"code": -400, "msg": "登录失效，请重新登录"})

    responses.add_callback(responses.POST, INTEGRAL_PATTERN, callback=_integral_callback)

    res = UserAPI().integral_list()

    assert endpoint_calls["count"] == 2, "框架确实重试了一次原请求"
    assert len(issued) == 1, "关键：-400 之后必须真的重新登录一次（且只重登一次）"
    assert TokenManager.login_times(AuthType.USER) == 1
    assert _token_of(responses.calls[-1]) == issued[0], "重试必须携带重新登录后的新 token"
    assert _token_of(responses.calls[-1]) != SECRET_TOKEN, "重试不能再发失效前的旧 token"
    assert res["code"] == -400, "服务端持续返回 -400 时如实返回失败，不掩盖"


def test_token_invalid_should_relogin_with_fresh_token(http):
    """期望行为（当前不满足）：-400 后应重新登录，并用新 token 重试原请求直至成功。

    这是框架 docstring 承诺的能力（core/auth.py:6 "失效自动恢复"），
    也是长链路用例不因登录态过期而假失败的前提。
    """
    issued = []

    def _login_callback(request):
        issued.append(f"login-token-{len(issued) + 1:04d}-abcdef")
        return _json_body(
            {
                "code": 0,
                "msg": "登录成功",
                "data": dict(LOGIN_OK["data"], token=issued[-1]),
            }
        )

    responses.add_callback(responses.POST, LOGIN_PATTERN, callback=_login_callback)
    responses.add_callback(
        responses.POST, INTEGRAL_PATTERN, callback=_token_gated_server("login-token-0002-abcdef")
    )

    res = UserAPI().integral_list()

    assert len(issued) == 2, f"应重新登录一次，实际登录 {len(issued)} 次"
    assert _token_of(responses.calls[-1]) == "login-token-0002-abcdef", "重试必须使用重新登录后的新 token"
    assert res["code"] == 0, f"用新 token 重试应成功，实际 code={res['code']} msg={res.get('msg')}"


# ------------------------------------------------------------------ 脱敏
def test_login_token_is_masked_in_logs(http):
    """防止风险：真实 token 明文进日志——CI 日志被转发/归档后等同于凭据泄露。"""
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)
    records = []
    auth_logger = logging.getLogger("shopxo.auth")
    handler = _RecordHandler(records)
    auth_logger.addHandler(handler)
    try:
        TokenManager.get_token(AuthType.USER)
    finally:
        auth_logger.removeHandler(handler)

    text = "\n".join(records)
    assert records, "登录成功没有任何日志，出问题后无法回溯鉴权行为"
    assert SECRET_TOKEN not in text, f"token 明文出现在日志中：{text}"
    assert TokenManager.mask(SECRET_TOKEN) in text, "日志应保留可人工核对的脱敏 token"


def test_token_is_masked_in_request_context_and_curl(http):
    """防止风险：token 明文留在 last_exchange / 可复现 curl 里，随报告附件一起外发。"""
    responses.add(responses.POST, INTEGRAL_PATTERN, json={"code": 0, "msg": "success", "data": {"data": []}})
    TokenManager.set_token(AuthType.USER, SECRET_TOKEN)

    api = UserAPI()
    api.integral_list()
    exchange_text = json.dumps(api.last_exchange, ensure_ascii=False, default=str)

    assert SECRET_TOKEN not in api.build_curl(), "复现用的 curl 命令泄露了 token 明文"
    assert SECRET_TOKEN not in exchange_text, "last_exchange（会写进 Allure 附件）泄露了 token 明文"
    assert api.last_exchange["params"]["token"] == TokenManager.mask(SECRET_TOKEN)


def test_login_response_token_is_not_kept_in_plaintext(http):
    """响应体也要脱敏：登录返回的 token 不得以明文进入 last_exchange（会作为附件写进报告）。"""
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)

    api = UserAPI(auth=AuthType.NONE)
    api.login(USER_ACCOUNTS["default"]["accounts"], USER_ACCOUNTS["default"]["pwd"])

    assert SECRET_TOKEN not in json.dumps(api.last_exchange, ensure_ascii=False, default=str)


def test_mask_keeps_only_head_and_tail():
    """防止风险：TokenManager.mask 退化成"原样返回"，脱敏形同虚设。"""
    assert TokenManager.mask(SECRET_TOKEN) == f"{SECRET_TOKEN[:6]}***{SECRET_TOKEN[-4:]}"
    assert SECRET_TOKEN[6:-4] not in TokenManager.mask(SECRET_TOKEN)
    assert TokenManager.mask("") == "<empty>"
    assert TokenManager.mask("short") == "sh***"


# ------------------------------------------------------------------ 并发
def test_concurrent_get_token_logs_in_once(http):
    """防止风险：并发首次取 token 时重复登录（浪费账号配额、易触发沙箱风控）。

    用 Barrier 让所有线程同时冲进 get_token，并在 mock 回调里 sleep 放大竞态窗口：
    若框架没有把"检查缓存 + 登录 + 写缓存"整体加锁，这里就会观察到多次登录。
    """
    thread_count = 8
    barrier = threading.Barrier(thread_count)

    def _slow_login(request):
        time.sleep(0.05)
        return _json_body(LOGIN_OK)

    responses.add_callback(responses.POST, LOGIN_PATTERN, callback=_slow_login)

    results, errors = [], []

    def _worker():
        try:
            barrier.wait(timeout=20)
            results.append(TokenManager.get_token(AuthType.USER))
        except Exception as exc:  # noqa: BLE001 - 线程内异常必须带回主线程断言，否则会被静默吞掉
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(thread.is_alive() for thread in threads), "并发取 token 出现死锁/超时"
    assert errors == [], f"并发取 token 抛异常：{errors}"
    assert results == [SECRET_TOKEN] * thread_count, "并发下拿到了不一致的 token"
    assert len(responses.calls) == 1, "并发只应发生一次登录"
    assert TokenManager.login_times(AuthType.USER) == 1


def test_base_api_requires_token_manager_for_user_auth(http):
    """防止风险：受保护接口的 token 注入被绕过（直接不传 token 也能发请求）。"""
    responses.add(responses.POST, INTEGRAL_PATTERN, json={"code": 0, "msg": "success", "data": {"data": []}})
    responses.add(responses.POST, LOGIN_PATTERN, json=LOGIN_OK)

    assert BaseAPI().auth == AuthType.NONE, "基类默认应为免登录，子类按需声明"
    UserAPI().integral_list()

    assert len(responses.calls) == 2, "USER 鉴权应自动完成一次登录 + 一次业务请求"
    assert responses.calls[0].request.url == LOGIN_URL
    assert "token=" in responses.calls[1].request.url
