"""收货地址模块测试：地址增删改查、地区数据、参数校验（数据驱动 data/address_data.json）。"""
import pytest

from core.allure_utils import mark, step
from core.assert_helper import Assert
from core.data_loader import build_params, case_ids, load_cases, unique

CASES = load_cases("address_data.json")


def _record(res: dict) -> dict:
    """兼容单层/双层 data 结构，取出地址记录。"""
    data = res.get("data") or {}
    if isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


@pytest.mark.negative
@pytest.mark.parametrize("case", build_params(CASES), ids=case_ids(CASES))
def test_address_invalid(address_api, token, case):
    """地址接口参数化异常/边界用例（含已知缺陷用例，由 xfail 标记跟踪）。"""
    mark(feature="用户模块", story="收货地址", title=case["desc"])
    group = case.get("group")
    try:
        with step(f"地址接口：{case['desc']}"):
            if group == "save":
                res = address_api.save(
                    name=case.get("name"),
                    tel=case.get("tel"),
                    address=case.get("address"),
                    province=9,
                    city=152,
                    county=1896,
                )
            elif group == "detail":
                res = address_api.detail(case["address_id"])
            else:
                res = address_api.delete(case["address_id"])

        expected = case["expected_code"]
        if expected == "not_0":
            Assert.fail(res, case["desc"])
        else:
            Assert.code(res, expected, case["desc"])
        if case.get("expected_msg"):
            Assert.msg_contains(res, case["expected_msg"])
    finally:
        # 参数校验类用例可能"意外"创建成功（缺陷场景），这里统一回收，保证环境干净
        if case.get("name"):
            removed = address_api.cleanup_by_name(case["name"])
            if removed:
                assert False, f"缺陷复现：非法参数({case.get('tel')!r})仍创建了 {removed} 条地址，已清理。{case.get('desc')}"


@pytest.mark.p0
@pytest.mark.positive
def test_address_crud_lifecycle(address_api, token, test_name):
    """地址全生命周期：新增 -> 列表可见 -> 详情一致 -> 修改 -> 删除 -> 列表不可见。"""
    mark(feature="用户模块", story="收货地址增删改查")

    with step("1. 新增地址"):
        res = address_api.save(
            name=test_name, tel="13800138000", address="自动化测试地址-初始",
            province=9, city=152, county=1896,
        )
    Assert.success(res, "新增地址")

    with step("2. 列表中能看到新增的地址"):
        record = address_api.find_by_name(test_name)
        Assert.not_none(record, f"列表中未找到地址[{test_name}]")
        address_id = record["id"]
        Assert.is_true("13800138000" == str(record["tel"]), f"电话不一致：{record['tel']}")

    try:
        with step("3. 查询地址详情并与列表数据一致"):
            detail = address_api.detail(address_id)
            Assert.success(detail, "地址详情")
            info = _record(detail)
            Assert.has_fields(info, "id", "name", "tel", "address")
            Assert.is_true(str(info["id"]) == str(address_id), "详情返回的地址id与查询id不一致")

        with step("4. 修改地址内容"):
            updated_text = unique("AutoTestAddr")
            upd = address_api.update(
                address_id, name=test_name, tel="13800138001", address=updated_text,
                province=9, city=152, county=1896,
            )
            Assert.success(upd, "修改地址")
            after = _record(address_api.detail(address_id))
            Assert.is_true(updated_text == after.get("address"), f"地址未更新：{after.get('address')}")
            Assert.is_true("13800138001" == str(after.get("tel")), f"电话未更新：{after.get('tel')}")
    finally:
        with step("5. 删除地址并确认不可见"):
            Assert.success(address_api.delete(address_id), "删除地址")
        Assert.is_true(address_api.find_by_name(test_name) is None, "删除后地址仍存在于列表")


@pytest.mark.positive
def test_address_list_schema(address_api, temp_address):
    """地址列表结构校验（JSON Schema）。"""
    res = address_api.list()
    Assert.success(res, "地址列表")
    Assert.schema(res, "address_list", "地址列表")
    Assert.is_true(len(res["data"]["data"]) >= 1, "地址列表应至少包含临时地址")


@pytest.mark.positive
def test_address_list_requires_token(address_api):
    """鉴权校验：不携带 token 查询地址列表应被拦截。"""
    from core.auth import AuthType

    res = address_api.post("index.php?s=/api/useraddress/index", auth=AuthType.NONE)
    Assert.fail(res, "未携带 token 查询地址")
    Assert.msg_contains(res, "登录失效")


@pytest.mark.smoke
@pytest.mark.positive
def test_region_tree_data(address_api):
    """地区数据：省级 -> 市级 层级结构正确（下单时选择收货地址依赖该接口）。"""
    with step("查询省级地区"):
        provinces = address_api.region_list(0)
    Assert.success(provinces, "省级地区")
    province_list = provinces["data"]
    Assert.is_true(isinstance(province_list, list) and len(province_list) >= 30, "省级地区数据异常")
    first = province_list[0]
    Assert.has_fields(first, "id", "name", "level")

    with step(f"按省级id查询下级地区 pid={first['id']}"):
        cities = address_api.region_list(first["id"])
    Assert.success(cities, "市级地区")
    city_list = cities["data"]
    Assert.is_true(isinstance(city_list, list) and len(city_list) >= 1, "市级地区数据异常")
    Assert.is_true(str(city_list[0].get("level")) == "2", f"下级地区 level 应为 2，实际 {city_list[0].get('level')}")
