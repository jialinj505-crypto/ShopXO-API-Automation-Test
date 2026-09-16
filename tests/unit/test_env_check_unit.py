"""环境能力探测（core/env_check.py）的离线单元测试，全部用 responses mock HTTP。

这条用例在防什么风险
--------------------
1. "离线承诺"被悄悄破坏：SHOPXO_OFFLINE=1 的意义是 PR 门禁"快、稳、不卡在别人的沙箱上"。
   只要 `probe()` 在离线分支里漏发一个请求，CI 就会重新依赖外部环境，所以这里用
   ``responses.calls`` 断言离线探测的**真实 HTTP 调用数为 0**——这是本文件最重要的一条守护。
2. 能力判定失准：插件未安装（code=-10 / msg 含"未安装"）、后台被禁用（页面含"非法访问"）
   如果判反了，要么是"该跳过的不跳过"→ 一片假红，要么是"能跑的不跑"→ 一片假绿；
   三种结果（已安装 / 未安装 / 探测失败）必须能被区分开。
3. 探测自身崩掉：沙箱超时、连接被拒、返回非 JSON 时，探测函数必须"不抛异常 + 明确说不可用"，
   否则环境探测反而会变成整个测试会话的失败源。
4. 谎报结论：离线模式下 ``summary()`` 必须明说"未探测"，而不是输出一串 False 让人
   误以为"环境没有这个能力"。

本文件零真实网络：所有 HTTP 交互都注册在 ``responses`` 上；未注册的请求会得到
ConnectionError，正好也被用来验证异常分支（调用仍被 ``responses.calls`` 记录）。
"""
import json

import pytest
import requests
import responses

from config.setting import ADMIN_PREFIX, API_PREFIX, BASE_URL
from core import env_check

# 本文件全部是"不依赖真实环境的框架自测"，离线模式下也会执行（见 tests/conftest.py 的钩子）
pytestmark = pytest.mark.offline

# 探测目标 URL：与 env_check 内部拼接方式保持一致，避免写死域名后与配置脱节
PLUGIN_URL = f"{BASE_URL}/{API_PREFIX.lstrip('/')}plugins/index"
ADMIN_URL = f"{BASE_URL}{ADMIN_PREFIX}login/index"


@pytest.fixture(autouse=True)
def isolate_cache(monkeypatch):
    """每个用例使用独立的 _CACHE：探测结果是模块级缓存，串味会让用例之间互相污染。"""
    monkeypatch.setattr(env_check, "_CACHE", {})


# ------------------------------------------------------------------ 离线承诺
@responses.activate
def test_probe_offline_makes_zero_http_requests(monkeypatch):
    """离线模式的核心承诺：probe() 返回占位结果，且真实 HTTP 调用数为 0。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)
    monkeypatch.setattr(env_check, "_CACHE", {"陈旧的探测结果": "不得被当成本次结果"})

    result = env_check.probe()

    assert result["offline"] is True
    assert result["reachable"] is None, "离线时『可达』必须是未知(None)，不能写成 False 谎报不可达"
    assert result["user_login"] is None
    assert result["features"] == {"coupon": False, "shop": False, "merchant": False}
    assert "陈旧的探测结果" not in result, "离线结果必须覆盖旧缓存"
    assert len(responses.calls) == 0, f"离线模式必须零网络请求，实际发出 {len(responses.calls)} 次"


@responses.activate
def test_probe_offline_does_not_touch_network_even_on_repeat_calls(monkeypatch):
    """重复调用 probe()（例如多个夹具都要能力矩阵）同样不得联网。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)

    for _ in range(3):
        assert env_check.probe()["offline"] is True

    assert len(responses.calls) == 0


@responses.activate
def test_offline_result_is_placeholder_not_false_claim():
    """offline_result() 必须把"未探测"和"不具备能力"区分开：可达/登录为 None，能力为 False。"""
    data = env_check.offline_result()

    assert data["base_url"] == BASE_URL
    assert data["offline"] is True
    assert data["reachable"] is None and data["user_login"] is None
    assert set(data["features"]) == {"coupon", "shop", "merchant"}
    assert all(value is False for value in data["features"].values())
    assert "离线" in data["details"]["mode"] and "未探测" in data["details"]["mode"]


@responses.activate
def test_probe_reuses_cache_without_extra_requests(monkeypatch):
    """非离线模式下已探测过的结果必须复用缓存（否则每次 capability() 都会再发一轮请求）。"""
    monkeypatch.setattr(env_check, "OFFLINE", False)
    cached = {"base_url": BASE_URL, "reachable": True, "user_login": True,
              "features": {"coupon": True, "shop": False, "merchant": False}, "from_cache": True}
    monkeypatch.setattr(env_check, "_CACHE", dict(cached))

    assert env_check.probe()["from_cache"] is True
    assert env_check.probe(force=False)["from_cache"] is True
    assert len(responses.calls) == 0, "命中缓存时不得发起任何请求"
    assert env_check._CACHE["from_cache"] is True, "缓存应被原地复用，而不是被替换掉"


# ------------------------------------------------------------------ 插件能力 _check_plugin()
@responses.activate
def test_check_plugin_reports_not_installed_for_code_minus_10():
    """接口返回 code=-10（应用未安装）时必须判定为"未安装"，并保留原因用于跳过说明。"""
    responses.add(responses.POST, PLUGIN_URL, json={"code": -10, "msg": "应用未安装[coupon]"})

    installed, message = env_check._check_plugin("coupon")

    assert installed is False
    assert "未安装" in message
    assert len(responses.calls) == 1
    assert "pluginsname=coupon" in responses.calls[0].request.body, "必须携带被探测的插件名"


@responses.activate
def test_check_plugin_reports_installed_for_code_zero():
    """接口返回 code=0 时判定为"已安装"，且原因取接口 msg。"""
    responses.add(responses.POST, PLUGIN_URL, json={"code": 0, "msg": "ok"})

    installed, message = env_check._check_plugin("shop")

    assert installed is True
    assert message == "ok"


@pytest.mark.parametrize(
    "payload, expected_installed",
    [
        ({"code": -10, "msg": "应用未安装[coupon]"}, False),
        ({"code": 0, "msg": "ok"}, True),
        ({"code": 0, "msg": "插件未安装"}, False),      # code 不规范但 msg 明确 → 仍判未安装
    ],
)
@responses.activate
def test_check_plugin_decision_matrix(payload, expected_installed):
    """判定矩阵：只要 msg 出现"未安装"就不算具备能力，避免不规范环境把缺失判成可用。"""
    responses.add(responses.POST, PLUGIN_URL, json=payload)

    installed, _ = env_check._check_plugin("coupon")

    assert installed is expected_installed


@responses.activate
def test_check_plugin_treats_non_json_response_as_probe_failure():
    """非 JSON 响应（被 WAF 或未登录登录页拦截）必须判为"探测失败"，不能当成"已安装"。

    原来这里固定的是缺陷行为：`code=None` 既不是 -10 也不含"未安装"，于是被算作"有插件"，
    结果环境拦截/接口契约变更被误报成"能力可用"——优惠券用例照跑并失败（假红），
    而不是按明确原因跳过。修复后统一判为探测失败，并在原因里带上 HTTP 状态码。
    """
    responses.add(responses.POST, PLUGIN_URL, body="<html>请先登录</html>", status=200)

    installed, message = env_check._check_plugin("coupon")

    assert installed is False
    assert "探测失败" in message and "非 JSON" in message
    assert "200" in message, "原因里应带 HTTP 状态码，便于判断是不是被网关/WAF 拦了"


@responses.activate
def test_check_plugin_treats_other_error_code_as_probe_failure():
    """除 -10 以外的业务错误码同样判为"探测失败"：能力可用必须由 code=0 明确给出。

    原来固定的是缺陷行为：任何非 -10 的 code（如 -1 参数错误）都算"已安装"，
    接口参数变更或鉴权失效会被误报成能力可用（假红）而不是按原因跳过。
    """
    responses.add(responses.POST, PLUGIN_URL, json={"code": -1, "msg": "参数错误"})

    installed, message = env_check._check_plugin("coupon")

    assert installed is False
    assert "探测失败" in message and "-1" in message


@responses.activate
def test_check_plugin_survives_timeout():
    """探测超时不能把异常抛给调用方：必须返回"未安装 + 可读原因"。"""
    responses.add(responses.POST, PLUGIN_URL, body=requests.exceptions.Timeout("mock timeout"))

    installed, message = env_check._check_plugin("coupon")

    assert installed is False
    assert "探测异常" in message
    assert "Timeout" in message


@responses.activate
def test_check_plugin_survives_connection_error():
    """连接被拒/地址写错（未注册任何 mock 时 responses 抛 ConnectionError）同样不能崩。"""
    installed, message = env_check._check_plugin("coupon")

    assert installed is False
    assert "探测异常" in message and "ConnectionError" in message
    assert len(responses.calls) == 1


@responses.activate
def test_check_plugin_should_keep_exception_reason():
    """探测失败的原因里必须包含异常原文（例如"mock timeout"）与异常类型，而不是只有类名。"""
    responses.add(responses.POST, PLUGIN_URL, body=requests.exceptions.Timeout("mock timeout"))

    _, message = env_check._check_plugin("coupon")

    assert "mock timeout" in message


# ------------------------------------------------------------------ 后台入口 _check_admin()
@responses.activate
def test_check_admin_disabled_when_page_says_illegal_access():
    """后台被禁用（页面含"非法访问"）时必须判为不可用，并给出可读原因（用于跳过说明）。"""
    responses.add(responses.GET, ADMIN_URL, body="<html><body>非法访问：您没有权限访问该页面</body></html>", status=200)

    available, reason = env_check._check_admin()

    assert available is False
    assert "非法访问" in reason
    assert len(responses.calls) == 1
    assert ADMIN_URL in str(responses.calls[0].request.url)


@responses.activate
def test_check_admin_available_on_login_page():
    """正常登录页（含"登录"/"密码"关键字）必须判为可用，否则后台用例会被无谓跳过。"""
    responses.add(
        responses.GET, ADMIN_URL,
        body="<html><head><title>商家登录</title></head><body>请输入密码 password</body></html>",
        status=200,
    )

    available, reason = env_check._check_admin()

    assert available is True
    assert "登录页" in reason


@responses.activate
def test_check_admin_unavailable_on_http_500():
    """后端 5xx 时必须判为不可用（且不能被页面里的"登录"字样骗过去）。"""
    responses.add(responses.GET, ADMIN_URL, body="<html>登录 密码</html>", status=500)

    available, reason = env_check._check_admin()

    assert available is False
    assert "500" in reason


@responses.activate
def test_check_admin_unavailable_on_unrecognized_content():
    """页面内容既不是登录页也不是明确的拒绝时，按"无法识别"处理，不猜成可用。"""
    responses.add(responses.GET, ADMIN_URL, body="OK", status=200)

    available, reason = env_check._check_admin()

    assert available is False
    assert "无法识别" in reason


@responses.activate
def test_check_admin_survives_network_error():
    """后台探测网络异常时必须返回不可用而不是抛异常。"""
    responses.add(responses.GET, ADMIN_URL, body=requests.exceptions.ConnectionError("mock refused"))

    available, reason = env_check._check_admin()

    assert available is False
    assert "探测异常" in reason and "ConnectionError" in reason


# ------------------------------------------------------------------ capability()
@pytest.mark.parametrize("name, expected", [("coupon", True), ("shop", False), ("merchant", False)])
def test_capability_reads_feature_matrix(monkeypatch, name, expected):
    """capability(name) 必须严格按能力矩阵返回布尔值，未知能力按 False 处理（不抛 KeyError）。"""
    monkeypatch.setattr(env_check, "OFFLINE", False)
    monkeypatch.setattr(
        env_check, "_CACHE",
        {"features": {"coupon": True, "shop": False, "merchant": False}},
    )

    assert env_check.capability(name) is expected
    assert env_check.capability("not_exist_feature") is False


def test_capability_false_when_offline(monkeypatch):
    """离线模式下所有能力按"不具备"返回 False：requires 门控只会跳过，不会误跑真环境用例。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)

    assert env_check.capability("coupon") is False
    assert env_check.capability("shop") is False
    assert env_check.capability("merchant") is False


def test_feature_enum_values_are_stable():
    """Feature 枚举值是能力矩阵的 key（也是 @pytest.mark.requires("coupon") 的取值），不得随意改名。"""
    assert [feature.value for feature in env_check.Feature] == ["coupon", "shop", "merchant"]
    assert env_check.Feature("coupon") is env_check.Feature.COUPON


# ------------------------------------------------------------------ summary()
def test_summary_includes_environment_and_all_capabilities():
    """能力矩阵文本必须包含被测环境/可达/登录/三项能力，否则报告里看不出"为什么没跑"。"""
    data = {
        "base_url": BASE_URL,
        "reachable": True,
        "user_login": True,
        "features": {"coupon": False, "shop": True, "merchant": False},
    }

    text = env_check.summary(data)

    for keyword in ("被测环境", BASE_URL, "环境可达", "用户登录", "优惠券插件", "多商户插件", "商家后台"):
        assert keyword in text, f"能力矩阵缺少关键字段：{keyword}"
    assert "True" in text and "False" in text, "真实探测结果应按原始布尔值展示"


@responses.activate
def test_summary_offline_says_not_probed_instead_of_false(monkeypatch):
    """离线模式下必须说明"离线/未探测"，绝不能输出一串 False 谎报"环境不具备能力"。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)

    text = env_check.summary()

    assert BASE_URL in text, "即使未探测，也应说明配置的被测环境是哪一个"
    assert "离线" in text and "未探测" in text
    assert "False" not in text, f"离线时不得展示 False 能力值：{text}"
    assert len(responses.calls) == 0


# ------------------------------------------------------------------ dump()
@responses.activate
def test_dump_writes_parseable_json(tmp_path, monkeypatch):
    """dump() 必须把探测结果写成可解析的 UTF-8 JSON（CI 归档与问题回溯依赖它）。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)
    path = tmp_path / "env_probe.json"

    env_check.dump(path)

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["offline"] is True
    assert payload["base_url"] == BASE_URL
    assert set(payload["features"]) == {"coupon", "shop", "merchant"}
    assert "离线" in payload["details"]["mode"], "中文不得被转义成 \\uXXXX 之外的乱码"
    assert len(responses.calls) == 0


def test_dump_failure_only_warns_and_does_not_raise(tmp_path, monkeypatch):
    """落盘失败（目录不存在）只应告警：报告归档问题不能反过来让用例报错。"""
    monkeypatch.setattr(env_check, "OFFLINE", True)
    bad_path = tmp_path / "not_exist_dir" / "env_probe.json"

    env_check.dump(bad_path)

    assert not bad_path.exists()
