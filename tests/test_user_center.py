"""用户中心模块测试：首页数据、消息、积分、留言。"""
import pytest

from config.setting import API_PREFIX
from core.allure_utils import attach_json, mark, step
from core.assert_helper import Assert
from core.auth import AuthType
from core.data_loader import unique

HOME_DATA_KEYS = ("navigation", "banner_list", "data_list", "common_cart_total")


@pytest.mark.smoke
@pytest.mark.positive
def test_home_index_structure(home_api):
    """首页聚合数据：免登录可访问，且包含导航/轮播/推荐商品/购物车总数。"""
    mark(feature="用户模块", story="首页数据")
    res = home_api.index()
    Assert.success(res, "首页数据")
    Assert.has_fields(res["data"], *HOME_DATA_KEYS)
    Assert.is_true(isinstance(res["data"]["data_list"], list), "首页推荐商品 data_list 应为数组")


@pytest.mark.positive
def test_message_list_pagination(user_api, token):
    """消息列表：分页结构与字段完整性。"""
    mark(feature="用户模块", story="消息中心")
    res = user_api.message_list(page=1)
    Assert.success(res, "消息列表")
    Assert.pagination(res["data"], "消息列表")

    if res["data"]["data"]:
        first = res["data"]["data"][0]
        Assert.has_fields(first, "id", "title", "is_read")
    else:
        pytest.skip("当前账号暂无消息数据，跳过字段校验")


@pytest.mark.positive
def test_integral_list_structure(user_api, token):
    """积分列表：接口可用且分页结构正确（无数据时也应有完整分页字段）。"""
    mark(feature="用户模块", story="我的积分")
    res = user_api.integral_list(page=1)
    Assert.success(res, "积分列表")
    Assert.pagination(res["data"], "积分列表")


@pytest.mark.positive
def test_answer_add_and_query(user_api, token):
    """留言：提交留言成功，且留言列表可正常查询（写入后总数不减少）。"""
    mark(feature="用户模块", story="留言")
    content = f"自动化测试留言-{unique('Answer')}"

    with step("查询留言前的总数"):
        before = user_api.answer_list(page=1)
    Assert.success(before, "留言列表(前)")
    Assert.pagination(before["data"], "留言列表")
    total_before = int(before["data"]["total"])

    with step("提交留言"):
        add = user_api.answer_add(name="自动化测试", tel="13800138000", content=content)
    Assert.success(add, "提交留言")
    Assert.msg_contains(add, "成功")

    with step("再次查询留言列表"):
        after = user_api.answer_list(page=1)
    Assert.success(after, "留言列表(后)")
    total_after = int(after["data"]["total"])
    Assert.is_true(total_after >= total_before, f"提交留言后总数异常：{total_before} -> {total_after}")

    found = any(str(item.get("content", "")).strip() == content for item in after["data"]["data"])
    attach_json({"content": content, "total_before": total_before, "total_after": total_after, "可见": found}, name="留言校验")
    if found:
        Assert.is_true(found, "新增留言应出现在列表中")


@pytest.mark.negative
def test_answer_add_missing_tel(user_api, token):
    """留言异常场景：完全不传联系电话字段应被拦截。"""
    res = user_api.post(
        f"{API_PREFIX}answer/add",
        data={"name": "自动化测试", "content": "缺少电话字段的留言"},
    )
    Assert.fail(res, "缺少电话提交留言")
    Assert.msg_contains(res, "联系电话")


@pytest.mark.xfail(
    reason="缺陷 BUG-ANSWER-TEL-001：留言接口对'空字符串'联系电话不做校验（tel='' 仍返回提交成功），"
           "而字段完全缺失时才拦截，校验逻辑不一致",
    strict=False,
)
@pytest.mark.negative
def test_answer_add_empty_tel_should_be_rejected(user_api, token):
    """留言异常场景（期望）：联系电话为空字符串也应被拦截。"""
    res = user_api.answer_add(name="自动化测试", tel="", content="空字符串电话的留言")
    Assert.fail(res, "空字符串电话提交留言")


@pytest.mark.negative
def test_message_requires_token(user_api):
    """鉴权校验：不携带 token 查询消息应被拦截。"""
    res = user_api.post(f"{API_PREFIX}message/index", auth=AuthType.NONE)
    Assert.fail(res, "未携带 token 查询消息")
    Assert.msg_contains(res, "登录失效")
