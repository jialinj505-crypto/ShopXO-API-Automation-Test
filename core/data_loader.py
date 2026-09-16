"""数据驱动（DDT）支持：统一加载 tests 使用的业务测试数据与响应结构定义。

数据文件放在 data/ 目录，统一结构：

    {
      "module": "登录模块",
      "cases": [
        {"desc": "正向：正确账号密码", "group": "login", "accounts": "...", "pwd": "...",
         "expected_code": 0, "expected_msg": "登录成功"}
      ]
    }

用例侧只需 `@pytest.mark.parametrize("case", build_params(load_cases("login_data.json")))`，
新增/修改用例数据不用改代码，实现真正的数据与代码分离。
"""
import json
import random
import string
from datetime import datetime
from pathlib import Path

from config.setting import DATA_DIR, DEFAULT_GOODS_ID, SCHEMA_DIR, TEST_DATA_PREFIX, USER_ACCOUNTS


# 数据集占位符：账号密码等环境相关信息只在 config / 环境变量中维护一处，
# 数据文件里写 ${USER} / ${PWD} 即可，避免沙箱改密码后要回来改测试数据。
_PLACEHOLDERS = {
    "${USER}": lambda: USER_ACCOUNTS["default"]["accounts"],
    "${PWD}": lambda: USER_ACCOUNTS["default"]["pwd"],
    "${GOODS_ID}": lambda: DEFAULT_GOODS_ID,
    "${DATA_PREFIX}": lambda: TEST_DATA_PREFIX,
}


# 说明性字段不参与占位符替换：它们只用于文档展示（如"沙箱密码已改为 ${PWD}"），
# 一旦替换，账号密码等凭据就会被复制进用例数据——用例数据随失败信息/报告附件外发即等于泄露。
_NO_EXPAND_FIELDS = {"note", "comment", "remark", "known_defect"}


def _expand_placeholders(value, _field: str = ""):
    """递归替换数据文件中的占位符（仅处理字符串，其他类型原样返回；说明性字段原样保留）。"""
    if _field in _NO_EXPAND_FIELDS:
        return value
    if isinstance(value, str):
        for key, getter in _PLACEHOLDERS.items():
            if key in value:
                value = value.replace(key, str(getter()))
        return value
    if isinstance(value, dict):
        return {k: _expand_placeholders(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_placeholders(v, _field) for v in value]
    return value


def _resolve(name: str, folder: Path) -> Path:
    path = Path(name)
    if not path.suffix:
        path = path.with_suffix(".json")
    return path if path.is_absolute() else folder / path


def load_json(name: str):
    """读取 data/ 下的 JSON 数据文件。"""
    path = _resolve(name, DATA_DIR)
    if not path.exists():
        raise FileNotFoundError(f"测试数据文件不存在：{path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_cases(name: str, group: str = None):
    """加载用例列表，支持按 group 过滤（一个文件管理一个模块的多类场景）。"""
    data = load_json(name)
    if isinstance(data, list):
        cases = data
    elif isinstance(data, dict):
        if "cases" in data:
            cases = data["cases"]
        elif group and group in data:
            cases = data[group]
        else:
            raise ValueError(f"数据文件 {name} 结构不支持：需要 list 或包含 cases 字段")
    else:
        raise ValueError(f"数据文件 {name} 结构不支持：{type(data).__name__}")

    if group:
        filtered = [c for c in cases if c.get("group") in (None, group)]
        if not filtered:
            # 分组名写错时必须报错：静默回退到全量会让"用例跑多了"完全无人察觉，
            # 与"少跑却全绿"一样属于结果不可信。这里列出可用分组，便于一眼定位拼写问题。
            available = sorted({str(c.get("group")) for c in cases if c.get("group")})
            raise ValueError(
                f"数据文件 {name} 中没有 group={group!r} 的用例；可用分组：{'、'.join(available) or '无'}"
            )
        cases = filtered
    return [_expand_placeholders(case) for case in cases]


def case_ids(cases) -> list:
    """生成可读的用例 ID：编号 + 场景描述。"""
    ids = []
    for index, case in enumerate(cases, start=1):
        ids.append(f"{index:02d}-{case.get('desc', 'case')}")
    return ids


def build_params(cases) -> list:
    """把用例数据转换成 pytest.param 列表，自动为 known_defect 用例打 xfail 标记。"""
    import pytest

    params = []
    for index, case in enumerate(cases, start=1):
        case = dict(case)
        case_id = f"{index:02d}-{case.get('desc', 'case')}"
        xfail_reason = case.get("known_defect")
        if xfail_reason:
            params.append(pytest.param(case, id=case_id, marks=pytest.mark.xfail(reason=xfail_reason, strict=False)))
        else:
            params.append(pytest.param(case, id=case_id))
    return params


def load_schema(name: str) -> dict:
    """读取 data/schemas/ 下的响应结构定义。"""
    return load_json(str(Path("schemas") / Path(name).with_suffix(".json")))


def stamp() -> str:
    """时间戳（毫秒级），用于生成唯一测试数据。"""
    return datetime.now().strftime("%m%d%H%M%S") + f"{datetime.now().microsecond // 1000:03d}"


def unique(prefix: str = TEST_DATA_PREFIX, max_len: int = 26) -> str:
    """生成唯一且可识别的测试数据（避免污染共享测试环境 / 用例互相干扰）。

    截断时必须保住"唯一部分"（时间戳 + 随机串）：直接 `value[:max_len]` 会在
    `max_len` 接近前缀长度时把随机段整体砍掉，返回值退化成常量前缀，
    多人并发跑同一沙箱就会互相覆盖/删除对方的数据。
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    value = f"{prefix}{stamp()}{suffix}"
    if max_len <= 0 or len(value) <= max_len:
        return value
    unique_part = value[len(prefix):]          # 时间戳 + 随机串 = 唯一性来源
    if len(unique_part) >= max_len:
        return unique_part[-max_len:]          # 长度不足以同时容纳前缀时，优先保住唯一性
    return f"{prefix[: max_len - len(unique_part)]}{unique_part}"
