"""订单模块测试：确认订单、提交订单、状态机、取消/删除/收货/支付/评价（数据驱动 data/order_data.json）。"""
import pytest

from api_objects.order_api import OrderAPI
from config.setting import API_PREFIX, DEFAULT_GOODS_ID
from core.allure_utils import attach_json, mark, step
from core.assert_helper import Assert
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("order_data.json")


def _group(name: str):
    return [c for c in CASES if c.get("group") == name]


# ----------------------------------------------------------------- 确认订单
@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("confirm")), ids=case_ids(_group("confirm")))
def test_order_confirm_invalid(order_api, case):
    """订单确认页异常参数：购物车ID不存在 / 缺少购物车ID。"""
    mark(feature="订单模块", story="订单确认页")
    with step(f"确认订单：ids={case.get('ids')!r}"):
        if case.get("ids") is None:
            res = order_api.post(f"{API_PREFIX}buy/index", data={"buy_type": case.get("buy_type", "cart")})
        else:
            res = order_api.confirm(case["ids"], buy_type=case.get("buy_type", "cart"), address_id=0)

    Assert.code(res, case["expected_code"], case["desc"])
    Assert.msg_contains(res, case["expected_msg"])


@pytest.mark.p0
@pytest.mark.positive
def test_order_confirm_amount_matches_cart(order_api, cart_api, clean_cart, temp_address):
    """订单确认页金额与购物车数据一致性（业务计算校验）。"""
    mark(feature="订单模块", story="订单确认页")
    cart_api.add(DEFAULT_GOODS_ID, 2)
    item = cart_api.find_item(DEFAULT_GOODS_ID)
    Assert.not_none(item, "购物车记录")

    with step("调用订单确认接口"):
        res = order_api.confirm(item["id"], address_id=temp_address["id"])
    Assert.success(res, "订单确认")
    data = res["data"]
    Assert.has_fields(data, "goods_list", "payment_list", "base")
    base = data["base"]
    Assert.has_fields(base, "total_price", "actual_price", "goods_count", "increase_price", "preferential_price")

    Assert.money(base["total_price"], item["total_price"], "订单确认页商品总额", tol=0.02)
    # 注意：base.goods_count 的语义是"商品种类数(购物车行数)"，不是商品件数(件数=各行 stock 之和)
    Assert.is_true(
        int(base["goods_count"]) == 1,
        f"商品种类数不符：期望 1，实际 {base['goods_count']}",
    )
    Assert.is_true(len(data["payment_list"]) >= 1, "订单确认页应返回可用支付方式")
    for payment in data["payment_list"]:
        Assert.has_fields(payment, "id", "name")


# ----------------------------------------------------------------- 提交订单
@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("submit_bad_goods")), ids=case_ids(_group("submit_bad_goods")))
def test_order_submit_invalid_goods(order_api, case):
    """提交订单异常：商品不存在。"""
    mark(feature="订单模块", story="提交订单")
    res = order_api.submit(case["ids"], address_id=0, payment_id=case.get("payment_id", 3))
    Assert.code(res, case["expected_code"], case["desc"])
    Assert.msg_contains(res, case["expected_msg"])


@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("submit_bad_payment")), ids=case_ids(_group("submit_bad_payment")))
def test_order_submit_invalid_payment(order_api, cart_api, clean_cart, temp_address, case):
    """提交订单异常：支付方式非法（需真实购物车数据）。"""
    mark(feature="订单模块", story="提交订单")
    cart_api.add(DEFAULT_GOODS_ID, 1)
    item = cart_api.find_item(DEFAULT_GOODS_ID)

    res = order_api.submit(item["id"], address_id=temp_address["id"], payment_id=case["payment_id"])
    Assert.code(res, case["expected_code"], case["desc"])
    Assert.msg_contains(res, case["expected_msg"])


@pytest.mark.p0
@pytest.mark.negative
def test_order_submit_blocks_exceed_inventory(order_api, cart_api, clean_cart, temp_address, payment_id):
    """库存防线：下单环节必须拦截超过库存的数量。

    说明：加购环节未拦截超库存属于已记录缺陷（BUG-CART-STOCK-001），
    本用例验证最后一道防线（提交订单）是有效的，避免真正产生超卖订单。
    """
    mark(feature="订单模块", story="库存校验")
    cart_api.add(DEFAULT_GOODS_ID, 999999)
    item = cart_api.find_item(DEFAULT_GOODS_ID)
    Assert.not_none(item, "购物车记录")

    with step("使用超库存数量提交订单"):
        res = order_api.submit(item["id"], address_id=temp_address["id"], payment_id=payment_id)
    Assert.fail(res, "超库存下单")
    Assert.msg_contains(res, "库存")


@pytest.mark.p0
@pytest.mark.positive
def test_order_submit_success(order_api, cart_api, clean_cart, temp_address, payment_id):
    """提交订单成功：返回订单号，且下单后该商品从购物车移除。"""
    mark(feature="订单模块", story="提交订单")
    cart_api.add(DEFAULT_GOODS_ID, 1)
    item = cart_api.find_item(DEFAULT_GOODS_ID)

    with step("提交订单"):
        res = order_api.submit(item["id"], address_id=temp_address["id"], payment_id=payment_id)
    Assert.success(res, "提交订单")
    order_ids = (res.get("data") or {}).get("order_ids") or []
    Assert.not_empty(order_ids, "提交订单未返回订单号")
    order_id = order_ids[0]

    try:
        Assert.is_true(cart_api.find_item(DEFAULT_GOODS_ID) is None, "下单后商品应从购物车移除")
        detail = order_api.detail(order_id)
        Assert.success(detail, "订单详情")
        status, status_name = OrderAPI.status_of(detail)
        Assert.is_true(str(status) in ("1", "2"), f"新订单状态异常：status={status} name={status_name}")
    finally:
        order_api.cancel(order_id)
        order_api.delete(order_id)


# ----------------------------------------------------------------- 查询
@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("detail")), ids=case_ids(_group("detail")))
def test_order_detail_invalid(order_api, case):
    """订单详情异常：订单不存在。"""
    mark(feature="订单模块", story="订单详情")
    res = order_api.detail(case["order_id"])
    Assert.code(res, case["expected_code"], case["desc"])
    Assert.msg_contains(res, case["expected_msg"])


@pytest.mark.smoke
@pytest.mark.positive
def test_order_detail_schema(order_api, temp_order):
    """订单详情结构校验（JSON Schema）+ 关键业务字段。"""
    mark(feature="订单模块", story="订单详情")
    res = order_api.detail(temp_order["id"])
    Assert.success(res, "订单详情")
    Assert.schema(res, "order_detail", "订单详情")

    data = res["data"]["data"]
    Assert.is_true(str(data["status"]) == "1", f"新订单应为待付款(status=1)，实际 {data['status']}")
    Assert.is_true("待付款" in str(data["status_name"]), f"状态名称异常：{data['status_name']}")
    Assert.is_true(str(data["pay_status"]) == "0", f"支付状态异常：{data['pay_status']}")
    Assert.not_empty(data.get("order_no"), "订单号")
    Assert.is_true(float(data["total_price"]) >= 0, "订单金额异常")


@pytest.mark.positive
def test_order_list_structure(order_api, token):
    """订单列表：分页结构与订单关键字段完整性。"""
    mark(feature="订单模块", story="订单列表")
    res = order_api.list(page=1, status="-1")
    Assert.success(res, "订单列表(全部)")
    Assert.pagination(res["data"], "订单列表")
    Assert.has_fields(res["data"], "payment_list")

    for item in res["data"]["data"]:
        Assert.has_fields(item, "id", "order_no", "status", "status_name", "total_price", "pay_price")
        Assert.is_true(float(item["total_price"]) >= 0, f"订单金额异常：{item['total_price']}")


@pytest.mark.xfail(
    reason="缺陷 BUG-ORDER-FILTER-001：订单列表 status 筛选参数未生效——实测 status 取 -1/0/1/2/3/4/5/6 "
           "均返回同一份数据(total 恒为 230)，且返回值里出现与筛选条件不符的状态，前端按状态筛选订单功能失效",
    strict=False,
)
@pytest.mark.negative
def test_order_list_status_filter_should_narrow_results(order_api, token):
    """订单列表状态筛选（期望）：status=1 只返回待付款订单，且不同状态的数据集不同。"""
    pending = order_api.list(page=1, status="1")
    canceled = order_api.list(page=1, status="5")
    Assert.success(pending, "订单列表(待付款)")
    Assert.success(canceled, "订单列表(已取消)")

    for item in pending["data"]["data"]:
        Assert.is_true(str(item["status"]) == "1", f"待付款列表出现 status={item['status']} 的记录")
    for item in canceled["data"]["data"]:
        Assert.is_true(str(item["status"]) == "5", f"已取消列表出现 status={item['status']} 的记录")
    Assert.is_true(
        int(pending["data"]["total"]) != int(canceled["data"]["total"]),
        "不同状态筛选返回的订单总数完全相同，说明筛选条件未生效",
    )


# ----------------------------------------------------------------- 状态机
@pytest.mark.p0
@pytest.mark.positive
def test_order_cancel_status_machine(order_api, temp_order):
    """订单状态机：待付款(1) -> 取消 -> 已取消(5)，且不可重复取消。"""
    mark(feature="订单模块", story="订单状态机")
    order_id = temp_order["id"]

    with step("取消前：状态应为待付款"):
        before = order_api.detail(order_id)
        status_before, name_before = OrderAPI.status_of(before)
        Assert.is_true(str(status_before) == "1", f"取消前状态异常：{status_before} {name_before}")

    with step("取消订单"):
        cancel = order_api.cancel(order_id)
    Assert.success(cancel, "取消订单")

    with step("取消后：状态应为已取消"):
        after = order_api.detail(order_id)
        status_after, name_after = OrderAPI.status_of(after)
        attach_json({"before": {"status": status_before, "name": name_before},
                     "after": {"status": status_after, "name": name_after}}, name="订单状态变化")
        Assert.is_true(str(status_after) == "5", f"取消后状态异常：{status_after} {name_after}")
        Assert.is_true("取消" in str(name_after), f"状态名称应包含'取消'，实际 {name_after}")
        Assert.is_true(str(status_after) != str(status_before), "订单状态未发生变化")

    with step("重复取消应被拦截"):
        again = order_api.cancel(order_id)
        Assert.fail(again, "重复取消订单")
        Assert.msg_contains(again, "状态不可操作")

    with step("终态订单可删除"):
        Assert.success(order_api.delete(order_id), "删除已取消订单")
        deleted = order_api.delete(order_id)
        Assert.fail(deleted, "重复删除订单")
        Assert.msg_contains(deleted, "不存在")


@pytest.mark.negative
def test_order_delete_pending_blocked(order_api, temp_order):
    """业务规则：待付款订单不允许直接删除（必须先取消）。"""
    res = order_api.delete(temp_order["id"])
    Assert.fail(res, "删除待付款订单")
    Assert.msg_contains(res, "状态不可操作")


@pytest.mark.negative
def test_order_collect_pending_blocked(order_api, temp_order):
    """业务规则：未付款订单不允许确认收货。"""
    res = order_api.collect(temp_order["id"])
    Assert.fail(res, "待付款订单确认收货")
    Assert.msg_contains(res, "状态不可操作")


@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("cancel")), ids=case_ids(_group("cancel")))
def test_order_cancel_invalid(order_api, case):
    """异常场景：取消不存在的订单。"""
    res = order_api.cancel(case["order_id"])
    Assert.fail(res, case["desc"])


@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(_group("delete")), ids=case_ids(_group("delete")))
def test_order_delete_invalid(order_api, case):
    """异常场景：删除不存在的订单。"""
    res = order_api.delete(case["order_id"])
    Assert.fail(res, case["desc"])


@pytest.mark.negative
def test_order_pay_offline_payment(order_api, temp_order):
    """支付：货到付款方式不支持在线支付，应被拦截而不是返回成功。

    沙箱环境只提供"货到付款"(payment_id=3)，因此在线支付成功链路无法在此环境验证，
    本用例只保证"不支持的支付方式不会被误判为成功"。
    """
    res = order_api.pay(temp_order["id"], temp_order["payment_id"])
    Assert.fail(res, "货到付款订单调用在线支付")
    Assert.not_empty(res.get("msg"), "失败提示 msg")


@pytest.mark.xfail(
    reason="缺陷 BUG-ORDER-COMMENT-001：待付款订单调用评价接口返回 code=0(提交成功)，但订单评价状态未变化(is_comments 仍为 0)，属于接口响应与实际结果不符的静默失败",
    strict=False,
)
@pytest.mark.negative
def test_order_comments_on_pending_should_be_rejected(order_api, temp_order):
    """业务规则（期望）：未完成订单不允许评价；当前实测返回 code=0 但未生成评价。"""
    order_id = temp_order["id"]
    before = (order_api.detail(order_id)["data"]["data"] or {}).get("is_comments")
    res = order_api.comments(order_id, content="自动化测试评价内容", rating=5)
    after = (order_api.detail(order_id)["data"]["data"] or {}).get("is_comments")

    Assert.fail(res, f"待付款订单评价（评价状态 before={before} after={after}）")
