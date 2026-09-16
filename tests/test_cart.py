"""购物车模块测试：加购校验、数量修改、删除、金额一致性（数据驱动 data/cart_data.json）。"""
import pytest

from config.setting import API_PREFIX, DEFAULT_GOODS_ID
from core.allure_utils import attach_json, mark, step
from core.assert_helper import Assert
from core.auth import AuthType
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("cart_data.json")
ADD_CASES = [c for c in CASES if c.get("group") in (None, "add")]


@pytest.mark.p0
@pytest.mark.boundary
@pytest.mark.parametrize("case", build_params(ADD_CASES), ids=case_ids(ADD_CASES))
def test_cart_add(cart_api, clean_cart, case):
    """加购参数化用例：正向 / 数量边界 / 商品不存在 / 缺参数 / 超库存缺陷。

    `clean_cart` 夹具负责前后清空购物车，保证用例可重复执行且不污染环境。
    """
    mark(feature="购物车模块", story="加入购物车", title=case["desc"])
    with step(f"加购：goods_id={case.get('goods_id')!r} stock={case.get('stock')}"):
        if case.get("goods_id") is None:
            res = cart_api.post(f"{API_PREFIX}cart/save", data={"stock": case.get("stock")})
        else:
            res = cart_api.add(case["goods_id"], case.get("stock"))
    attach_json(res, name=f"加购响应-{case['desc']}")

    expected = case["expected_code"]
    if expected == "not_0":
        Assert.fail(res, case["desc"])
    else:
        Assert.code(res, expected, case["desc"])
    if case.get("expected_msg"):
        Assert.msg_contains(res, case["expected_msg"])


@pytest.mark.p0
@pytest.mark.positive
def test_cart_repeat_add_accumulates_quantity(cart_api, clean_cart):
    """重复加购同一商品应累加数量，而不是产生多条购物车记录。"""
    Assert.success(cart_api.add(DEFAULT_GOODS_ID, 1), "第一次加购")
    Assert.success(cart_api.add(DEFAULT_GOODS_ID, 1), "第二次加购")

    res = cart_api.list()
    Assert.success(res, "购物车列表")
    items = [i for i in res["data"]["data"] if str(i["goods_id"]) == str(DEFAULT_GOODS_ID)]
    Assert.is_true(len(items) == 1, f"重复加购产生了 {len(items)} 条记录，应合并为 1 条")
    Assert.is_true(str(items[0]["stock"]) == "2", f"数量未累加，实际 stock={items[0]['stock']}")


@pytest.mark.smoke
def test_cart_list_schema_and_total(cart_api, clean_cart):
    """购物车列表结构 + common_cart_total 与实际条目数一致。"""
    cart_api.add(DEFAULT_GOODS_ID, 2)
    res = cart_api.list()
    Assert.success(res, "购物车列表")
    Assert.schema(res, "cart_list", "购物车列表")

    items = res["data"]["data"]
    Assert.is_true(len(items) >= 1, "购物车应至少有 1 条记录")
    # 注意：common_cart_total 的语义是"购物车商品种类数(记录行数)"，不是商品件数
    Assert.is_true(
        int(res["data"]["common_cart_total"]) == len(items),
        f"购物车商品总数与明细行数不一致：common_cart_total={res['data']['common_cart_total']}，明细 {len(items)} 行",
    )


@pytest.mark.positive
def test_cart_total_price_equals_price_times_stock(cart_api, clean_cart):
    """金额校验：单条记录小计 = 单价 × 数量（业务计算正确性）。"""
    cart_api.add(DEFAULT_GOODS_ID, 3)
    item = cart_api.find_item(DEFAULT_GOODS_ID)
    Assert.not_none(item, "购物车记录")

    expected = float(item["price"]) * int(item["stock"])
    Assert.money(item["total_price"], expected, "购物车小计", tol=0.01)


@pytest.mark.positive
def test_cart_update_stock(cart_api, clean_cart):
    """修改购物车数量：接口返回成功，且列表中的数量随之更新。"""
    cart_api.add(DEFAULT_GOODS_ID, 1)
    item = cart_api.find_item(DEFAULT_GOODS_ID)

    with step("把购物车数量修改为 4"):
        res = cart_api.update_stock(item["id"], DEFAULT_GOODS_ID, 4)
    Assert.success(res, "修改数量")

    updated = cart_api.find_item(DEFAULT_GOODS_ID)
    Assert.is_true(str(updated["stock"]) == "4", f"数量未更新，实际 stock={updated['stock']}")


@pytest.mark.negative
def test_cart_update_stock_invalid_cart_id(cart_api, clean_cart):
    """异常场景：修改不存在的购物车记录应被拦截。"""
    res = cart_api.update_stock(99999999, DEFAULT_GOODS_ID, 1)
    Assert.fail(res, "修改不存在的购物车记录")
    Assert.not_empty(res.get("msg"), "失败提示 msg")


@pytest.mark.p0
@pytest.mark.positive
def test_cart_delete_and_repeat_delete(cart_api, clean_cart):
    """删除购物车：首次删除成功，重复删除返回失败（幂等性校验）。"""
    cart_api.add(DEFAULT_GOODS_ID, 1)
    item = cart_api.find_item(DEFAULT_GOODS_ID)

    Assert.success(cart_api.delete(item["id"]), "删除购物车商品")
    Assert.is_true(cart_api.find_item(DEFAULT_GOODS_ID) is None, "删除后购物车仍存在该商品")

    again = cart_api.delete(item["id"])
    Assert.code(again, -100, "重复删除")
    Assert.msg_contains(again, "删除失败")


@pytest.mark.negative
def test_cart_delete_without_id(cart_api, clean_cart):
    """异常场景：删除时不传 id 应被拦截。"""
    res = cart_api.delete("")
    Assert.fail(res, "缺少删除id")
    Assert.msg_contains(res, "id")


@pytest.mark.positive
def test_cart_clear_removes_all_items(cart_api, clean_cart):
    """批量删除：一次请求可清理多条购物车记录（用例环境清理能力）。"""
    cart_api.add(DEFAULT_GOODS_ID, 1)
    removed = cart_api.clear()
    Assert.is_true(removed >= 1, f"清理条数异常：{removed}")
    Assert.is_true(cart_api.list()["data"]["data"] == [], "购物车未清空")


@pytest.mark.negative
def test_cart_add_with_fake_token_rejected(cart_api):
    """鉴权校验：伪造 token 加购必须被拦截。"""
    res = cart_api.post(
        f"{API_PREFIX}cart/save",
        data={"goods_id": DEFAULT_GOODS_ID, "stock": 1, "token": "fake_token_for_autotest"},
        auth=AuthType.NONE,
    )
    Assert.code(res, -400, "伪造 token 加购")
