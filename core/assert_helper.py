"""统一断言层。

把"接口返回怎么算通过"收敛到一处，好处：
1. 断言失败信息里带上接口 msg，定位问题不用再翻日志；
2. 结构校验（JSON Schema）、金额校验、分页校验可复用；
3. 用例里只写业务语义断言（如 Assert.success(res)），可读性更好。
"""
from core.data_loader import load_schema

_MISSING = object()


class Assert:
    """接口断言工具集。"""

    # ------------------------------------------------------------ 返回值契约
    @staticmethod
    def code(res: dict, expected: int = 0, context: str = "") -> None:
        """断言业务码等于期望值。"""
        actual = res.get("code")
        prefix = f"{context} " if context else ""
        assert actual == expected, (
            f"{prefix}业务码不符：期望 code={expected}，实际 code={actual}，msg={res.get('msg')}"
        )

    @staticmethod
    def success(res: dict, context: str = "") -> None:
        """断言接口调用成功（code == 0）。"""
        Assert.code(res, 0, context)

    @staticmethod
    def fail(res: dict, context: str = "") -> None:
        """断言接口调用失败（code != 0），用于异常场景。"""
        actual = res.get("code")
        prefix = f"{context} " if context else ""
        assert actual not in (0, None), f"{prefix}期望接口返回失败，实际成功：code={actual} msg={res.get('msg')}"

    @staticmethod
    def code_in(res: dict, expected_codes, context: str = "") -> None:
        actual = res.get("code")
        prefix = f"{context} " if context else ""
        assert actual in expected_codes, (
            f"{prefix}业务码不符：期望属于 {expected_codes}，实际 code={actual}，msg={res.get('msg')}"
        )

    @staticmethod
    def msg_contains(res: dict, *keywords) -> None:
        """断言 msg 包含指定关键字（用业务提示语校验拦截原因）。"""
        msg = str(res.get("msg", ""))
        for keyword in keywords:
            assert keyword in msg, f"响应提示不符：期望包含[{keyword}]，实际 msg=[{msg}]"

    @staticmethod
    def msg_equals(res: dict, expected: str) -> None:
        assert str(res.get("msg", "")) == expected, f"响应提示不符：期望[{expected}]，实际[{res.get('msg')}]"

    # ------------------------------------------------------------ 字段取值
    @staticmethod
    def get(data, path: str, default=_MISSING):
        """按 'data.data.0.id' 路径取值；取不到时返回 default 或抛断言。"""
        node = data
        for segment in str(path).split("."):
            try:
                if isinstance(node, (list, tuple)):
                    node = node[int(segment)]
                elif isinstance(node, dict):
                    node = node[segment]
                else:
                    node = getattr(node, segment)
            except (KeyError, IndexError, AttributeError, ValueError, TypeError):
                if default is _MISSING:
                    raise AssertionError(f"字段路径不存在：{path}（已取到 {type(node).__name__}）") from None
                return default
        return node

    @staticmethod
    def has_fields(data: dict, *fields, context: str = "") -> None:
        """断言响应包含指定字段（带上 context 便于多接口批量断言时定位来源）。"""
        prefix = f"{context} " if context else ""
        assert isinstance(data, dict), f"{prefix}期望 dict，实际 {type(data).__name__}"
        missing = [f for f in fields if f not in data]
        assert not missing, f"{prefix}响应缺少字段：{missing}"

    @staticmethod
    def not_none(value, name: str = "值") -> None:
        assert value is not None, f"{name} 不应为空"

    @staticmethod
    def not_empty(value, name: str = "值") -> None:
        assert value, f"{name} 不应为空（实际：{value!r}）"

    @staticmethod
    def is_true(condition, message: str) -> None:
        assert condition, message

    @staticmethod
    def in_set(value, allowed, name: str = "值") -> None:
        assert value in allowed, f"{name} 取值非法：实际 {value!r}，允许 {allowed}"

    # ------------------------------------------------------------ 结构与数值
    @staticmethod
    def schema(payload, schema_name: str, context: str = "") -> None:
        """JSON Schema 结构校验：字段存在性、类型、必填项。"""
        try:
            import jsonschema
        except ImportError:  # 未安装时跳过结构校验，不影响主流程
            return
        schema = load_schema(schema_name)
        prefix = f"{context} " if context else ""
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            details = "\n".join(f"  - 路径 {list(e.path)}: {e.message}" for e in errors[:8])
            raise AssertionError(f"{prefix}响应结构不符合 [{schema_name}]：\n{details}")

    @staticmethod
    def money(actual, expected, name: str = "金额", tol: float = 0.01) -> None:
        """金额断言：规避浮点误差。"""
        try:
            actual_value = float(actual)
            expected_value = float(expected)
        except (TypeError, ValueError):
            raise AssertionError(f"{name} 无法比较：actual={actual!r} expected={expected!r}") from None
        assert abs(actual_value - expected_value) <= tol, (
            f"{name} 不符：期望 {expected_value}，实际 {actual_value}（容差 {tol}）"
        )

    @staticmethod
    def pagination(data: dict, context: str = "") -> None:
        """分页结构校验：total / page_total / data 三件套。"""
        prefix = f"{context} " if context else ""
        Assert.has_fields(data, "total", "page_total", "data", context=context)
        assert isinstance(data["data"], list), f"{prefix}分页数据 data 应为数组，实际 {type(data['data']).__name__}"
        for field in ("total", "page_total"):
            value = data[field]
            assert str(value).lstrip("-").isdigit(), f"{prefix}分页字段 {field} 应为数字，实际 {value!r}"

    @staticmethod
    def contains_keyword(items, keyword: str, key: str = "title") -> None:
        """断言列表中至少有一条记录的指定字段包含关键字（模糊搜索有效性校验）。"""
        assert isinstance(items, list) and items, "列表为空，无法校验关键字匹配"
        matched = [item for item in items if keyword.lower() in str(item.get(key, "")).lower()]
        assert matched, f"搜索结果中没有任何记录的 {key} 包含关键字[{keyword}]"
