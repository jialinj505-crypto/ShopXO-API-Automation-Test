"""商品模块测试：详情、规格、收藏（数据驱动 data/goods_data.json）。"""
import pytest

from config.setting import API_PREFIX, DEFAULT_GOODS_ID
from core.allure_utils import mark, step
from core.assert_helper import Assert
from core.auth import AuthType
from core.data_loader import build_params, case_ids, load_cases

CASES = load_cases("goods_data.json")


@pytest.mark.p0
@pytest.mark.parametrize("case", build_params(CASES), ids=case_ids(CASES))
def test_goods(goods_api, case):
    """商品详情 / 规格详情 / 规格类型 参数化用例。"""
    mark(feature="商品模块", story="商品详情与规格", title=case["desc"])
    group = case.get("group", "detail")
    goods_id = case.get("goods_id")

    with step(f"{group}：goods_id={goods_id!r}"):
        if group == "detail":
            res = goods_api.detail(goods_id)
        elif group == "specdetail":
            res = goods_api.spec_detail(goods_id)
        else:
            res = goods_api.spec_type(goods_id)

    expected = case["expected_code"]
    if expected == "not_0":
        Assert.fail(res, case["desc"])
    else:
        Assert.code(res, expected, case["desc"])
        if case.get("expected_msg"):
            Assert.msg_equals(res, case["expected_msg"])

    if case.get("schema"):
        Assert.schema(res, case["schema"], case["desc"])

    for field in case.get("expect_fields", []):
        Assert.has_fields((res.get("data") or {}).get("goods") or {}, field)


@pytest.mark.positive
def test_goods_detail_without_token(goods_api):
    """商品详情为免登录接口：不携带 token 也应能正常返回。"""
    res = goods_api.post(
        f"{API_PREFIX}goods/detail",
        data={"goods_id": DEFAULT_GOODS_ID},
        auth=AuthType.NONE,
    )
    Assert.success(res, "免登录查询商品详情")
    Assert.has_fields(res["data"]["goods"], "id", "title", "price")


@pytest.mark.p0
@pytest.mark.positive
def test_goods_favor_toggle(goods_api, token):
    """收藏接口：同一接口切换收藏状态，且收藏态与商品详情返回一致。"""
    mark(feature="商品模块", story="商品收藏")

    with step("第一次调用收藏接口（切换状态）"):
        first = goods_api.favor(DEFAULT_GOODS_ID)
    Assert.success(first, "收藏/取消收藏")
    Assert.in_set(first.get("msg"), ("收藏成功", "取消成功"), "收藏接口提示")
    # 校验收藏态必须带 token 查询详情，否则拿不到 is_favor 字段
    state_one = str(
        ((goods_api.detail(DEFAULT_GOODS_ID, with_user=True).get("data") or {}).get("goods") or {}).get("is_favor")
    )

    with step("第二次调用收藏接口（状态应切换回来）"):
        second = goods_api.favor(DEFAULT_GOODS_ID)
    Assert.success(second, "收藏/取消收藏")
    state_two = str(
        ((goods_api.detail(DEFAULT_GOODS_ID, with_user=True).get("data") or {}).get("goods") or {}).get("is_favor")
    )

    Assert.is_true(
        state_one != state_two,
        f"收藏状态未被切换：两次调用后 is_favor 均为 {state_one}",
    )


def _parse_spec(goods_api, goods_id):
    """解析多规格商品的规格结构，返回 (商品信息, 完整规格组合)。

    ShopXO 的规格结构为：{"choose": [{"name": "颜色", "value": [...]}, {"name": "尺码", "value": [...]}]}。
    查询规格价格/库存时必须给出**每一个规格维度**的取值：只传第一个维度会返回
    code=-100「没有相关规格」（实测商品 id=12 这类多维规格商品即如此），
    因此这里对每个维度取第一个可用值，拼成 [{"type": 维度名, "value": 取值}] 的完整组合。
    """
    detail = goods_api.detail(goods_id)
    Assert.success(detail, "商品详情")
    goods = detail["data"]["goods"]
    Assert.is_true(str(goods.get("is_exist_many_spec")) == "1", "该商品不是多规格商品")

    specs = goods.get("specifications") or {}
    if isinstance(specs, dict):
        spec_defs = specs.get("choose") or next((v for v in specs.values() if isinstance(v, list)), [])
    else:
        spec_defs = specs
    if not spec_defs:
        pytest.skip("商品详情未返回规格明细(specifications)，无法构造规格组合")

    combination = []
    for dimension in spec_defs:
        type_name = dimension.get("name") or dimension.get("title") or dimension.get("type")
        values = dimension.get("value") or dimension.get("values") or []
        if not (type_name and values):
            pytest.skip("规格结构无法解析，跳过（不同版本 ShopXO 规格字段不一致）")
        value_item = values[0]
        value_name = (value_item.get("name") or value_item.get("value")) if isinstance(value_item, dict) else value_item
        combination.append({"type": type_name, "value": value_name})
    return goods, combination


@pytest.mark.positive
def test_multi_spec_goods_spec_detail(goods_api, spec_goods):
    """多规格商品：按规格组合查询规格详情，返回的价格必须落在商品价格区间内。"""
    goods_id = spec_goods["id"]
    mark(feature="商品模块", story="多规格商品规格选择")
    goods, spec = _parse_spec(goods_api, goods_id)

    with step(f"按规格查询规格详情 spec={spec}"):
        res = goods_api.spec_detail(goods_id, spec=spec)
    Assert.success(res, "规格详情")
    spec_data = res["data"]
    Assert.has_fields(spec_data, "price", "inventory")
    Assert.is_true(str(spec_data["inventory"]).lstrip("-").isdigit(), "库存应为数字")

    min_price = float(str(goods.get("min_price") or goods["price"]).split("-")[0])
    max_price = float(str(goods.get("max_price") or goods["price"]).split("-")[-1])
    Assert.is_true(
        min_price - 0.01 <= float(spec_data["price"]) <= max_price + 0.01,
        f"规格价格 {spec_data['price']} 超出商品价格区间 [{min_price}, {max_price}]",
    )


@pytest.mark.negative
def test_spec_detail_invalid_value_rejected(goods_api, spec_goods):
    """异常场景：选择真实规格类型 + 不存在的规格值，应被拦截。"""
    _, spec = _parse_spec(goods_api, spec_goods["id"])
    res = goods_api.spec_detail(spec_goods["id"], spec=[{"type": spec[0]["type"], "value": "不存在的规格值"}])
    Assert.fail(res, "不存在的规格值")
    Assert.msg_contains(res, "规格")


@pytest.mark.xfail(
    reason="缺陷 BUG-GOODS-SPEC-001：spec 传入畸形嵌套结构时服务端直接返回 HTTP 500（非 JSON），"
           "说明规格参数缺少类型校验与异常处理，应返回业务错误码而不是 5xx",
    strict=False,
)
@pytest.mark.negative
def test_spec_detail_malformed_spec_should_not_500(goods_api, spec_goods):
    """健壮性（期望）：畸形规格参数应返回业务错误码，而不是服务端 500。"""
    res = goods_api.spec_detail(spec_goods["id"], spec=[{"type": "choose", "value": [{"id": "1"}]}])
    Assert.success(res, "畸形规格参数")
