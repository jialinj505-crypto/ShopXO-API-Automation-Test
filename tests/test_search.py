"""商品搜索模块测试：关键字、筛选、分页、异常输入（数据驱动 data/search_data.json）。"""
import pytest

from core.allure_utils import mark, step
from core.assert_helper import Assert
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("search_data.json")
FILTER_KEYS = ("category_ids", "brand_id", "screening_price", "order_by")


def _min_price(value) -> float:
    """商品价格可能是区间（多规格商品，如 '160.00-258.00'），这里取最低价。"""
    return float(str(value).split("-")[0])


@pytest.mark.p0
@pytest.mark.boundary
@pytest.mark.parametrize("case", build_params(CASES), ids=case_ids(CASES))
def test_search(search_api, case):
    """搜索接口参数化用例：正向 / 边界 / 异常输入。"""
    mark(feature="商品模块", story="商品搜索", title=case["desc"])
    filters = {key: case[key] for key in FILTER_KEYS if key in case}
    with step(f"搜索：wd={case.get('wd')!r} page={case.get('page')} filters={filters}"):
        res = search_api.search(wd=case.get("wd"), page=case.get("page", 1), **filters)

    Assert.code(res, case.get("expected_code", 0), case["desc"])
    data = res.get("data") or {}

    if case.get("schema"):
        Assert.schema(res, case["schema"], case["desc"])
        Assert.pagination(data, case["desc"])

    if case.get("expect_total_zero"):
        Assert.money(data.get("total"), 0, "搜索命中总数", tol=0)

    if case.get("expect_empty_page"):
        Assert.is_true(data.get("data") == [], f"期望空列表，实际返回 {len(data.get('data') or [])} 条")

    if case.get("expect_min_total"):
        Assert.is_true(
            int(data.get("total") or 0) >= case["expect_min_total"],
            f"命中总数过少：期望 >= {case['expect_min_total']}，实际 {data.get('total')}",
        )

    if case.get("assert_keyword"):
        Assert.contains_keyword(data.get("data"), case["wd"], key="title")


@pytest.mark.p0
@pytest.mark.positive
def test_search_result_consistency(search_api):
    """搜索分页一致性：data 长度不超过每页上限，total / page_total 与实际数据自洽。"""
    res = search_api.search(wd=None, page=1)
    Assert.success(res, "搜索默认列表")
    data = res["data"]
    items = data.get("data") or []

    Assert.is_true(len(items) <= 20, f"单页返回条数异常：{len(items)} 条（应 <= 20）")
    Assert.is_true(int(data.get("total") or 0) >= len(items), "命中总数小于当前页条数，分页数据不一致")
    Assert.is_true(int(data.get("page_total") or 0) >= 1, "总页数应至少为 1")

    for item in items:
        Assert.has_fields(item, "id", "title", "price", "inventory", "is_shelves")
        Assert.is_true(_min_price(item["price"]) >= 0, f"商品价格异常：{item['price']}")


@pytest.mark.positive
def test_search_specific_goods_visible(search_api, goods_api):
    """搜索-详情一致性：搜索到的商品可通过商品 ID 打开详情（跨接口数据一致性）。"""
    search = search_api.search(wd="iphone", page=1)
    Assert.success(search, "搜索 iphone")
    items = (search["data"] or {}).get("data") or []
    Assert.not_empty(items, "搜索结果")

    goods_id = items[0]["id"]
    with step(f"打开搜索结果中的商品详情 id={goods_id}"):
        detail = goods_api.detail(goods_id)
    Assert.success(detail, "商品详情")
    detail_goods = detail["data"]["goods"]
    Assert.is_true(
        str(detail_goods.get("id")) == str(goods_id),
        f"搜索结果与详情数据不一致：搜索 id={goods_id}，详情 id={detail_goods.get('id')}",
    )
