"""用户登录模块测试：正向 / 边界 / 异常 / 安全（数据驱动 data/login_data.json）。"""
import pytest

from config.setting import API_PREFIX
from core.allure_utils import attach_json, mark, step
from core.assert_helper import Assert
from core.auth import TOKEN_INVALID_CODES, AuthType, TokenManager
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("login_data.json")


@pytest.mark.p0
@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(CASES), ids=case_ids(CASES))
def test_login(user_api, case):
    """登录接口参数化用例：覆盖正向、边界、异常、安全场景。"""
    mark(feature="用户模块", story="用户登录", title=case["desc"], severity="critical" if case["expected_code"] == 0 else "normal")
    with step(f"调用登录接口：{case['desc']}"):
        res = user_api.login(case["accounts"], case["pwd"], type=case.get("type"))
    attach_json(res, name=f"登录响应-{case['desc']}")

    expected = case["expected_code"]
    if expected == "not_0":
        Assert.fail(res, case["desc"])
        Assert.not_empty(res.get("msg"), "失败提示 msg")
    else:
        Assert.code(res, expected, case["desc"])
        if case.get("expected_msg"):
            Assert.msg_equals(res, case["expected_msg"])

    if case.get("schema"):
        Assert.schema(res, case["schema"], case["desc"])

    if case.get("expect_token"):
        Assert.has_fields(res["data"], "token", "id", "username")
        Assert.is_true(len(str(res["data"]["token"])) >= 8, "token 长度不足，可能不是有效登录态")
        Assert.in_set(str(res["data"]["username"]), [str(case["accounts"])], "登录账号")


@pytest.mark.p0
@pytest.mark.positive
def test_login_token_usable_for_protected_api(user_api, cart_api, account):
    """登录返回的 token 可直接访问需要鉴权的接口（token 有效性）。"""
    login = user_api.login(account["accounts"], account["pwd"], account.get("type", "username"))
    Assert.success(login, "登录")
    TokenManager.set_token(AuthType.USER, login["data"]["token"])

    with step("使用该 token 访问购物车列表"):
        res = cart_api.list()
    Assert.success(res, "token 访问受保护接口")
    Assert.has_fields(res.get("data"), "data", "common_cart_total")


@pytest.mark.negative
def test_protected_api_rejects_fake_token(cart_api):
    """鉴权校验：伪造 token 访问受保护接口必须被拦截（code=-400 登录失效）。"""
    res = cart_api.post(
        f"{API_PREFIX}cart/index",
        data={"token": "fake_token_for_autotest"},
        auth=AuthType.NONE,
    )
    Assert.code(res, -400, "伪造 token")
    Assert.msg_contains(res, "登录失效")
    Assert.is_true(-400 in TOKEN_INVALID_CODES, "框架未把 -400 识别为 token 失效码，自动重登会失效")


@pytest.mark.negative
def test_protected_api_rejects_missing_token(cart_api):
    """鉴权校验：不携带 token 访问受保护接口必须被拦截。"""
    res = cart_api.post(f"{API_PREFIX}cart/index", auth=AuthType.NONE)
    Assert.code(res, -400, "缺少 token")
    Assert.msg_contains(res, "登录失效")


@pytest.mark.smoke
def test_token_is_cached_and_reused(cart_api, token):
    """统一鉴权封装：token 会话级缓存，多次调用受保护接口不会重复登录。"""
    times_before = TokenManager.login_times(AuthType.USER)
    cart_api.list()
    cart_api.list()
    times_after = TokenManager.login_times(AuthType.USER)
    Assert.is_true(
        times_after == times_before,
        f"token 未复用：调用前登录 {times_before} 次，调用后 {times_after} 次（说明发生了重复登录）",
    )
    Assert.not_empty(token, "token")
