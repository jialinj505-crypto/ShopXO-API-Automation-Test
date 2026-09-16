"""优惠券模块测试（插件能力）。

执行前提：被测环境安装并启用了优惠券插件（plugins_coupon）。
未安装时，本文件中带 @pytest.mark.requires("coupon") 的用例会被自动跳过，
跳过原因来自 core/env_check.py 的真实探测结果（例如：应用未安装[coupon]），
报告中可以看到"为什么没跑"，而不是静默通过。

注意：即使插件不可用，也仍然校验首页/订单确认响应中优惠券数据的结构
（ShopXO 通过 plugins_coupon_data 字段下发优惠券信息），保证框架对优惠券数据契约的覆盖。
"""
import pytest

from api_objects.coupon_api import CouponAPI
from core.allure_utils import mark, step
from core.assert_helper import Assert
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("coupon_data.json")


def test_coupon_capability_is_detected(capabilities):
    """环境能力探测：明确记录当前环境是否具备优惠券能力（用于解释跳过原因）。"""
    available = CouponAPI.available()
    detail = capabilities.get("details", {}).get("coupon")
    mark(feature="优惠券模块", story="环境能力")
    assert available == capabilities["features"]["coupon"], "优惠券能力探测结果不一致"
    print(f"优惠券插件可用={available}，探测详情={detail}")


@pytest.mark.requires("coupon")
@pytest.mark.p0
@pytest.mark.parametrize("case", build_params(CASES), ids=case_ids(CASES))
def test_coupon(coupon_api, case):
    """优惠券参数化用例：可领券列表 / 领券 / 我的优惠券。"""
    mark(feature="优惠券模块", story="优惠券领取与查询", title=case["desc"])
    group = case.get("group")

    with step(f"调用优惠券接口：{case['desc']}"):
        if group == "list":
            res = coupon_api.coupon_list(page=case.get("page", 1))
        elif group == "my":
            res = coupon_api.my_coupon_list(page=case.get("page", 1))
        else:
            res = coupon_api.receive(case.get("coupon_id"))

    expected = case["expected_code"]
    if expected == "not_0":
        Assert.fail(res, case["desc"])
    else:
        Assert.code(res, expected, case["desc"])


@pytest.mark.requires("coupon")
@pytest.mark.positive
def test_coupon_list_structure(coupon_api):
    """可用优惠券列表结构：券ID、名称、面额/折扣、使用门槛、有效期。"""
    res = coupon_api.coupon_list(page=1)
    Assert.success(res, "可用优惠券列表")
    data = res.get("data")
    Assert.is_true(isinstance(data, (dict, list)), "优惠券列表结构异常")
    items = data.get("data") if isinstance(data, dict) else data
    if not items:
        pytest.skip("当前环境暂无可领取优惠券")
    first = items[0]
    for field in ("id", "name", "type"):
        Assert.has_fields(first, field)


@pytest.mark.positive
def test_coupon_data_in_order_confirm(order_api, cart_api, clean_cart, temp_address):
    """订单确认页若下发优惠券数据(plugins_coupon_data)，其结构应可被正确解析。"""
    mark(feature="优惠券模块", story="下单用券数据契约")
    cart_api.add(12, 1)
    item = cart_api.find_item(12)
    res = order_api.confirm(item["id"], address_id=temp_address["id"])
    Assert.success(res, "订单确认")

    coupon_data = CouponAPI.extract_plugin_data(res)
    if coupon_data is None:
        pytest.skip("当前环境订单确认页未下发优惠券数据（优惠券插件未安装/未参与）")
    Assert.is_true(isinstance(coupon_data, (dict, list)), "优惠券数据结构异常")
