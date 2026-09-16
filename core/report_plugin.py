"""测试结果汇总与归档插件（pytest 插件，由 pytest.ini 自动加载）。

解决什么问题
------------
pytest-html 每次执行都会覆盖 `reports/report.html`，历史结果留不下来，
于是无法回答"这次回归比上次好还是差"。本插件把每次执行的结构化结果**归档**并渲染成看板。

产出（互不覆盖）
----------------
    reports/summary.json                     最近一次执行的结构化结果（看板主数据源）
    reports/dashboard.html                   质量看板（最新）
    reports/history/<run_id>/summary.json    每次执行的结果归档
    reports/history/<run_id>/dashboard.html  该次执行的看板快照（与报告一起留档）

设计说明
--------
1. 用 pytest hook 采集，而不是事后解析文本报告：能拿到 marker、模块、阶段耗时、跳过原因与缺陷单号；
2. 汇总里包含环境能力矩阵，看板才能回答"哪些用例因环境能力缺失被跳过、为什么"；
3. 归档按次数裁剪（默认保留最近 50 次），既保留历史又不会无限增长；
4. 归档/渲染失败只打印提示，绝不影响测试结果本身。
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest

from config.setting import BASE_URL, ENV_NAME, REPORT_DIR
from core import env_check

HISTORY_DIR = REPORT_DIR / "history"
SUMMARY_FILE = REPORT_DIR / "summary.json"
DASHBOARD_FILE = REPORT_DIR / "dashboard.html"
SCHEMA_VERSION = 1
DEFAULT_HISTORY_KEEP = 50

# 用例类型 marker（看板按此分类展示）
TYPE_MARKERS = ("smoke", "regression", "p0", "positive", "boundary", "negative", "e2e")

# 模块中文名（看板展示用；未登记的模块回退为文件名）
MODULE_LABELS = {
    "test_login": "用户登录",
    "test_user_center": "首页/用户中心",
    "test_search": "商品搜索",
    "test_goods": "商品",
    "test_cart": "购物车",
    "test_address": "收货地址/地区",
    "test_order": "订单",
    "test_order_e2e": "E2E 闭环",
    "test_coupon": "优惠券",
    "test_merchant": "商家后台",
    "test_report_tools": "报告工具（自测）",
}

_DEFECT_RE = re.compile(r"BUG-[A-Z]+(?:-[A-Z]+)*-\d+")

# 会话级状态：由 hook 写入，sessionfinish 落盘
_STATE = {"run_id": None, "tag": "", "started": None, "cases": {}}


# ------------------------------------------------------------------ pytest 选项
def pytest_addoption(parser):
    group = parser.getgroup("shopxo", "ShopXO 测试结果归档与看板")
    group.addoption("--run-id", action="store", default=None, help="本次执行编号（默认时间戳）")
    group.addoption("--run-tag", action="store", default="", help="本次执行标签，如 smoke/regression")
    group.addoption(
        "--history-keep",
        action="store",
        type=int,
        default=DEFAULT_HISTORY_KEEP,
        help=f"历史结果保留次数（默认 {DEFAULT_HISTORY_KEEP}）",
    )
    group.addoption("--no-dashboard", action="store_true", default=False, help="不生成质量看板（仍会归档结构化结果）")


# ------------------------------------------------------------------ 采集
def pytest_sessionstart(session):
    config = session.config
    _STATE["cases"] = {}
    _STATE["run_id"] = config.getoption("--run-id") or datetime.now().strftime("%Y%m%d-%H%M%S")
    _STATE["tag"] = config.getoption("--run-tag") or ""
    _STATE["started"] = time.time()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """采集每个用例的 setup/call/teardown 三个阶段。"""
    outcome = yield
    report = outcome.get_result()
    record = _STATE["cases"].setdefault(report.nodeid, _new_record(item, report))
    record["phases"][report.when] = {
        "outcome": report.outcome,
        "duration": round(report.duration, 4),
        "wasxfail": getattr(report, "wasxfail", None),
        "message": _report_message(report),
    }


def _new_record(item, report) -> dict:
    file_name = Path(str(getattr(item, "fspath", "unknown.py"))).name
    markers = sorted({marker.name for marker in item.iter_markers()})
    doc = ""
    function = getattr(item, "function", None)
    if function is not None and function.__doc__:
        doc = function.__doc__.strip().splitlines()[0]
    return {
        "nodeid": report.nodeid,
        "name": getattr(item, "name", report.nodeid),
        "file": file_name,
        "module": MODULE_LABELS.get(Path(file_name).stem, Path(file_name).stem),
        "markers": markers,
        "types": [name for name in markers if name in TYPE_MARKERS],
        "doc": doc,
        "phases": {},
    }


def _report_message(report) -> str:
    """提取可读的原因/失败信息：跳过原因、xfail 原因、失败断言的最后一行。"""
    wasxfail = getattr(report, "wasxfail", None)
    if wasxfail and not report.failed:
        return str(wasxfail)[:500]
    if report.skipped:
        longrepr = report.longrepr
        if isinstance(longrepr, tuple) and len(longrepr) == 3:
            return str(longrepr[2])[:500]
        return str(longrepr)[:500] if longrepr else "跳过"
    if report.failed:
        if wasxfail:
            return str(wasxfail)[:500]
        text = (getattr(report, "longreprtext", "") or str(report.longrepr or "")).strip()
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1][:500]
    return ""


def final_outcome(phases: dict) -> str:
    """把三个阶段的结果归并成最终结论（顺序与 pytest 语义保持一致）。"""
    setup, call, teardown = (phases.get(name) for name in ("setup", "call", "teardown"))
    if setup and setup["outcome"] == "failed":
        return "error"                       # 夹具/环境初始化失败 → 错误
    if call is None:
        return "skipped" if setup and setup["outcome"] == "skipped" else "error"
    if call["outcome"] == "skipped":
        return "xfailed" if call.get("wasxfail") else "skipped"
    if call["outcome"] == "failed":
        if call.get("wasxfail"):
            # strict xfail 意外通过时 pytest 记为 failed，这里仍按 xpassed 统计
            return "xpassed" if "XPASS" in (call.get("message") or "") else "xfailed"
        return "failed"
    if teardown and teardown["outcome"] == "failed":
        return "error"                       # 数据清理失败也算错误，必须暴露
    return "xpassed" if call.get("wasxfail") else "passed"


# ------------------------------------------------------------------ 汇总
def build_summary(exitstatus: int) -> dict:
    """把采集到的原始数据整理成看板可直接消费的结构。"""
    cases = []
    for record in _STATE["cases"].values():
        phases = record["phases"]
        outcome = final_outcome(phases)
        message = ""
        for phase_name in ("call", "setup", "teardown"):
            phase = phases.get(phase_name)
            if phase and phase.get("message"):
                message = phase["message"]
                break
        defect = _DEFECT_RE.search(message or "")
        cases.append(
            {
                "nodeid": record["nodeid"],
                "name": record["name"],
                "file": record["file"],
                "module": record["module"],
                "types": record["types"],
                "markers": record["markers"],
                "doc": record["doc"],
                "outcome": outcome,
                "duration": round(sum(p.get("duration", 0) for p in phases.values()), 4),
                "message": message,
                "defect": defect.group(0) if defect else "",
            }
        )
    cases.sort(key=lambda case: (case["file"], case["name"]))

    finished = time.time()
    totals = _totals(cases)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "id": _STATE["run_id"],
            "tag": _STATE["tag"],
            "started_at": datetime.fromtimestamp(_STATE["started"]).strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": datetime.fromtimestamp(finished).strftime("%Y-%m-%d %H:%M:%S"),
            "duration": round(finished - _STATE["started"], 2),
            "exit_code": exitstatus,
        },
        "environment": {
            "base_url": BASE_URL,
            "env_name": ENV_NAME,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pytest": pytest.__version__,
        },
        "totals": totals,
        "capabilities": env_check.probe(),
        "modules": _modules(cases),
        "defects": _defects(cases),
        "cases": cases,
    }


def _totals(cases: list) -> dict:
    totals = {key: 0 for key in ("total", "passed", "failed", "error", "skipped", "xfailed", "xpassed")}
    for case in cases:
        totals["total"] += 1
        totals[case["outcome"]] = totals.get(case["outcome"], 0) + 1
    executed = totals["total"] - totals["skipped"]
    totals["pass_rate"] = round(totals["passed"] / totals["total"] * 100, 2) if totals["total"] else 0.0
    totals["executed_pass_rate"] = round(totals["passed"] / executed * 100, 2) if executed else 0.0
    return totals


def _modules(cases: list) -> list:
    modules = {}
    for case in cases:
        item = modules.setdefault(
            case["module"],
            {"name": case["module"], "file": case["file"], "total": 0, "passed": 0,
             "failed": 0, "error": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "duration": 0.0},
        )
        item["total"] += 1
        item[case["outcome"]] = item.get(case["outcome"], 0) + 1
        item["duration"] = round(item["duration"] + case["duration"], 3)
    return sorted(modules.values(), key=lambda module: module["file"])


def _defects(cases: list) -> list:
    """从 xfail 守护用例反推缺陷清单：缺陷修复后用例会变 XPASS，看板自动改状态。"""
    defects = {}
    for case in cases:
        if not case["defect"]:
            continue
        item = defects.setdefault(
            case["defect"],
            {"id": case["defect"], "status": "open", "desc": "", "cases": []},
        )
        item["cases"].append(case["name"])
        if not item["desc"] and case["message"]:
            item["desc"] = case["message"]
        if case["outcome"] == "xpassed":
            item.setdefault("_fixed", []).append(case["name"])
    for item in defects.values():
        fixed = len(item.pop("_fixed", []))
        if fixed == len(item["cases"]):
            item["status"] = "fixed"
    return sorted(defects.values(), key=lambda defect: defect["id"])


# ------------------------------------------------------------------ 落盘与归档
def _dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_run_archive(summary: dict, keep: int = DEFAULT_HISTORY_KEEP) -> Path:
    """把本次结果写入 history/<run_id>/，并按 keep 裁剪最旧的归档。"""
    run_dir = HISTORY_DIR / summary["run"]["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    _dump(summary, run_dir / "summary.json")
    prune_history(keep)
    return run_dir


def prune_history(keep: int) -> list:
    """只保留最近 keep 次归档，返回被删除的目录名。"""
    if keep <= 0 or not HISTORY_DIR.exists():
        return []
    runs = sorted([path for path in HISTORY_DIR.iterdir() if path.is_dir()], key=lambda path: path.name)
    removed = []
    for path in runs[:-keep] if len(runs) > keep else []:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def pytest_sessionfinish(session, exitstatus):
    """会话结束时归档结果并刷新看板（任何异常都不得影响测试结论）。"""
    if not _STATE["cases"]:
        return
    try:
        summary = build_summary(int(exitstatus))
        _dump(summary, SUMMARY_FILE)
        run_dir = write_run_archive(summary, session.config.getoption("--history-keep"))

        if session.config.getoption("--no-dashboard"):
            print(f"\n[报告归档] 本次结果：{HISTORY_DIR.joinpath(summary['run']['id']).relative_to(REPORT_DIR.parent)}")
            return

        from core import dashboard

        html = dashboard.render_dashboard(summary, dashboard.load_history(HISTORY_DIR))
        DASHBOARD_FILE.write_text(html, encoding="utf-8")
        (run_dir / "dashboard.html").write_text(html, encoding="utf-8")

        print(
            f"\n[报告归档] 质量看板：{DASHBOARD_FILE.relative_to(REPORT_DIR.parent)}"
            f"（历史归档 {run_dir.relative_to(REPORT_DIR.parent)}）"
        )
    except Exception as exc:  # noqa: BLE001 - 归档失败不能影响测试结果
        print(f"\n[报告归档] 归档失败（不影响测试结论）：{type(exc).__name__}: {exc}")
