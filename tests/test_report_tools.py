"""报告与质量看板工具的自测（纯离线，不依赖被测环境）。

为什么要测"看板"
----------------
看板是给人看的结论。如果汇总/渲染逻辑本身有问题（总数对不上、跳过没写原因、
或者页面偷偷依赖 CDN 导致离线打不开），展示层就会"说谎"——这是测试岗最不能接受的。
所以这里用构造数据把这几条底线固定下来。
"""
import json

import pytest

from core import dashboard, report_plugin

# 本文件全部是"不依赖真实环境的框架自测"，离线模式下也会执行（见 run.py --offline）
pytestmark = pytest.mark.offline


def _case(nodeid: str, outcome: str, message: str = "", module: str = "订单", defect: str = "") -> dict:
    return {
        "nodeid": nodeid,
        "name": nodeid.split("::")[-1],
        "file": "tests/test_order.py",
        "module": module,
        "types": ["p0"],
        "markers": ["p0"],
        "doc": "",
        "outcome": outcome,
        "duration": 0.12,
        "message": message,
        "defect": defect,
    }


def _summary(run_id: str = "20260101-000000", cases=None, tag: str = "smoke") -> dict:
    cases = cases if cases is not None else [
        _case("tests/test_order.py::test_ok", "passed"),
        _case("tests/test_order.py::test_skip", "skipped", "环境[http://x]不支持能力[coupon]：应用未安装[coupon]"),
        _case("tests/test_order.py::test_defect", "xfailed",
              "缺陷 BUG-ORDER-FILTER-001：订单列表 status 筛选未生效", defect="BUG-ORDER-FILTER-001"),
    ]
    totals = {key: 0 for key in ("passed", "failed", "error", "skipped", "xfailed", "xpassed")}
    for case in cases:
        totals[case["outcome"]] = totals.get(case["outcome"], 0) + 1
    totals["total"] = len(cases)
    executed = max(totals["total"] - totals["skipped"], 1)
    totals["pass_rate"] = round(totals["passed"] / max(totals["total"], 1) * 100, 2)
    totals["executed_pass_rate"] = round(totals["passed"] / executed * 100, 2)
    return {
        "schema_version": 1,
        "run": {"id": run_id, "tag": tag, "started_at": "2026-01-01 00:00:00",
                "finished_at": "2026-01-01 00:00:03", "duration": 3.0, "exit_code": 0},
        "environment": {"base_url": "http://shop-xo.hctestedu.com", "env_name": "test",
                        "python": "3.11.7", "pytest": "9.1.1"},
        "totals": totals,
        "capabilities": {"features": {"coupon": False}, "details": {"coupon": "应用未安装[coupon]"}},
        "modules": [{"name": "订单", "file": "tests/test_order.py", "total": len(cases),
                     "passed": totals["passed"], "failed": 0, "error": 0,
                     "skipped": totals["skipped"], "xfailed": totals["xfailed"], "duration": 0.36}],
        "defects": [{"id": "BUG-ORDER-FILTER-001", "status": "open",
                     "desc": "缺陷 BUG-ORDER-FILTER-001：订单列表 status 筛选未生效",
                     "cases": ["test_defect"]}],
        "cases": cases,
    }


# ------------------------------------------------------------------ 数据自检
def test_validate_summary_accepts_consistent_result():
    assert dashboard.validate_summary(_summary()) == []


def test_validate_summary_detects_inconsistent_totals():
    summary = _summary()
    summary["totals"]["total"] = 99          # 故意把总数改成与明细不符
    problems = dashboard.validate_summary(summary)
    assert problems and any("不一致" in item for item in problems)


def test_validate_summary_requires_reason_for_skipped_case():
    summary = _summary(cases=[_case("tests/test_order.py::test_skip", "skipped", "")])
    problems = dashboard.validate_summary(summary)
    assert problems and any("跳过用例未记录原因" in item for item in problems)


# ------------------------------------------------------------------ 看板渲染
def test_dashboard_renders_key_sections_offline():
    html = dashboard.render_dashboard(_summary(), history=[_summary(), _summary("20260102-000000")])

    for keyword in ("本次概览", "质量趋势", "模块覆盖", "缺陷看板", "失败与跳过诊断", "环境能力矩阵", "用例明细"):
        assert keyword in html, f"看板缺少分区：{keyword}"
    assert "BUG-ORDER-FILTER-001" in html          # 缺陷单号必须出现
    assert "应用未安装[coupon]" in html             # 跳过/能力原因必须出现
    assert "<svg" in html                          # 趋势图用内联 SVG，不依赖图表库


def test_dashboard_overview_cards_have_no_empty_values():
    """概览卡片不允许出现空值：耗时只在 run.duration 里，若只读 totals 就会渲染成空白卡片（已修复）。"""
    html = dashboard.render_dashboard(_summary())

    assert "<div class='k'>耗时</div><div class='v blue'>3.0s</div>" in html
    assert "class='v blue'></div>" not in html, "概览卡片出现了空值"

    # 离线可用：不得引用任何外部资源（CDN/字体/图片）
    for bad in ('src="http', "src='http", 'href="http', "href='http", "<link", "<script src"):
        assert bad not in html, f"看板引用了外部资源：{bad}"


def test_dashboard_survives_without_history():
    html = dashboard.render_dashboard(_summary(), history=[])
    assert "尚无历史数据" in html


# ------------------------------------------------------------------ 归档
def test_history_archive_keeps_latest_runs_sorted(tmp_path, monkeypatch):
    monkeypatch.setattr(report_plugin, "HISTORY_DIR", tmp_path)

    for run_id in ("20260101-000000", "20260102-000000", "20260103-000000"):
        report_plugin.write_run_archive(_summary(run_id), keep=2)

    remaining = sorted(path.name for path in tmp_path.iterdir())
    assert remaining == ["20260102-000000", "20260103-000000"], "归档应只保留最近 2 次"

    history = dashboard.load_history(tmp_path)
    assert [item["run"]["id"] for item in history] == ["20260102-000000", "20260103-000000"]
    assert json.loads((tmp_path / "20260103-000000" / "summary.json").read_text(encoding="utf-8"))["totals"]["total"] == 3


# ------------------------------------------------------------------ 结论归并
@pytest.mark.parametrize(
    "phases, expected",
    [
        ({"setup": {"outcome": "failed"}, "call": None}, "error"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "passed"}}, "passed"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "message": "缺数据"}}, "skipped"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "wasxfail": "已知缺陷"}}, "xfailed"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "failed", "message": "断言失败"}}, "failed"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "passed", "wasxfail": "已知缺陷"}}, "xpassed"),
        ({"setup": {"outcome": "passed"}, "call": {"outcome": "passed"}, "teardown": {"outcome": "failed"}}, "error"),
    ],
)
def test_final_outcome_mapping(phases, expected):
    assert report_plugin.final_outcome(phases) == expected


# ------------------------------------------------------------------ 与上次对比
def test_compare_runs_detects_new_failure_and_fix():
    """发版判断看的是"新增失败"，不是绝对失败数——这里把差集逻辑固定下来。"""
    previous = _summary("20260101-000000", cases=[
        _case("tests/test_order.py::test_ok", "passed"),
        _case("tests/test_order.py::test_will_fail", "passed"),
        _case("tests/test_order.py::test_will_fix", "failed", "断言失败：金额不一致"),
        _case("tests/test_order.py::test_was_skipped", "passed"),
    ])
    current = _summary("20260102-000000", cases=[
        _case("tests/test_order.py::test_ok", "passed"),
        _case("tests/test_order.py::test_will_fail", "failed", "断言失败：订单状态不符"),
        _case("tests/test_order.py::test_will_fix", "passed"),
        _case("tests/test_order.py::test_was_skipped", "skipped", "环境不支持能力[coupon]"),
    ])

    comparison = dashboard.compare_runs(current, previous)

    assert comparison["has_previous"] is True
    assert comparison["previous"]["id"] == "20260101-000000"
    assert [item["name"] for item in comparison["new_failures"]] == ["test_will_fail"]
    assert [item["name"] for item in comparison["fixed"]] == ["test_will_fix"]
    assert [item["name"] for item in comparison["newly_skipped"]] == ["test_was_skipped"]
    # 失败总数净变化为 0（新增 1 条、修复 1 条），但"新增失败"卡片必须能指出那 1 条
    assert comparison["totals_delta"]["failed"] == 0
    assert len(comparison["new_failures"]) == 1
    assert comparison["totals_delta"]["skipped"] == 1
    assert comparison["totals_delta"]["passed"] == -1


def test_compare_runs_without_previous_is_explicit():
    comparison = dashboard.compare_runs(_summary(), None)
    assert comparison["has_previous"] is False
    assert comparison["new_failures"] == []
    assert "首次" in comparison["reason"]


def test_compare_runs_counts_new_failing_case_as_new_failure():
    """新增用例一上来就失败，也必须算进"新增失败"，不能因为"上次没有"就忽略。"""
    previous = _summary("20260101-000000", cases=[_case("tests/test_order.py::test_ok", "passed")])
    current = _summary("20260102-000000", cases=[
        _case("tests/test_order.py::test_ok", "passed"),
        _case("tests/test_order.py::test_brand_new", "error", "夹具初始化失败"),
    ])
    comparison = dashboard.compare_runs(current, previous)
    assert [item["name"] for item in comparison["new_failures"]] == ["test_brand_new"]
    assert comparison["persistent_failures"] == []


def test_pick_previous_prefers_same_tag():
    history = [
        _summary("20260101-000000", tag="全量"),
        _summary("20260102-000000", tag="smoke"),
        _summary("20260103-000000", tag="全量"),
    ]
    current = _summary("20260104-000000", tag="全量")
    assert dashboard.pick_previous(history, current)["run"]["id"] == "20260103-000000"
    assert dashboard.pick_previous(history, _summary("20260105-000000", tag="smoke"))["run"]["id"] == "20260102-000000"


def test_pick_previous_returns_none_for_first_run():
    assert dashboard.pick_previous([], _summary()) is None
    assert dashboard.pick_previous([_summary("20260101-000000")], _summary("20260101-000000")) is None


# ------------------------------------------------------------------ 不稳定用例
def test_compute_flaky_only_reports_real_flips():
    """既通过又失败才算不稳定；跳过（环境门控）与只跑过一次的用例都不算。"""
    history = [
        _summary("20260101-000000", cases=[
            _case("tests/test_order.py::test_flip", "passed"),
            _case("tests/test_order.py::test_stable", "passed"),
            _case("tests/test_order.py::test_gated", "skipped", "环境不支持能力[coupon]"),
        ]),
        _summary("20260102-000000", cases=[
            _case("tests/test_order.py::test_flip", "failed", "偶发：接口超时"),
            _case("tests/test_order.py::test_stable", "passed"),
            _case("tests/test_order.py::test_gated", "passed"),
            _case("tests/test_order.py::test_once", "passed"),
        ]),
        _summary("20260103-000000", cases=[
            _case("tests/test_order.py::test_flip", "passed"),
            _case("tests/test_order.py::test_stable", "passed"),
        ]),
    ]

    flaky = dashboard.compute_flaky(history)
    names = [item["nodeid"].split("::")[-1] for item in flaky]

    assert names == ["test_flip"], f"只应报告真正翻转过的用例，实际：{names}"
    assert flaky[0]["appearances"] == 3
    assert flaky[0]["failures"] == 1
    assert flaky[0]["flaky_rate"] == 33.3
    assert flaky[0]["last"] == "passed"


def test_compute_flaky_is_empty_when_everything_is_stable():
    history = [_summary(f"2026010{i}-000000", cases=[_case("tests/test_order.py::test_ok", "passed")]) for i in (1, 2, 3)]
    assert dashboard.compute_flaky(history) == []


def test_dashboard_renders_governance_sections():
    run1 = _summary("20260101-000000", cases=[
        _case("tests/test_order.py::test_flip", "passed"),
        _case("tests/test_order.py::test_will_fail", "passed"),
    ])
    run2 = _summary("20260102-000000", cases=[
        _case("tests/test_order.py::test_flip", "failed", "偶发：接口超时"),
        _case("tests/test_order.py::test_will_fail", "failed", "断言失败：订单状态不符"),
    ])
    html = dashboard.render_dashboard(run2, history=[run1, run2])

    assert "与上次执行对比" in html
    assert "新增失败" in html
    assert "不稳定用例（flaky）" in html
    assert "test_flip" in html
    assert "33.3%" in html or "50.0%" in html      # 不稳定度必须展示出来
    assert "20260101-000000" in html               # 对比对象可追溯
