"""BaseAPI（框架请求驱动）的离线自测：用 responses 打桩，零真实网络。

为什么要单独测"框架自己"
------------------------
框架层是所有业务用例的地基。重试策略、幂等保护、鉴权注入、响应容错只要有一处不对，
上层用例就会集体"说谎"：真实缺陷可能被重试成假绿，网络抖动也可能被吞成通过。
而这些行为没法靠跑公开沙箱来稳定验证（沙箱会抖、会变、会被别人改数据），
所以这里用 responses 把 HTTP 打桩，把框架契约固定下来：

1. 正常响应原样解析，并保留 `_http_status` 供失败排查；
2. 非 JSON / 结构异常响应统一转框架错误码 `CODE_NON_JSON`（-9998），不抛裸异常；
3. 网络异常按 `RETRY_TIMES` 重试，退避为 `retry_interval × backoff^(n-1)`；
4. HTTP 5xx 与约定业务码触发重试，**非幂等接口一律不重试**（防重复下单）；
5. 公共参数与 token 的注入规则（token 走 GET 参数，见 README「统一 Token 鉴权」）；
6. 可复现 curl 的生成，以及 token/pwd 不得以明文落进日志与附件。

发现框架缺陷时**不改框架代码**，而是用 `pytest.mark.xfail(reason=...)` 固定"应该是什么样"，
另用普通用例固定"现在实际是什么样"，两边都写清楚，避免缺陷被无声修掉或无声扩大。
"""
from urllib.parse import parse_qsl, urlsplit

import pytest
import requests
import responses
from responses import matchers

import core.base_api as base_api
from config.setting import (
    BASE_URL,
    COMMON_PARAMS,
    RETRY_BACKOFF,
    RETRY_BIZ_CODES,
    RETRY_STATUS_CODES,
    RETRY_TIMES,
)
from core.auth import AuthType, TokenManager
from core.base_api import CODE_NETWORK, CODE_NON_JSON, ApiError, BaseAPI

# 本文件全部为离线用例（SHOPXO_OFFLINE=1 时只执行带该标记的用例，见 tests/conftest.py）
pytestmark = pytest.mark.offline

# ShopXO 的路由形如 index.php?s=/api/...：URL 的 path 恒为 /index.php，接口身份在 query 里。
# 因此 mock 只按 path 注册（responses 对"带 query 的注册"会顺带严格比对 query），
# 接口身份改用 query 匹配器表达，避免 token / 公共参数一进来就匹配不上。
CART_ROUTE = "/index.php?s=/api/cart/index"
LOGIN_ROUTE = "/index.php?s=/api/user/login"
INDEX_URL = f"{BASE_URL}/index.php"
CART_MATCH = [matchers.query_param_matcher({"s": "/api/cart/index"}, strict_match=False)]
LOGIN_MATCH = [matchers.query_param_matcher({"s": "/api/user/login"})]

# 长 token 便于同时验证"首6+尾4"脱敏与"明文不得出现"；脱敏格式见 core/auth.py:108
TOKEN = "c2021a77f0a1b2c3d4e5f60718293a4b3624"
MASKED_TOKEN = f"{TOKEN[:6]}***{TOKEN[-4:]}"
OLD_TOKEN = "oldtoken0000000000000000000000000000ab"
NEW_TOKEN = "newtoken1111111111111111111111111111ee"


def _ok(data=None) -> dict:
    """标准成功响应体。"""
    return {"code": 0, "msg": "success", "data": {} if data is None else data}


def _add_cart(rsps, method=responses.POST, **kwargs):
    """注册购物车接口的 mock（可按 token 等条件追加 match）。"""
    kwargs.setdefault("match", CART_MATCH)
    return rsps.add(method, INDEX_URL, **kwargs)


def _add_login(rsps, **kwargs):
    """注册登录接口的 mock。"""
    kwargs.setdefault("match", LOGIN_MATCH)
    return rsps.add(responses.POST, INDEX_URL, **kwargs)


def _query(call) -> dict:
    """取请求 URL 上的 query（框架把 token 与 GET 公共参数放在这里）。"""
    return dict(parse_qsl(urlsplit(str(call.request.url)).query))


def _body(call) -> dict:
    """取 POST 表单体（框架把公共参数放在这里）。"""
    return dict(parse_qsl(call.request.body or ""))


# ---------------------------------------------------------------------- 夹具
@pytest.fixture(autouse=True)
def retry_delays(monkeypatch):
    """隔离全局状态 + 记录重试退避时长。

    要清的三类"类级/模块级"共享状态：
    1. `TokenManager` 的 token 缓存与登录次数（类级字典，用例间会互相污染）；
    2. 真实 `time.sleep`（默认退避 0.5s 会让重试用例变慢且拖长 CI）；
    3. `responses` 的注册表由每个用例自己的上下文管理器负责，无需在此处理。
    返回的列表按顺序记录每次退避秒数，供断言退避策略。
    """
    monkeypatch.setattr(TokenManager, "_tokens", dict(TokenManager._tokens))
    monkeypatch.setattr(TokenManager, "_login_times", dict(TokenManager._login_times))
    monkeypatch.setattr(
        TokenManager, "_accounts", {key: dict(value) for key, value in TokenManager._accounts.items()}
    )

    delays = []
    monkeypatch.setattr(base_api.time, "sleep", delays.append)
    yield delays


@pytest.fixture
def api_factory():
    """构造被测 BaseAPI：默认免登录、0.1s 起退避（便于断言），用例结束统一关闭会话。"""
    created = []

    def _make(**kwargs):
        kwargs.setdefault("auth", AuthType.NONE)
        kwargs.setdefault("retry_interval", 0.1)
        client = BaseAPI(**kwargs)
        created.append(client)
        return client

    yield _make
    for client in created:
        client.close()


# ------------------------------------------------------------------ 1. 正常响应
def test_normal_response_is_parsed_and_http_status_kept(api_factory):
    """正常业务响应：code/msg/data 原样解析，_http_status 必须保留（排查失败时要靠它分辨框架问题还是业务问题）。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok({"goods_id": 12}), status=200)

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        assert result["code"] == 0
        assert result["msg"] == "success"
        assert result["data"] == {"goods_id": 12}
        assert result["_http_status"] == 200
        assert len(rsps.calls) == 1

    # 最近一次请求上下文：状态码/尝试次数可观测，附件里的响应体不含内部字段
    assert api.last_exchange["http_status"] == 200
    assert api.last_exchange["code"] == 0
    assert api.last_exchange["attempt"] == 1
    assert "_http_status" not in api.last_exchange["response"]


# ------------------------------------------------------- 2. 非 JSON / 结构异常
def test_html_error_page_returns_code_non_json_without_raising(api_factory):
    """容错底线：网关返回 HTML 错误页时不能让用例抛裸异常崩溃，要转成 CODE_NON_JSON 并保留原文与状态码。"""
    api = api_factory(retry_times=0)
    with responses.RequestsMock() as rsps:
        _add_cart(
            rsps,
            body="<html><body>500 Internal Server Error</body></html>",
            status=500,
            content_type="text/html",
        )

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        assert result["code"] == CODE_NON_JSON
        assert result["data"] is None
        assert "非 JSON" in result["msg"]
        assert result["_http_status"] == 500
        assert "Internal Server Error" in result["_raw"]
        assert len(rsps.calls) == 1


def test_non_object_json_returns_code_non_json(api_factory):
    """结构容错：JSON 合法但不是对象（网关返回数组）同样按框架错误码处理，不误判为业务成功。"""
    api = api_factory(retry_times=0)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=[1, 2, 3], status=200)

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        assert result["code"] == CODE_NON_JSON
        assert "响应结构异常" in result["msg"]
        assert result["data"] == [1, 2, 3]
        assert result["_http_status"] == 200


# ------------------------------------------------------------ 3. 网络异常重试
def test_network_error_is_retried_and_raises_api_error(api_factory, retry_delays):
    """网络异常必须重试（否则一次抖动就判用例失败），并在重试耗尽后抛出可读的 ApiError。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, body=requests.exceptions.ConnectTimeout("mock 连接超时"))

        with pytest.raises(ApiError) as excinfo:
            api.post(CART_ROUTE, data={"goods_id": 12})

        assert len(rsps.calls) == RETRY_TIMES + 1, "网络异常应按 RETRY_TIMES 重试（首试 + N 次重试）"
        assert f"已尝试 {RETRY_TIMES + 1} 次" in str(excinfo.value)
        assert "ConnectTimeout" in str(excinfo.value)

    assert retry_delays == pytest.approx([0.1 * RETRY_BACKOFF**0, 0.1 * RETRY_BACKOFF**1]), "退避应为 interval×backoff^(n-1)"


def test_invalid_retry_config_falls_back_to_code_network(api_factory):
    """配置兜底：retry_times<0 导致一次都没执行时，必须返回框架错误码 -9999 并说明原因。

    契约口径（已与文档统一）：网络异常/超时**不**返回 -9999，而是重试耗尽后抛 `ApiError`
    （消息含尝试次数与异常原文），这样失败信息能直接看出是网络问题，不会和业务码混淆；
    `CODE_NETWORK`(-9999) 只用于"请求未执行"这类框架自身的配置兜底，不能静默返回 None。
    """
    api = api_factory(auth=AuthType.NONE)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _add_cart(rsps, json={"code": 0, "msg": "ok", "data": None})

        result = api.post(CART_ROUTE, data={"goods_id": 12}, idempotent=True, retry_times=-1)

        assert len(rsps.calls) == 0, "attempts=0 时不应发出任何请求"

    assert result["code"] == CODE_NETWORK
    assert result["msg"], "兜底错误必须带可读原因，不能只有错误码"


# --------------------------------------------------- 4/5. 5xx 与业务码触发重试
def test_http_500_in_retry_status_codes_is_retried(api_factory, retry_delays):
    """5xx 多为瞬时故障：命中 RETRY_STATUS_CODES 时必须重试，且最终仍如实返回失败结果（不掩盖）。"""
    assert 500 in RETRY_STATUS_CODES
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json={"code": -1, "msg": "服务器内部错误", "data": None}, status=500)

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        assert len(rsps.calls) == RETRY_TIMES + 1
        assert result["code"] == -1
        assert result["_http_status"] == 500

    assert len(retry_delays) == RETRY_TIMES


def test_biz_code_in_retry_biz_codes_is_retried(api_factory, retry_delays):
    """HTTP 200 但业务码命中 RETRY_BIZ_CODES（默认 -500）同样要重试，否则瞬时业务异常会被计成缺陷。"""
    assert -500 in RETRY_BIZ_CODES
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json={"code": -500, "msg": "服务器异常", "data": None}, status=200)

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        assert len(rsps.calls) == RETRY_TIMES + 1
        assert result["code"] == -500
        assert result["_http_status"] == 200

    assert len(retry_delays) == RETRY_TIMES


# ------------------------------------------------------------- 6. 幂等性保护
@pytest.mark.parametrize(
    "status, payload",
    [
        (500, {"code": -1, "msg": "服务器内部错误", "data": None}),
        (200, {"code": -500, "msg": "服务器异常", "data": None}),
    ],
    ids=["http-500", "biz-500"],
)
def test_non_idempotent_request_is_never_retried(api_factory, retry_delays, status, payload):
    """幂等性保护：下单/支付这类写操作 idempotent=False 时，任何失败都只能尝试一次（重试=重复下单）。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=payload, status=status)

        api.post(CART_ROUTE, data={"goods_id": 12}, idempotent=False)

        assert len(rsps.calls) == 1, "非幂等接口不得重试"

    assert retry_delays == [], "非幂等接口不应产生任何退避等待"


def test_subclass_default_idempotent_false_is_respected():
    """类级默认值同样生效：子类声明 default_idempotent=False 时，调用方漏传 idempotent 也不会重试。"""

    class _WriteOnlyAPI(BaseAPI):
        name = "WriteOnlyAPI"
        default_idempotent = False

    api = _WriteOnlyAPI(retry_interval=0.1)
    try:
        with responses.RequestsMock() as rsps:
            _add_cart(rsps, json={"code": -500, "msg": "服务器异常", "data": None}, status=200)

            result = api.post(CART_ROUTE, data={"goods_id": 12})

            assert len(rsps.calls) == 1
            assert result["code"] == -500
    finally:
        api.close()


def test_non_idempotent_network_error_is_not_retried(api_factory):
    """网络异常也不能突破幂等保护：非幂等接口断网时同样只尝试一次，宁可失败也不能产生脏数据。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, body=requests.exceptions.ConnectionError("mock 网络不可达"))

        with pytest.raises(ApiError) as excinfo:
            api.post(CART_ROUTE, data={"goods_id": 12}, idempotent=False)

        assert len(rsps.calls) == 1
        assert "已尝试 1 次" in str(excinfo.value)


# --------------------------------------------------------- 7/8. 公共参数与鉴权
def test_common_params_are_injected_into_get_query(api_factory):
    """GET 公共参数注入：漏注入 application/application_client_type 会被网关判为非法请求，属框架基础契约。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, method=responses.GET, json=_ok())

        api.get(CART_ROUTE, params={"wd": "iphone", "page": 1})

        query = _query(rsps.calls[0])
        assert query["wd"] == "iphone"
        assert query["page"] == "1"
        for key, value in COMMON_PARAMS.items():
            assert query[key] == value


def test_common_params_are_injected_into_post_form(api_factory):
    """POST 公共参数注入到表单体（不是 query）：与接口文档一致，否则后台收到的公共参数为空。"""
    api = api_factory()
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok())

        api.post(CART_ROUTE, data={"goods_id": 12, "stock": 1})

        call = rsps.calls[0]
        body = _body(call)
        assert body["goods_id"] == "12"
        assert body["stock"] == "1"
        for key, value in COMMON_PARAMS.items():
            assert body[key] == value
        assert "application_client_type" not in _query(call), "POST 公共参数应放表单体"


def test_user_auth_injects_token_from_token_manager(api_factory):
    """鉴权注入：USER 接口的 token 由 TokenManager 提供并注入 GET 参数，用例层不应出现手写 token 的代码。"""
    TokenManager.set_token(AuthType.USER, TOKEN)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok())

        api.post(CART_ROUTE, data={"goods_id": 12})

        call = rsps.calls[0]
        assert _query(call)["token"] == TOKEN
        assert "token" not in _body(call), "框架按接口文档把 token 放在 GET 参数（README 已明确该约定）"
        assert _body(call) == {**COMMON_PARAMS, "goods_id": "12"}


@pytest.mark.parametrize("auth", [AuthType.NONE, AuthType.ADMIN])
def test_auth_none_and_admin_requests_carry_no_token(api_factory, auth):
    """免登录接口（登录/首页/搜索）与后台会话接口都不能带前台 token，否则越权用例与登录用例会失真。"""
    TokenManager.set_token(AuthType.USER, TOKEN)  # 即使缓存里有前台 token 也不应被注入
    api = api_factory(auth=auth)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok())

        api.post(CART_ROUTE, data={"goods_id": 12})

        call = rsps.calls[0]
        assert "token" not in _query(call)
        assert "token" not in _body(call)


def test_explicit_token_is_not_overwritten(api_factory):
    """调用方显式传 token 时不覆盖：伪造 token / 缺失 token 的鉴权负向用例依赖这条规则。"""
    TokenManager.set_token(AuthType.USER, TOKEN)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok())

        api.post(CART_ROUTE, params={"token": "forged-token"}, data={"goods_id": 12})

        assert _query(rsps.calls[0])["token"] == "forged-token"


def test_token_is_obtained_by_login_when_cache_is_empty(api_factory):
    """缓存为空时框架自动登录拿 token：保证"一次登录全程复用"的前提是真能拿到 token，而不是靠缓存巧合。"""
    TokenManager.invalidate(AuthType.USER)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock() as rsps:
        _add_login(rsps, json=_ok({"token": TOKEN}))
        _add_cart(
            rsps,
            json=_ok({"goods_id": 12}),
            match=[matchers.query_param_matcher({"s": "/api/cart/index", "token": TOKEN})],
        )

        api.post(CART_ROUTE, data={"goods_id": 12})

        login_calls = [call for call in rsps.calls if "user/login" in str(call.request.url)]
        assert len(login_calls) == 1
        assert len(rsps.calls) == 2
        assert _body(login_calls[0])["accounts"] == TokenManager.account(AuthType.USER)["accounts"]
        assert "pwd" in _body(login_calls[0])
        assert TokenManager.get_token(AuthType.USER) == TOKEN


# --------------------------------------------- token 失效自愈（修复后行为）
def test_token_invalid_relogins_once_then_retries_with_fresh_token(api_factory):
    """-400 失效自愈：必须真的重新登录一次，并用新 token 重试（且只重登一次，不无限循环）。

    背景：这条用例原来固定的是"框架日志说已重登、实际没登、重试仍带旧 token"的缺陷行为，
    修复后改为断言期望行为——`_inject_token()` 现在会区分"框架注入/调用方传入"，
    每轮重试前刷新框架注入的 token，`invalidate()` 清掉的缓存因此能被真正重建。
    """
    TokenManager.set_token(AuthType.USER, OLD_TOKEN)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # 服务端对任何 token 都回 -400：用于验证"只重登一次"的收敛性
        _add_cart(rsps, json={"code": -400, "msg": "登录失效", "data": None})
        _add_login(rsps, json=_ok({"token": NEW_TOKEN}))

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        login_calls = [call for call in rsps.calls if "user/login" in str(call.request.url)]
        api_calls = [call for call in rsps.calls if "user/login" not in str(call.request.url)]
        assert len(api_calls) == 2, "-400 后框架会额外给一次尝试机会"
        assert [_query(call)["token"] for call in api_calls] == [OLD_TOKEN, NEW_TOKEN], (
            "重试必须换成重新登录后的新 token，而不是继续发失效的旧 token"
        )
        assert len(login_calls) == 1, "必须真的重新登录，且只重登一次（不能无限重登）"

    assert result["code"] == -400, "服务端持续返回 -400 时如实返回失败，不掩盖"


def test_token_invalid_should_retry_with_fresh_token(api_factory):
    """应然行为：重新登录后重试必须使用新 token，最终结果应为成功，而不是再撞一次 -400。"""
    TokenManager.set_token(AuthType.USER, OLD_TOKEN)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _add_cart(
            rsps,
            json={"code": -400, "msg": "登录失效", "data": None},
            match=[matchers.query_param_matcher({"s": "/api/cart/index", "token": OLD_TOKEN})],
        )
        _add_login(rsps, json=_ok({"token": NEW_TOKEN}))
        _add_cart(
            rsps,
            json=_ok({"goods_id": 12}),
            match=[matchers.query_param_matcher({"s": "/api/cart/index", "token": NEW_TOKEN})],
        )

        result = api.post(CART_ROUTE, data={"goods_id": 12})

        api_calls = [call for call in rsps.calls if "user/login" not in str(call.request.url)]
        assert len(api_calls) == 2
        assert _query(api_calls[-1])["token"] == NEW_TOKEN

    assert result["code"] == 0


# --------------------------------------------------------------- 9. 可复现 curl
def test_build_curl_contains_method_url_and_masks_token(api_factory):
    """可复现性 + 脱敏：curl 必须能直接复现（方法/URL/关键参数齐全），同时不得把 token 明文写进日志与附件。"""
    TokenManager.set_token(AuthType.USER, TOKEN)
    api = api_factory(auth=AuthType.USER)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, json=_ok())
        api.post(CART_ROUTE, data={"goods_id": 12})

    curl = api.build_curl()
    assert curl.startswith("curl -X POST '")
    assert CART_ROUTE in curl
    assert f"token={MASKED_TOKEN}" in curl
    assert "***" in curl
    assert TOKEN not in curl, "curl 泄露了 token 明文"
    assert "-d 'goods_id=12'" in curl
    assert f"-d 'application={COMMON_PARAMS['application']}'" in curl
    assert f"-d 'application_client_type={COMMON_PARAMS['application_client_type']}'" in curl


def test_build_curl_after_network_error_is_still_reproducible(api_factory):
    """失败路径同样要能复现：网络异常时的 curl 仍应可用，且同样不能泄露 token（排查最需要它）。"""
    TokenManager.set_token(AuthType.USER, TOKEN)
    api = api_factory(auth=AuthType.USER, retry_times=0)
    with responses.RequestsMock() as rsps:
        _add_cart(rsps, body=requests.exceptions.ConnectionError("mock 网络不可达"))

        with pytest.raises(ApiError):
            api.post(CART_ROUTE, data={"goods_id": 12})

        assert len(rsps.calls) == 1

    curl = api.build_curl()
    assert "curl -X POST" in curl
    assert CART_ROUTE in curl
    assert f"token={MASKED_TOKEN}" in curl
    assert TOKEN not in curl
    assert "-d 'goods_id=12'" in curl


def test_build_curl_is_empty_before_any_request(api_factory):
    """无请求上下文时返回空串而不是抛异常：附件钩子在任何时机调用都不能把用例带崩。"""
    assert api_factory().build_curl() == ""


# ---------------------------------------------------------------- 脱敏工具
def test_mask_payload_masks_token_and_passwords():
    """脱敏底线：token、pwd、password 都不能以明文进入 last_exchange / curl / Allure 附件。"""
    masked = BaseAPI.mask_payload({"token": TOKEN, "pwd": "123456", "password": "abcdef", "page": 1})

    assert masked["token"] == MASKED_TOKEN
    assert masked["pwd"] == "12***"
    assert masked["password"] == "ab***"
    assert masked["page"] == 1
    assert TOKEN not in str(masked)
    assert BaseAPI.mask_payload(None) is None, "非 dict 入参应原样返回，不抛异常"


def test_short_password_is_also_masked():
    """脱敏不应有长度例外：≤3 字符的密码同样是敏感信息，落进 curl/附件即为泄露。"""
    assert BaseAPI.mask_payload({"pwd": "123"})["pwd"] == "12***"
