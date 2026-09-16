"""Allure 报告适配层。

设计目标：**Allure 是可选增强，不是运行前提**。
未安装 allure-pytest 时，本模块所有函数降级为空操作，
用例如常执行、断言照常生效，避免因报告组件缺失导致回归跑不起来。
"""
from contextlib import contextmanager

from core.logger import get_logger

logger = get_logger("shopxo.allure")

try:  # pragma: no cover - 取决于运行环境
    import allure  # type: ignore

    ALLURE_AVAILABLE = True
except Exception:  # noqa: BLE001 - 任何导入异常都降级
    allure = None
    ALLURE_AVAILABLE = False


def attach_text(body: str, name: str = "附件") -> None:
    """附加文本（如 curl 命令）。"""
    if not ALLURE_AVAILABLE:
        return
    try:
        allure.attach(str(body), name=name, attachment_type=allure.attachment_type.TEXT)
    except Exception:  # noqa: BLE001
        pass


def attach_json(data, name: str = "响应") -> None:
    """附加 JSON 数据（自动截断超长内容，避免报告过大）。"""
    if not ALLURE_AVAILABLE:
        return
    import json

    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if len(text) > 20000:
            text = text[:20000] + "\n...（内容过长已截断）"
        allure.attach(text, name=name, attachment_type=allure.attachment_type.JSON)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def step(title: str):
    """Allure 步骤；未安装 Allure 时等价于普通代码块。"""
    if not ALLURE_AVAILABLE:
        yield
        return
    try:
        with allure.step(title):
            yield
    except Exception:  # noqa: BLE001 - allure 自身异常不影响业务断言
        yield


def mark(feature: str = None, story: str = None, title: str = None, description: str = None, severity: str = None) -> None:
    """动态标注用例的模块/场景/标题/描述/级别。"""
    if not ALLURE_AVAILABLE:
        return
    try:
        if feature:
            allure.dynamic.feature(feature)
        if story:
            allure.dynamic.story(story)
        if title:
            allure.dynamic.title(title)
        if description:
            allure.dynamic.description(description)
        if severity and hasattr(allure, "severity_level"):
            allure.dynamic.severity(getattr(allure.severity_level, severity.upper(), None))
    except Exception:  # noqa: BLE001
        pass
