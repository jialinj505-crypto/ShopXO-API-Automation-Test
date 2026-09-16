"""商家模块（后台管理端）测试。

执行前提：被测环境开放商家后台入口（admin.php）且后台账号可用。
当前沙箱环境后台入口被禁用（探测结果为"非法访问"），
本文件所有用例都带 @pytest.mark.requires("merchant")，会被自动跳过并在报告中说明原因；
在后台可用的环境上（本地部署 / 预发），无需改代码即可直接执行。
"""
import pytest

from core.allure_utils import mark, step
from core.assert_helper import Assert
from core.data_loader import build_params, case_ids, load_cases

pytestmark = pytest.mark.requires("merchant")

CASES = load_cases("admin_data.json")


def _group(name: str):
    return [c for c in CASES if c.get("group") == name]


@pytest.mark.p0
@pytest.mark.parametrize("case", build_params(_group("login")), ids=case_ids(_group("login")))
def test_admin_login(admin_api, case):
    """商家后台登录成功并能访问后台首页。"""
    mark(feature="商家模块", story="后台登录", title=case["desc"])
    with step("调用后台登录接口"):
        res = admin_api.login()
    Assert.code(res, case["expected_code"], case["desc"])
    Assert.is_true(admin_api.is_logged_in(), "后台登录后无法访问后台首页，会话未生效")


@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("login_negative")), ids=case_ids(_group("login_negative")))
def test_admin_login_wrong_password(admin_api, case):
    """商家后台登录异常：密码错误应被拦截。"""
    res = admin_api.login(pwd=case["pwd"])
    Assert.fail(res, case["desc"])


@pytest.mark.p0
@pytest.mark.parametrize("case", build_params(_group("goods")), ids=case_ids(_group("goods")))
def test_admin_goods_list(admin_api, case):
    """商家后台商品列表查询（商家可管理自己店铺的商品）。"""
    mark(feature="商家模块", story="商品管理")
    admin_api.login()
    res = admin_api.goods_list(page=case.get("page", 1))
    Assert.code(res, case["expected_code"], case["desc"])
    Assert.is_true(isinstance(res.get("data"), (dict, list)), "商品列表结构异常")


@pytest.mark.p0
@pytest.mark.parametrize("case", build_params(_group("order")), ids=case_ids(_group("order")))
def test_admin_order_list(admin_api, case):
    """商家后台订单列表查询（商家视角的订单管理）。"""
    mark(feature="商家模块", story="订单管理")
    admin_api.login()
    res = admin_api.order_list(page=case.get("page", 1), status=case.get("status", "-1"))
    Assert.code(res, case["expected_code"], case["desc"])


@pytest.mark.parametrize("case", build_params(_group("coupon")), ids=case_ids(_group("coupon")))
def test_admin_coupon_list(admin_api, case):
    """商家后台优惠券列表查询（发券管理）。"""
    mark(feature="商家模块", story="优惠券管理")
    admin_api.login()
    res = admin_api.coupon_list(page=case.get("page", 1))
    Assert.code(res, case["expected_code"], case["desc"])
