"""数据驱动加载器（core/data_loader.py）的离线单元测试。

这条用例在防什么风险
--------------------
1. 占位符失真：``${USER}`` / ``${PWD}`` / ``${GOODS_ID}`` / ``${DATA_PREFIX}`` 展开错误时，
   用例会拿着错误账号去登录，现象却是"接口报错"，排查成本极高；而未识别的占位符若被
   静默替换成空字符串，会把"密码错误"伪装成"参数为空"这种无关结论——所以这里同时
   固定"已知占位符必须替换""未知占位符必须原样保留"。
2. 用例少跑却全绿：``load_cases()`` 返回的条数少于 data/*.json 里真实定义的条数（分组过滤
   写错、结构解析回退），意味着用例被悄悄丢掉而报告依然通过，是"假绿"的典型来源。
3. 定位困难：数据文件名写错时抛出 KeyError/AttributeError 这类空异常，看不出是哪个文件；
   这里要求异常信息里必须带得出文件路径。
4. 测试数据退化：``unique()`` 一旦因为截断失去唯一性/可识别前缀，多人共用同一沙箱时会
   互相污染数据（比如把别人的地址删掉），所以要把前缀、长度、唯一性这些确定性特征固定住。

本文件纯本地执行：不读网络、不依赖被测环境（``pytest.mark.offline``）。
"""
import importlib
import json
import re
from datetime import datetime

import pytest

from config import setting
from core import data_loader

# 本文件全部是"不依赖真实环境的框架自测"，离线模式下也会执行（见 tests/conftest.py 的钩子）
pytestmark = pytest.mark.offline

# 四个占位符的"字面量"名字，用于断言展开后不残留
_KNOWN_PLACEHOLDERS = ("${USER}", "${PWD}", "${GOODS_ID}", "${DATA_PREFIX}")


def _raw(name: str):
    """独立于被测代码读取 data/ 下的原始用例文件，作为数量/结构的"事实来源"。"""
    return json.loads((setting.DATA_DIR / name).read_text(encoding="utf-8"))


def _case_files() -> list:
    """列出 data/ 下真正承载用例的文件（list 结构，或含 cases 字段的 dict）。"""
    files = []
    for path in sorted(setting.DATA_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list) or (isinstance(raw, dict) and "cases" in raw):
            files.append(path.name)
    return files


CASE_FILES = _case_files()
CASE_FILES_WITH_CASES_FIELD = [name for name in CASE_FILES if "cases" in _raw(name)]


@pytest.fixture
def reload_env():
    """在受控环境变量下重新导入 config.setting / core.data_loader，用完彻底还原。

    为什么需要它：本项目大量使用 ``from config.setting import X``，值是在**导入时**拷贝的，
    所以"环境变量覆盖"只有重新导入后才会体现在 data_loader 里。这里必须保证重新导入后
    不会把被覆盖的配置残留给后续用例（_CACHE、环境变量、setting 属性都不能互相污染）。
    """
    mp = pytest.MonkeyPatch()

    def _apply(**env):
        for key, value in env.items():
            mp.setenv(key, value)
        importlib.reload(setting)
        importlib.reload(data_loader)
        return data_loader

    yield _apply
    mp.undo()
    importlib.reload(setting)
    importlib.reload(data_loader)


def _write_case_file(tmp_path, payload: dict) -> None:
    """在临时目录写一个用例数据文件（配合 monkeypatch 掉的 DATA_DIR 使用）。"""
    (tmp_path / "unit_placeholders.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ------------------------------------------------------------------ 占位符展开
def test_placeholders_use_current_setting_values():
    """真实数据文件里的 ${USER}/${PWD} 必须展开成 config.setting 当前的账号密码。"""
    case = data_loader.load_cases("login_data.json")[0]

    assert case["accounts"] == setting.USER_ACCOUNTS["default"]["accounts"]
    assert case["pwd"] == setting.USER_ACCOUNTS["default"]["pwd"]
    assert "${USER}" not in case["accounts"] and "${PWD}" not in case["pwd"]


def test_placeholders_follow_env_override(reload_env):
    """环境变量覆盖配置后（重新导入），四个占位符都必须跟着变成新值，而不是沿用默认值。"""
    loader = reload_env(
        SHOPXO_USER="unit_env_user",
        SHOPXO_PWD="unit_env_pwd",
        SHOPXO_GOODS_ID="888",
        SHOPXO_DATA_PREFIX="EnvPrefix",
    )

    cases = loader.load_cases("login_data.json")

    assert cases[0]["accounts"] == "unit_env_user"
    assert cases[0]["pwd"] == "unit_env_pwd"
    # 数据文件里原文是 " ${PWD} "：只替换占位符，不得顺手裁剪空格（否则会掩盖"密码未 trim"这条边界用例）
    assert cases[1]["pwd"] == " unit_env_pwd "
    assert loader._expand_placeholders("${GOODS_ID}") == "888"
    assert loader._expand_placeholders("${DATA_PREFIX}") == "EnvPrefix"
    assert loader.DEFAULT_GOODS_ID == 888, "SHOPXO_GOODS_ID 应被 env() 转成 int"


def test_all_four_placeholders_expanded_in_real_structure(tmp_path, monkeypatch):
    """四种占位符在 dict/list 嵌套结构里都要被替换；非字符串类型原样保留。"""
    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_loader, "DEFAULT_GOODS_ID", 4242)
    monkeypatch.setattr(data_loader, "TEST_DATA_PREFIX", "UnitPrefix")
    monkeypatch.setattr(
        data_loader, "USER_ACCOUNTS", {"default": {"accounts": "unit_user", "pwd": "unit_pwd"}}
    )
    _write_case_file(
        tmp_path,
        {
            "module": "单元自测",
            "cases": [
                {
                    "desc": "占位符全展开",
                    "joined": "${USER}/${PWD}/${GOODS_ID}/${DATA_PREFIX}",
                    "nested": {"goods": "${GOODS_ID}", "list": ["${DATA_PREFIX}-x"]},
                    "count": 12,
                    "none_value": None,
                }
            ],
        },
    )

    case = data_loader.load_cases("unit_placeholders.json")[0]

    assert case["joined"] == "unit_user/unit_pwd/4242/UnitPrefix"
    assert case["nested"]["goods"] == "4242"
    assert case["nested"]["list"] == ["UnitPrefix-x"]
    assert case["count"] == 12, "非字符串（int）必须原样返回"
    assert case["none_value"] is None, "None 不能被替换成字符串"


def test_unknown_placeholder_is_preserved_not_blanked(tmp_path, monkeypatch):
    """未识别的占位符必须原样保留：静默变空串会把"配置写错"伪装成"参数为空"。"""
    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
    _write_case_file(tmp_path, {"cases": [{"desc": "未知占位符", "value": "${NOT_EXIST}"}]})

    case = data_loader.load_cases("unit_placeholders.json")[0]

    assert case["value"] == "${NOT_EXIST}"
    assert case["value"] != "", "未知占位符绝不能被替换成空字符串"


def test_patching_setting_alone_does_not_change_expansion(monkeypatch):
    """说明性用例：from ... import 是"导入时按值拷贝"。

    运行期只改 config.setting 的属性并不会影响 data_loader 的占位符展开（反之亦然，
    env_check.OFFLINE 也是同一个坑）。这条用例把该事实固定下来，避免后来人误以为
    monkeypatch.setattr(setting, "DEFAULT_GOODS_ID", x) 就能改动加载结果。
    """
    monkeypatch.setattr(setting, "DEFAULT_GOODS_ID", 424242)
    monkeypatch.setattr(setting, "USER_ACCOUNTS", {"default": {"accounts": "nobody", "pwd": "nopwd"}})

    assert data_loader._expand_placeholders("${GOODS_ID}") == str(data_loader.DEFAULT_GOODS_ID)
    assert data_loader._expand_placeholders("${GOODS_ID}") != "424242"
    assert data_loader._expand_placeholders("${USER}") == data_loader.USER_ACCOUNTS["default"]["accounts"]


def test_documentation_fields_keep_placeholders_unexpanded():
    """说明性字段（note / known_defect 等）不做占位符替换：凭据不能被复制进用例数据。

    用例数据会随失败信息与报告附件外发，而 `note` 只是给人看的备注；
    若把 ${USER}/${PWD} 也替换进去，等于在数据里再存一份账号密码（凭据泄露面扩大）。
    """
    case = data_loader._expand_placeholders({"desc": "${USER}", "note": "沙箱密码已改为 ${PWD}"})

    assert case["desc"] == data_loader.USER_ACCOUNTS["default"]["accounts"], "数据字段仍要正常替换"
    assert case["note"] == "沙箱密码已改为 ${PWD}", "说明字段必须保持占位符原样"


# ------------------------------------------------------------------ 加载数量 / 结构
def test_case_data_files_are_discovered():
    """守卫：data/ 下必须能识别出承载用例的数据文件（否则下面的数量校验会变成空跑）。"""
    assert "login_data.json" in CASE_FILES, "登录模块数据文件缺失，数据驱动用例会整体消失"
    assert len(CASE_FILES) >= 8, f"识别到的用例数据文件过少：{CASE_FILES}"


@pytest.mark.parametrize("name", CASE_FILES_WITH_CASES_FIELD)
def test_load_cases_count_matches_raw_definition(name):
    """load_cases() 的条数必须与数据文件里 cases 的真实条数一致：少加载=用例少跑却全绿。"""
    expected = _raw(name)["cases"]

    cases = data_loader.load_cases(name)

    assert len(cases) == len(expected), f"{name} 实际加载 {len(cases)} 条，文件定义 {len(expected)} 条"
    assert all(isinstance(case, dict) for case in cases)


@pytest.mark.parametrize("name", CASE_FILES_WITH_CASES_FIELD)
def test_every_loaded_case_keeps_its_description(name):
    """每条用例都要有 desc：case_ids() 依赖它生成可读 ID，缺了报告里就是无法定位的 "case"。"""
    cases = data_loader.load_cases(name)

    assert all(case.get("desc") for case in cases), f"{name} 存在没有 desc 的用例"


def _iter_strings(value):
    """递归取出结构里的所有字符串，用于检查占位符残留。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


@pytest.mark.parametrize("name", CASE_FILES_WITH_CASES_FIELD)
def test_known_placeholders_are_fully_expanded(name):
    """加载结果里不得残留 ${USER}/${PWD}/${GOODS_ID}/${DATA_PREFIX}：残留会让接口拿到字面量。"""
    for case in data_loader.load_cases(name):
        for text in _iter_strings(case):
            for placeholder in _KNOWN_PLACEHOLDERS:
                assert placeholder not in text, (
                    f"{name} 中 {case.get('desc')} 的 {text!r} 仍残留占位符 {placeholder}"
                )


@pytest.mark.parametrize("name", CASE_FILES_WITH_CASES_FIELD)
def test_case_ids_are_unique_and_numbered(name):
    """用例 ID 必须"编号+描述"且互不重复：重复 ID 会让报告里两条用例看起来是同一条。"""
    cases = data_loader.load_cases(name)

    ids = data_loader.case_ids(cases)

    assert len(ids) == len(cases)
    assert len(set(ids)) == len(ids), f"{name} 存在重复用例 ID：{ids}"
    assert ids[0].startswith("01-")
    assert ids[0].endswith(cases[0]["desc"])


def test_build_params_marks_known_defect_cases_as_xfail():
    """带 known_defect 的用例必须被标成 xfail（strict=False），否则"已知缺陷"会变成红色失败，
    或者反过来被误当成正常用例通过——两种情况都会让缺陷跟踪失真。"""
    cases = data_loader.load_cases("cart_data.json")
    params = data_loader.build_params(cases)

    expected_ids = [f"{i:02d}-{case.get('desc', 'case')}" for i, case in enumerate(cases, start=1)]
    assert [param.id for param in params] == expected_ids

    marked = [p for p in params if any(m.name == "xfail" for m in p.marks)]
    defect_cases = [c for c in cases if c.get("known_defect")]

    assert defect_cases, "购物车数据文件应保留已知缺陷用例，用于回归缺陷跟踪"
    assert len(marked) == len(defect_cases)
    assert all(
        m.kwargs.get("strict") is False
        for p in marked
        for m in p.marks
        if m.name == "xfail"
    ), "known_defect 的 xfail 必须是 strict=False，缺陷修复后自动变 XPASS 而不是报错"


def test_group_filter_returns_only_requested_group():
    """按 group 过滤必须只返回该分组（外加未标注分组的通用用例），不能夹带其它分组。"""
    raw = _raw("admin_data.json")
    expected = [case for case in raw["cases"] if case.get("group") == "login"]

    cases = data_loader.load_cases("admin_data.json", group="login")

    assert expected, "admin_data.json 应当存在 login 分组"
    assert len(cases) == len(expected)
    assert all(case.get("group") == "login" for case in cases)


def test_unknown_group_raises_with_available_groups():
    """分组名拼错必须立刻报错并列出可用分组，而不是静默回退成全量用例。

    这条用例原来固定的是缺陷行为：`cases = filtered or cases` 让拼错的 group（logni）
    返回全部 5 条后台用例——分组名写错时用例"跑多了"却没有任何提示，
    很容易把别组的失败算到本组头上。修复后改为显式报错。
    """
    with pytest.raises(ValueError) as excinfo:
        data_loader.load_cases("admin_data.json", group="logni")

    message = str(excinfo.value)
    assert "logni" in message, "报错要带上写错的分组名，便于一眼定位拼写问题"
    assert "login" in message, "报错应列出可用分组"


# ------------------------------------------------------------------ 异常可定位
@pytest.mark.parametrize("loader_name", ["load_cases", "load_json"])
def test_missing_file_error_contains_path(loader_name):
    """文件不存在时必须抛带路径的 FileNotFoundError：空的 KeyError/AttributeError 无法定位。"""
    loader = getattr(data_loader, loader_name)

    with pytest.raises(FileNotFoundError) as excinfo:
        loader("not_exist_data_file_zzz.json")

    message = str(excinfo.value)
    assert "not_exist_data_file_zzz.json" in message
    assert str(setting.DATA_DIR) in message, f"异常信息应包含数据目录，实际：{message}"
    assert "不存在" in message


def test_load_schema_missing_file_error_contains_path():
    """schema 文件不存在时同样要能定位到 schemas/ 目录下的具体文件名。"""
    with pytest.raises(FileNotFoundError) as excinfo:
        data_loader.load_schema("not_exist_schema_zzz")

    message = str(excinfo.value)
    assert "not_exist_schema_zzz.json" in message
    assert "schemas" in message


def test_load_schema_returns_contract_dict():
    """真实存在的响应契约要能被解析成 dict（用例层的结构校验依赖它）。"""
    schema = data_loader.load_schema("login_success")

    assert isinstance(schema, dict) and schema


def test_unsupported_structure_error_contains_file_name(tmp_path, monkeypatch):
    """结构不支持时要抛带文件名的 ValueError，而不是在后续 .get() 上炸出 AttributeError。"""
    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
    (tmp_path / "bad_structure.json").write_text(json.dumps({"goods": [1, 2]}), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        data_loader.load_cases("bad_structure.json")

    message = str(excinfo.value)
    assert "bad_structure.json" in message
    assert "结构不支持" in message


# ------------------------------------------------------------------ 辅助函数 unique()/stamp()
def test_unique_keeps_prefix_length_and_uniqueness():
    """unique() 是"测试数据互不污染"的唯一屏障：前缀可识别 + 长度受限 + 连续调用不重复。"""
    values = [data_loader.unique("UnitTest") for _ in range(50)]

    assert all(value.startswith("UnitTest") for value in values)
    assert all(len(value) <= 26 for value in values)
    assert all(value.isalnum() for value in values), "时间戳+随机后缀应为纯小写字母与数字"
    assert len(set(values)) == 50, "同一毫秒内连续生成的测试数据也必须互不相同"


def test_unique_defaults_to_configured_prefix_and_max_len():
    """默认前缀必须取自配置的 TEST_DATA_PREFIX（便于用前缀批量识别/清理测试数据）。"""
    value = data_loader.unique()

    assert value.startswith(data_loader.TEST_DATA_PREFIX)
    assert len(value) <= 26
    assert len(data_loader.unique("UnitTest", max_len=18)) == 18, "max_len 应能收紧长度"


def test_unique_keeps_uniqueness_when_truncated():
    """截断不能把唯一性一起砍掉：max_len 接近前缀长度时，也必须保住时间戳/随机后缀。

    这条用例原来固定的是缺陷行为：`value[:max_len]` 让 max_len<=前缀长度时返回值退化成
    常量前缀（两次调用完全相同），多人并发跑同一沙箱就会互相覆盖/删除对方的数据。
    修复后前缀可能被裁短，但"长度受限 + 连续调用互不相同"这两条底线必须同时成立。
    """
    prefix = "UnitPrefix"
    first = data_loader.unique(prefix, max_len=len(prefix))
    second = data_loader.unique(prefix, max_len=len(prefix))

    assert first != second, "截断后仍必须唯一"
    assert len(first) == len(prefix) == len(second), "长度仍要受 max_len 约束"
    assert data_loader.unique("UnitPrefix", max_len=10) != data_loader.unique("UnitPrefix", max_len=10)


def test_stamp_is_millisecond_precision_numeric():
    """stamp() 必须是无分隔符的月日时分秒+毫秒数字（unique() 的唯一性来源之一）。"""
    before = datetime.now()
    value = data_loader.stamp()
    after = datetime.now()

    assert re.fullmatch(r"\d{13}", value), f"期望 13 位数字（月日时分秒+毫秒），实际 {value!r}"
    assert value[:10] in (before.strftime("%m%d%H%M%S"), after.strftime("%m%d%H%M%S"))
    assert 0 <= int(value[10:]) <= 999
