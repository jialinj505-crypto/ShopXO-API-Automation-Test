"""统一断言层（core/assert_helper.py）离线单元测试。

断言层是"用例结论"的最后一道闸门：它写错，报告就会说谎。
这里把它当成被测对象，固定住几条底线：

1. 业务码断言失败时必须同时给出期望值、实际值、接口 msg —— 防止 CI 失败信息无法定位；
2. msg 包含/相等断言 —— 防止只校验 code 而放过"错误原因被改掉"的缺陷；
3. JSON Schema 契约校验 —— 防止接口悄悄加/删字段、改类型后用例静默失去覆盖；
4. 金额断言 —— 防止浮点误差造成假失败，也防止容差失控造成假通过；
5. 分页结构断言 —— 防止列表接口结构变化未被发现。

纯本地：只读 data/schemas 下的结构定义与内存构造数据，零网络请求。
"""
import copy
import sys

import pytest

from core.assert_helper import Assert

pytestmark = pytest.mark.offline

# 与 data/schemas/login_success.json 一致的合法登录响应
VALID_LOGIN = {
    "code": 0,
    "msg": "登录成功",
    "data": {
        "id": 1,
        "username": "huace_tester",
        "token": "unit-test-token-0123456789",
        "user_name_view": "华测测试",
        "integral": 0,
    },
}


def _login_payload() -> dict:
    """返回一份可变副本，供结构校验用例按需破坏字段。"""
    return copy.deepcopy(VALID_LOGIN)


# ------------------------------------------------------------------ 业务码
def test_code_pass_is_silent():
    """防止风险：断言成功时仍返回内容/抛异常，干扰用例链式调用。"""
    assert Assert.code({"code": 0, "msg": "登录成功"}, 0, "登录") is None
    assert Assert.success({"code": 0, "msg": "登录成功"}, "登录") is None
    assert Assert.code_in({"code": -400, "msg": "登录失效"}, (-400, 401), "伪造 token") is None


def test_code_failure_message_carries_expected_actual_and_msg():
    """防止风险：断言失败只说"业务码不符"，看不到期望值、实际值与接口 msg，定位靠猜。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.success({"code": -4, "msg": "密码错误"}, "登录")

    message = str(excinfo.value)
    assert "期望 code=0" in message, f"缺少期望值：{message}"
    assert "实际 code=-4" in message, f"缺少实际值：{message}"
    assert "密码错误" in message, f"缺少接口 msg：{message}"
    assert "登录" in message, f"缺少业务上下文：{message}"


def test_code_in_failure_lists_allowed_codes():
    """防止风险：多值业务码断言失败时看不出允许范围，无法判断是环境差异还是真缺陷。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.code_in({"code": -1, "msg": "参数错误"}, (-400, 401), "权限校验")

    message = str(excinfo.value)
    assert "-400" in message and "401" in message and "-1" in message and "参数错误" in message


def test_fail_passes_on_business_failure():
    """防止风险：异常用例断言方向写反，接口真失败了反而判定不通过。"""
    assert Assert.fail({"code": -4, "msg": "密码错误"}, "错误密码") is None
    assert Assert.fail({"code": -1, "msg": "参数错误"}) is None

    with pytest.raises(AssertionError) as excinfo:
        Assert.fail({"code": 0, "msg": "登录成功"}, "错误密码")
    assert "code=0" in str(excinfo.value) and "登录成功" in str(excinfo.value)


def test_fail_treats_missing_code_as_not_failed():
    """现状（保守设计）：响应里没有 code 字段时 fail() 判为"不通过"。

    这样能挡住"接口返回结构异常却被当成业务失败"的情况，
    但提示语写成"实际成功：code=None"与实际语义不符，排查时会误导（见报告中的疑似缺陷）。
    """
    with pytest.raises(AssertionError) as excinfo:
        Assert.fail({"msg": "响应结构异常"})
    assert "code=None" in str(excinfo.value)


# ------------------------------------------------------------------ 提示语
@pytest.mark.parametrize("keywords", [("登录成功",), ("登录", "成功")])
def test_msg_contains_pass(keywords):
    """防止风险：提示语断言过严（要求整句相等），接口微调文案就让用例假失败。"""
    assert Assert.msg_contains({"msg": "登录成功"}, *keywords) is None


def test_msg_contains_failure_names_the_missing_keyword():
    """防止风险：失败时只说"提示语不符"，不知道是哪个关键字没匹配上。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.msg_contains({"msg": "密码错误"}, "密码错误", "账号不存在")

    message = str(excinfo.value)
    assert "账号不存在" in message, f"未指出缺失的关键字：{message}"
    assert "密码错误" in message, f"未回显接口真实 msg：{message}"


def test_msg_contains_handles_missing_msg_field():
    """防止风险：响应缺 msg 字段时抛 AttributeError/TypeError，掩盖真实的接口异常。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.msg_contains({}, "任意提示")
    assert "实际 msg=[]" in str(excinfo.value)


def test_msg_equals_pass_and_failure():
    """防止风险：提示语被改（如"密码错误"→"账号或密码错误"）未被发现。"""
    assert Assert.msg_equals({"msg": "登录成功"}, "登录成功") is None

    with pytest.raises(AssertionError) as excinfo:
        Assert.msg_equals({"msg": "账号或密码错误"}, "密码错误")
    message = str(excinfo.value)
    assert "密码错误" in message and "账号或密码错误" in message


# ------------------------------------------------------------------ 结构契约
def test_schema_accepts_conforming_payload():
    """防止风险：结构校验过严，把合法响应判成失败（契约校验本身成为噪音）。"""
    assert Assert.schema(_login_payload(), "login_success", "登录") is None


def test_schema_reports_missing_required_field():
    """防止风险：接口少返回 token（登录态拿不到）却因为只断言 code=0 而放过。"""
    payload = _login_payload()
    payload["data"].pop("token")

    with pytest.raises(AssertionError) as excinfo:
        Assert.schema(payload, "login_success", "登录")

    message = str(excinfo.value)
    assert "login_success" in message and "登录" in message
    assert "路径 ['data']" in message, f"未指出出错的字段路径：{message}"
    assert "token" in message and "required" in message, f"未指出缺失的字段：{message}"


def test_schema_reports_type_error_with_field_path():
    """防止风险：字段类型被改（integral 由数字变数组）时用例静默失去覆盖。"""
    payload = _login_payload()
    payload["data"]["integral"] = ["not", "an", "integer"]

    with pytest.raises(AssertionError) as excinfo:
        Assert.schema(payload, "login_success", "登录")

    message = str(excinfo.value)
    assert "路径 ['data', 'integral']" in message, f"未定位到具体字段：{message}"
    assert "is not of type" in message, f"未说明类型不符：{message}"


def test_schema_reports_all_top_level_missing_fields():
    """防止风险：空/异常响应体（如网关返回 {}）被当成正常响应继续断言。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.schema({}, "login_success")

    message = str(excinfo.value)
    assert "路径 []" in message
    for field in ("code", "msg", "data"):
        assert field in message, f"未指出缺失的顶层字段 {field}：{message}"


def test_schema_skips_silently_when_jsonschema_missing(monkeypatch):
    """现状（设计取舍）：未安装 jsonschema 时结构校验静默跳过，用例照样"绿"。

    框架注释说明这是为了"报告组件缺失也能跑回归"，但代价是契约校验无声失效，
    正是本项目最警惕的"假绿"场景，故此处把该行为固定下来，便于评审时取舍。
    """
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    assert Assert.schema({"完全不符合结构": True}, "login_success") is None


def test_schema_unknown_name_reports_file_not_found():
    """防止风险：schema 名写错时静默不校验；这里确认它会明确报出找不到的数据文件。"""
    with pytest.raises(FileNotFoundError) as excinfo:
        Assert.schema({}, "schema_not_exists_for_unit_test")
    assert "schema_not_exists_for_unit_test" in str(excinfo.value)


def test_has_fields_rejects_non_dict():
    """防止风险：把列表/None 传给字段存在性断言时静默通过。"""
    assert Assert.has_fields({"code": 0}, "code") is None

    with pytest.raises(AssertionError) as excinfo:
        Assert.has_fields([], "code")
    assert "期望 dict" in str(excinfo.value)


# ------------------------------------------------------------------ 金额
@pytest.mark.parametrize(
    "actual, expected, tol",
    [
        (12.34, 12.34, 0.01),
        (12.34, "12.34", 0.01),        # 接口常以字符串返回金额
        (0.1 + 0.2, 0.3, 0.01),        # 经典浮点误差：0.30000000000000004 vs 0.3
        (10.00, 10.01, 0.01),          # 相差正好等于容差：判定为相等（容差是闭区间）
        (0.1 + 0.2, 0.31, 0.01),       # 差额 0.00999…≤ 0.01：容差把真实差额也一起兜住了
        (-5.00, -5.00, 0.01),          # 负数金额（优惠/退款）
        (10.0, 10.5, 0.5),             # 显式放宽容差
    ],
)
def test_money_passes_within_tolerance(actual, expected, tol):
    """防止风险：浮点误差导致金额断言假失败（用例不稳定，被误判成产品缺陷）。"""
    assert Assert.money(actual, expected, "订单金额", tol) is None


@pytest.mark.parametrize(
    "actual, expected",
    [
        (10.00, 10.02),                    # 超出默认容差 0.01
        (-10.00, 10.00),                   # 符号错误
        (0.1 + 0.2, 0.32),                 # 差额约 0.02，超出默认容差
        (float("nan"), float("nan")),      # nan 与自身都不相等：必须失败而不是放过
    ],
)
def test_money_fails_beyond_tolerance(actual, expected):
    """防止风险：容差过大/比较写反导致金额算错也判通过（假绿）。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.money(actual, expected, "订单金额")

    message = str(excinfo.value)
    assert "订单金额" in message and "容差" in message


@pytest.mark.parametrize("bad", [None, "abc", "", {"amount": 1}, [1.0], True])
def test_money_rejects_non_numeric_input(bad):
    """防止风险：金额字段变成空/文本/结构体时抛裸 ValueError 或静默通过，报错看不懂。

    说明：True 会被 float() 转成 1.0，因此它不会进"无法比较"分支——用期望 1.0 校验这一点。
    """
    if bad is True:
        assert Assert.money(bad, 1.0, "订单金额") is None
        return

    with pytest.raises(AssertionError) as excinfo:
        Assert.money(bad, 1.0, "订单金额")

    message = str(excinfo.value)
    assert "无法比较" in message and "订单金额" in message


def test_money_rejects_non_numeric_expected():
    """防止风险：期望值来自测试数据文件，写错（如"待确认"）时应明确报错而不是当成 0。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.money(1.0, "待确认", "订单金额")
    assert "无法比较" in str(excinfo.value) and "待确认" in str(excinfo.value)


# ------------------------------------------------------------------ 分页结构
def test_pagination_accepts_valid_structure():
    """防止风险：分页校验过严，把合法结构判成失败。数字字段允许字符串（接口返回"10"）。"""
    assert Assert.pagination({"total": 10, "page_total": 2, "data": []}, "商品搜索") is None
    assert Assert.pagination({"total": "10", "page_total": "2", "data": [{"id": 1}]}) is None


def test_pagination_rejects_missing_field():
    """防止风险：分页接口少了 total/page_total，用例只看 data 就放过了结构变化。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.pagination({"total": 10, "data": []}, "商品搜索")

    message = str(excinfo.value)
    assert "缺少字段" in message and "page_total" in message


def test_pagination_rejects_non_list_data():
    """防止风险：data 由数组变成对象（结构变更）时未被发现，后续取列表的操作全错。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.pagination({"total": 10, "page_total": 2, "data": {"list": []}}, "商品搜索")

    message = str(excinfo.value)
    assert "商品搜索" in message and "应为数组" in message


def test_pagination_rejects_non_numeric_total():
    """防止风险：total 变成字符串文案（如"共 10 条"）时，分页数量断言会静默失效。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.pagination({"total": "共 10 条", "page_total": 2, "data": []}, "商品搜索")

    message = str(excinfo.value)
    assert "商品搜索" in message and "total" in message and "应为数字" in message


def test_pagination_accepts_negative_total():
    """现状（宽松行为）：total 为负数也能通过校验（lstrip('-') 后仍是数字）。

    固定该行为是为了让人看到"负数没人挡"，若业务上不可能出现负 total，
    应在断言层补一条非负校验（见报告中的疑似缺陷）。
    """
    assert Assert.pagination({"total": -1, "page_total": 1, "data": []}) is None


def test_pagination_missing_field_message_keeps_context():
    """缺字段时报错必须带上 context：多接口批量断言时才能定位是哪次调用出的问题。"""
    with pytest.raises(AssertionError) as excinfo:
        Assert.pagination({"total": 10, "data": []}, "商品搜索")
    assert "商品搜索" in str(excinfo.value)
