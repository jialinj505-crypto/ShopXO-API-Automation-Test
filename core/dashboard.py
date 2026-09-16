"""质量看板渲染器：把归档的结构化结果渲染成一个**自包含、可离线打开**的 HTML 看板。

为什么是静态 HTML
-----------------
- 面试/交付场景常常没有网络、也不想先起服务：单文件双击即开，可以直接发给别人；
- 不引入任何 CDN 与第三方图表库（图表用内联 SVG 生成，交互用几十行原生 JS），
  保证离线可用，也避免"打不开就看不懂报告"；
- 只读消费归档数据，不参与测试执行，测试环境零额外依赖。

数据来源：`reports/summary.json`（最近一次）+ `reports/history/*/summary.json`（趋势），
两者都由 `core/report_plugin.py` 在 pytest 会话结束时自动写入。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from config.setting import REPORT_DIR

HISTORY_DIR = REPORT_DIR / "history"
SUMMARY_FILE = REPORT_DIR / "summary.json"
DASHBOARD_FILE = REPORT_DIR / "dashboard.html"

OUTCOME_LABELS = {
    "passed": "通过",
    "failed": "失败",
    "error": "错误",
    "skipped": "跳过",
    "xfailed": "缺陷守护",
    "xpassed": "缺陷已修复",
}
OUTCOME_ORDER = ("failed", "error", "skipped", "xfailed", "xpassed", "passed")

# 环境类失败的特征词：用于把"环境问题"与"产品缺陷/用例问题"分开
ENV_HINTS = (
    "AuthError", "登录失败", "缺少 token", "ConnectionError", "Timeout", "请求失败",
    "响应非 JSON", "-9998", "-9999", "未安装", "不支持能力", "非法访问",
)

_CSS = """
:root{--bg:#f5f7fa;--card:#fff;--line:#e3e8ef;--text:#1f2937;--dim:#6b7280;
--green:#16a34a;--red:#dc2626;--amber:#d97706;--blue:#2563eb;--gray:#9ca3af}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0 0 6px}
h2{font-size:16px;margin:0 0 12px;padding-left:10px;border-left:4px solid var(--blue)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:18px}
.meta{color:var(--dim);font-size:13px}
.meta b{color:var(--text);font-weight:600}
.links{margin-top:8px;font-size:13px}
.links a{color:var(--blue);text-decoration:none;margin-right:14px}
.links a:hover{text-decoration:underline}
.verdict{margin-top:12px;padding:10px 14px;border-radius:8px;font-weight:600;display:inline-block}
.verdict.good{background:#ecfdf5;color:#047857;border:1px solid #a7f3d0}
.verdict.bad{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}
.cards{display:flex;flex-wrap:wrap;gap:12px}
.card{flex:1 1 120px;min-width:120px;border:1px solid var(--line);border-radius:8px;
padding:12px 14px;background:#fbfcfe}
.card .k{color:var(--dim);font-size:12px}
.card .v{font-size:22px;font-weight:700;margin-top:2px}
.v.green{color:var(--green)}.v.red{color:var(--red)}.v.amber{color:var(--amber)}
.v.gray{color:var(--gray)}.v.blue{color:var(--blue)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f8fafc;color:var(--dim);font-weight:600;white-space:nowrap}
tr:hover td{background:#fcfdff}
.bar{height:8px;border-radius:4px;background:#eef2f7;overflow:hidden;min-width:70px}
.bar>i{display:block;height:100%}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;white-space:nowrap}
.t-passed{background:#ecfdf5;color:#047857}
.t-failed{background:#fef2f2;color:#b91c1c}
.t-error{background:#fff7ed;color:#c2410c}
.t-skipped{background:#f3f4f6;color:#4b5563}
.t-xfailed{background:#fffbeb;color:#b45309}
.t-xpassed{background:#eff6ff;color:#1d4ed8}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.filters input[type=search],.filters select{padding:6px 10px;border:1px solid var(--line);
border-radius:6px;font-size:13px;background:#fff;color:var(--text)}
.case-row .msg{max-height:2.9em;overflow:hidden;cursor:pointer;color:var(--dim);font-size:12px}
.case-row.open .msg{max-height:none;white-space:pre-wrap}
.hint{color:var(--dim);font-size:12px;margin-top:8px}
.triage{display:flex;gap:14px;flex-wrap:wrap}
.triage .box{flex:1 1 240px;border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.triage .box h3{margin:0 0 8px;font-size:13px}
.triage ul{margin:0;padding-left:18px;color:var(--dim);font-size:12px}
code{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:12px}
footer{color:var(--dim);font-size:12px;text-align:center;margin-top:8px}
"""

_JS = """
function applyFilter(){
  var q=(document.getElementById('kw').value||'').toLowerCase();
  var oc=document.getElementById('oc').value;
  var ty=document.getElementById('ty').value;
  var rows=document.querySelectorAll('#cases tbody tr.case-row');
  var shown=0;
  rows.forEach(function(tr){
    var okQ=!q||(tr.dataset.search||'').indexOf(q)>=0;
    var okO=oc==='all'||tr.dataset.outcome===oc;
    var okT=ty==='all'||(tr.dataset.types||'').indexOf(ty)>=0;
    var show=okQ&&okO&&okT;
    tr.style.display=show?'':'none';
    if(show){shown++;}
  });
  document.getElementById('cnt').textContent=shown;
}
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('#cases tbody tr.case-row').forEach(function(tr){
    tr.addEventListener('click',function(){tr.classList.toggle('open');});
  });
  applyFilter();
});
"""


# ------------------------------------------------------------------ 读取
def load_summary(path: Path = None) -> dict:
    path = Path(path or SUMMARY_FILE)
    if not path.exists():
        raise FileNotFoundError(f"未找到结果汇总文件：{path}（先执行一次 run.py）")
    return json.loads(path.read_text(encoding="utf-8"))


def load_history(history_dir: Path = None, limit: int = None) -> list:
    """按运行编号（时间戳）升序读取历史归档，只保留最近 limit 次。"""
    history_dir = Path(history_dir or HISTORY_DIR)
    if not history_dir.exists():
        return []
    runs = []
    for run_dir in sorted([path for path in history_dir.iterdir() if path.is_dir()], key=lambda path: path.name):
        summary_file = run_dir / "summary.json"
        if not summary_file.exists():
            continue
        try:
            runs.append(json.loads(summary_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return runs[-limit:] if limit else runs


# ------------------------------------------------------------------ 数据自检
def validate_summary(summary: dict) -> list:
    """校验结果汇总的自洽性，返回问题列表（空列表表示通过）。

    看板是给人看的，如果数据本身不自洽（总数对不上、跳过没写原因），
    展示层就会"说谎"——所以这里做一次强校验，并在页面底部展示校验结论。
    """
    problems = []
    totals = summary.get("totals") or {}
    cases = summary.get("cases") or []
    counted = sum(int(totals.get(key, 0)) for key in ("passed", "failed", "error", "skipped", "xfailed", "xpassed"))
    if counted != int(totals.get("total", -1)):
        problems.append(f"分类合计 {counted} 与用例总数 {totals.get('total')} 不一致")
    if int(totals.get("total", -1)) != len(cases):
        problems.append(f"用例总数 {totals.get('total')} 与明细条数 {len(cases)} 不一致")
    for case in cases:
        if case.get("outcome") == "skipped" and not case.get("message"):
            problems.append(f"跳过用例未记录原因：{case.get('nodeid')}")
        if case.get("outcome") in ("failed", "error") and not case.get("message"):
            problems.append(f"失败用例未记录失败信息：{case.get('nodeid')}")
    return problems


def pick_previous(history: list, current: dict) -> dict:
    """在历史里挑出"上一次可比执行"：优先同标签（同范围），否则取紧邻的上一次。"""
    current_run = current.get("run") or {}
    candidates = [run for run in history if (run.get("run") or {}).get("id") != current_run.get("id")]
    if not candidates:
        return None
    same_tag = [run for run in candidates if (run.get("run") or {}).get("tag") == current_run.get("tag")]
    return (same_tag or candidates)[-1]


def compare_runs(current: dict, previous: dict) -> dict:
    """把本次结果与上次结果做差集：新增失败 / 已修复 / 新增跳过 / 新增用例。

    这是"这次回归能不能发版"最直接的答案：绝对数（0 failed）不够，
    真正要盯的是**新增**的失败——它代表本次改动带进来的风险。
    """
    current_map = {case["nodeid"]: case for case in (current.get("cases") or [])}
    if not previous:
        return {"has_previous": False, "reason": "没有更早的归档，本次为首次可比执行", "new_failures": [],
                "fixed": [], "newly_skipped": [], "new_cases": [], "became_xpassed": [],
                "persistent_failures": [], "totals_delta": {}, "duration_delta": 0.0, "previous": None}

    previous_map = {case["nodeid"]: case for case in (previous.get("cases") or [])}
    buckets = {"new_failures": [], "fixed": [], "newly_skipped": [], "new_cases": [],
               "became_xpassed": [], "persistent_failures": []}
    for nodeid, case in current_map.items():
        now = case.get("outcome")
        before = previous_map.get(nodeid)
        row = {"nodeid": nodeid, "name": case.get("name"), "module": case.get("module"),
               "outcome": now, "message": case.get("message", ""),
               "before": before.get("outcome") if before else "新增"}
        if before is None:
            buckets["new_failures" if now in ("failed", "error") else "new_cases"].append(row)
        elif now in ("failed", "error"):
            buckets["persistent_failures" if before.get("outcome") in ("failed", "error") else "new_failures"].append(row)
        elif now == "xpassed":
            buckets["became_xpassed"].append(row)
        elif before.get("outcome") in ("failed", "error") and now in ("passed", "xfailed"):
            buckets["fixed"].append(row)
        elif now == "skipped" and before.get("outcome") in ("passed", "xfailed"):
            buckets["newly_skipped"].append(row)

    current_totals = current.get("totals") or {}
    previous_totals = previous.get("totals") or {}
    totals_delta = {
        key: int(current_totals.get(key, 0)) - int(previous_totals.get(key, 0))
        for key in ("total", "passed", "failed", "error", "skipped", "xfailed", "xpassed")
    }
    return {
        "has_previous": True,
        "previous": {"id": (previous.get("run") or {}).get("id"), "tag": (previous.get("run") or {}).get("tag")},
        "new_failures": buckets["new_failures"],
        "fixed": buckets["fixed"],
        "newly_skipped": buckets["newly_skipped"],
        "new_cases": buckets["new_cases"],
        "became_xpassed": buckets["became_xpassed"],
        "persistent_failures": buckets["persistent_failures"],
        "totals_delta": totals_delta,
        "duration_delta": round(
            float((current.get("run") or {}).get("duration", 0))
            - float((previous.get("run") or {}).get("duration", 0)),
            2,
        ),
    }


def compute_flaky(history: list, limit: int = 10) -> list:
    """跨执行统计"不稳定用例"（同一用例既通过过也失败过）。

    说明：环境能力导致的 `skipped` 不参与稳定性评估（那不是不稳定，是没条件跑）；
    只出现 1 次的用例无法判断稳定性，直接排除——避免把"新加用例"误报成 flaky。
    """
    stats = {}
    for run in history:
        run_id = (run.get("run") or {}).get("id")
        for case in run.get("cases") or []:
            outcome = case.get("outcome")
            if outcome == "skipped" or not outcome:
                continue
            item = stats.setdefault(
                case["nodeid"],
                {"nodeid": case["nodeid"], "name": case.get("name"), "module": case.get("module"),
                 "passes": 0, "failures": 0, "appearances": 0, "last": "", "last_run": ""},
            )
            if outcome in ("failed", "error"):
                item["failures"] += 1
            else:
                item["passes"] += 1
            item["appearances"] += 1
            item["last"] = outcome
            item["last_run"] = run_id

    flaky = []
    for item in stats.values():
        if item["appearances"] >= 2 and item["passes"] and item["failures"]:
            item["flaky_rate"] = round((1 - max(item["passes"], item["failures"]) / item["appearances"]) * 100, 1)
            flaky.append(item)
    flaky.sort(key=lambda item: (-item["flaky_rate"], -item["appearances"], item["nodeid"]))
    return flaky[:limit]


# ------------------------------------------------------------------ 渲染
def render_dashboard(summary: dict, history: list = None) -> str:
    history = list(history or [])
    totals = dict(summary.get("totals") or {})
    run = summary.get("run") or {}
    env = summary.get("environment") or {}
    totals.setdefault("duration", run.get("duration"))   # 概览卡片要显示耗时（原本只存在于 run 里）
    problems = validate_summary(summary)
    cases = summary.get("cases") or []

    failed = int(totals.get("failed", 0)) + int(totals.get("error", 0))
    verdict_class = "good" if failed == 0 else "bad"
    verdict_text = (
        f"本次回归通过：{totals.get('passed', 0)} passed"
        f" / {totals.get('failed', 0)} failed / {totals.get('error', 0)} error"
        if failed == 0
        else f"本次回归未通过：{totals.get('failed', 0)} failed / {totals.get('error', 0)} error"
    )

    # 质量治理数据：与上一次同范围执行的对比、跨执行的不稳定用例统计
    previous = pick_previous(history, summary)
    comparison = compare_runs(summary, previous)
    flaky = compute_flaky(history)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>ShopXO 接口自动化测试 · 质量看板</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<h1>ShopXO 接口自动化测试 · 质量看板</h1>",
        "<div class='meta'>"
        f"运行编号 <b>{_e(run.get('id'))}</b>｜标签 <b>{_e(run.get('tag') or '全部')}</b>｜"
        f"执行时间 <b>{_e(run.get('started_at'))}</b>｜耗时 <b>{_e(run.get('duration'))}s</b><br>"
        f"被测环境 <b>{_e(env.get('base_url'))}</b>（{_e(env.get('env_name'))}）｜"
        f"Python {_e(env.get('python'))}｜pytest {_e(env.get('pytest'))}</div>",
        "<div class='links'>"
        "<a href='report.html'>pytest-html 详细报告</a>"
        "<a href='allure-results/'>Allure 原始结果</a>"
        "<a href='env_probe.json'>环境能力探测</a>"
        "<a href='history/'>历史归档</a></div>",
        f"<div class='verdict {verdict_class}'>{_e(verdict_text)}</div>",
        "</div>",
        _cards(totals, comparison),
        _compare_section(comparison),
        _trend_section(history),
        _flaky_section(flaky, len(history)),
        _module_section(summary.get("modules") or []),
        _defect_section(summary.get("defects") or []),
        _triage_section(cases),
        _capability_section(summary.get("capabilities") or {}),
        _case_section(cases),
        "<footer>数据来源：<code>reports/history/*/summary.json</code>（由 pytest 插件在会话结束时自动归档，未经手工修改）"
        f"<br>数据自检：{'通过（分类合计、明细条数、跳过原因均一致）' if not problems else '发现 ' + str(len(problems)) + ' 个问题：' + _e('；'.join(problems[:3]))}"
        "</footer>",
        f"<script>{_JS}</script>",
        "</div></body></html>",
    ]
    return "\n".join(parts)


def build(report_dir: Path = None) -> Path:
    """读取归档并生成看板，返回看板路径。"""
    report_dir = Path(report_dir or REPORT_DIR)
    summary = load_summary(report_dir / "summary.json")
    history = load_history(report_dir / "history")
    html_text = render_dashboard(summary, history)
    out = report_dir / "dashboard.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _cards(totals: dict, comparison: dict = None) -> str:
    comparison = comparison or {}
    items = [
        ("用例总数", totals.get("total", 0), "blue"),
        ("通过", totals.get("passed", 0), "green"),
        ("失败", totals.get("failed", 0), "red"),
        ("错误", totals.get("error", 0), "amber"),
        ("跳过", totals.get("skipped", 0), "gray"),
        ("缺陷守护(xfail)", totals.get("xfailed", 0), "amber"),
        ("通过率", f"{totals.get('pass_rate', 0)}%", "green" if not totals.get("failed") else "amber"),
        ("可执行通过率", f"{totals.get('executed_pass_rate', 0)}%", "green" if not totals.get("failed") else "amber"),
        ("耗时", f"{totals['duration']}s" if totals.get("duration") is not None else "-", "blue"),
    ]
    if comparison.get("has_previous"):
        new_failures = len(comparison.get("new_failures") or [])
        items.append(("本次新增失败", new_failures, "red" if new_failures else "green"))
    cards = "".join(
        f"<div class='card'><div class='k'>{_e(name)}</div><div class='v {color}'>{_e(value)}</div></div>"
        for name, value, color in items
    )
    hint = (
        "通过率 = 通过 / 全部用例（含环境能力不足导致的跳过）；"
        "可执行通过率 = 通过 / (全部 - 跳过)，用于区分“环境没提供条件”与“真的挂了”。"
        "发版判断请看下一节的“新增失败”，它代表本次改动带进来的风险。"
    )
    return f"<section><h2>本次概览</h2><div class='cards'>{cards}</div><div class='hint'>{_e(hint)}</div></section>"


def _compare_section(comparison: dict) -> str:
    """与上次执行对比：新增失败 / 已修复 / 新增跳过。"""
    if not comparison.get("has_previous"):
        return (
            "<section><h2>与上次执行对比</h2><p class='hint'>"
            f"{_e(comparison.get('reason', '暂无历史可比'))}；再执行一次（相同标签/范围）后即可对比。</p></section>"
        )

    previous = comparison.get("previous") or {}
    delta = comparison.get("totals_delta") or {}
    cards = [
        ("新增失败", len(comparison.get("new_failures") or []), "red"),
        ("已修复", len(comparison.get("fixed") or []), "green"),
        ("新增跳过", len(comparison.get("newly_skipped") or []), "amber"),
        ("缺陷转已修复(xpass)", len(comparison.get("became_xpassed") or []), "blue"),
        ("新增用例", len(comparison.get("new_cases") or []), "gray"),
        ("耗时变化", f"{comparison.get('duration_delta', 0):+}s", "blue"),
        ("用例数变化", f"{delta.get('total', 0):+}", "gray"),
        ("通过数变化", f"{delta.get('passed', 0):+}", "green" if delta.get("passed", 0) >= 0 else "red"),
    ]
    card_html = "".join(
        f"<div class='card'><div class='k'>{_e(name)}</div><div class='v {color}'>{_e(value)}</div></div>"
        for name, value, color in cards
    )

    def rows(title: str, items: list, note: str) -> str:
        body = "".join(
            f"<tr><td>{_e(item.get('module'))}</td><td>{_e(item.get('name'))}</td>"
            f"<td>{_e(item.get('before'))} → {_e(item.get('outcome'))}</td>"
            f"<td>{_e((item.get('message') or '')[:160])}</td></tr>"
            for item in items[:10]
        )
        more = f"<div class='hint'>仅显示前 10 条，共 {len(items)} 条。</div>" if len(items) > 10 else ""
        if not items:
            return f"<div class='box'><h3>{_e(title)}（0）</h3><div class='hint'>无</div></div>"
        return (
            f"<div class='box'><h3>{_e(title)}（{len(items)}）</h3>"
            "<table><thead><tr><th>模块</th><th>用例</th><th>上次 → 本次</th><th>说明</th></tr></thead>"
            f"<tbody>{body}</tbody></table>{more}<div class='hint'>{_e(note)}</div></div>"
        )

    boxes = (
        rows("新增失败（重点看这里）", comparison.get("new_failures") or [],
             "上次通过/跳过、本次失败：优先怀疑本次改动带来的回归")
        + rows("已修复", comparison.get("fixed") or [], "上次失败、本次通过：确认是修复还是偶发，偶发要进不稳定清单")
    )
    boxes2 = (
        rows("新增跳过", comparison.get("newly_skipped") or [], "上次能跑、本次环境不满足：环境问题，不代表业务缺陷")
        + rows("缺陷守护转已修复(xpass)", comparison.get("became_xpassed") or [],
               "对应用例已 XPASS：可移除 data/*.json 里的 known_defect 标记")
    )
    if comparison.get("persistent_failures"):
        boxes2 += rows("持续失败（上次也失败）", comparison.get("persistent_failures") or [],
                       "不属于本次新增风险，但仍是未收敛的问题")
    return (
        f"<section><h2>与上次执行对比</h2>"
        f"<div class='hint'>对比对象：运行编号 <b>{_e(previous.get('id'))}</b>"
        f"（标签 {_e(previous.get('tag') or '无')}，优先选择与本次同标签的上一次执行）</div>"
        f"<div class='cards'>{card_html}</div>"
        f"<div class='triage' style='margin-top:14px'>{boxes}</div>"
        f"<div class='triage' style='margin-top:14px'>{boxes2}</div></section>"
    )


def _flaky_section(flaky: list, history_count: int) -> str:
    """不稳定用例（flaky）：跨执行既通过过也失败过的用例。"""
    if history_count < 2:
        return (
            "<section><h2>不稳定用例（flaky）</h2><p class='hint'>"
            "历史执行少于 2 次，暂无法评估稳定性。多次执行（相同标签/范围）后这里会给出不稳定清单。</p></section>"
        )
    if not flaky:
        return (
            "<section><h2>不稳定用例（flaky）</h2><p class='hint'>"
            f"已统计 {history_count} 次执行：没有被判定为不稳定的用例（同一用例未出现“既通过又失败”）。"
            "环境能力导致的跳过不计入稳定性评估。</p></section>"
        )
    rows = "".join(
        f"<tr><td>{_e(item.get('module'))}</td><td>{_e(item.get('name'))}</td>"
        f"<td>{item.get('appearances')}</td><td>{item.get('passes')}</td><td>{item.get('failures')}</td>"
        f"<td>{item.get('flaky_rate')}%</td>"
        f"<td><span class='tag t-{_e(item.get('last'))}'>{_e(OUTCOME_LABELS.get(item.get('last'), item.get('last')))}</span></td>"
        f"<td>{_e(item.get('last_run'))}</td></tr>"
        for item in flaky
    )
    hint = (
        "不稳定度 = 少数派结果占比（越高越不稳定）。处理建议：先隔离重跑确认，再判断是环境抖动还是真实偶发缺陷；"
        "确认偶发后从门禁中隔离（quarantine）但仍保留记录，避免“重跑变绿”掩盖问题。"
    )
    return (
        f"<section><h2>不稳定用例（flaky）</h2>"
        f"<div class='hint'>统计范围：最近 {history_count} 次执行；只统计执行过 2 次以上、且既有通过又有失败的用例</div>"
        "<table><thead><tr><th>模块</th><th>用例</th><th>执行次数</th><th>通过</th><th>失败</th>"
        "<th>不稳定度</th><th>最近结果</th><th>最近执行</th></tr></thead>"
        f"<tbody>{rows}</tbody></table><div class='hint'>{_e(hint)}</div></section>"
    )


def _trend_section(history: list, limit: int = 12) -> str:
    runs = history[-limit:]
    if not runs:
        return "<section><h2>质量趋势</h2><p class='hint'>尚无历史数据，多跑几次后这里会出现通过率与失败数趋势。</p></section>"
    hint = (
        "横轴为「运行编号后 6 位 / 用例总数」，纵轴为通过率，浅红柱为失败用例数。"
        "不同执行范围（如单独跑冒烟）会一起进入趋势，看图时请结合用例总数判断——这正是"
        "<strong>可执行通过率</strong>与<strong>用例总数</strong>要同时展示的原因。"
    )
    return (
        f"<section><h2>质量趋势（最近 {len(runs)} 次执行）</h2>{_trend_svg(runs)}"
        f"<div class='hint'>{_e(hint)}</div></section>"
    )


def _trend_svg(runs: list, width: int = 1080, height: int = 220, pad: int = 46) -> str:
    step = (width - 2 * pad) / max(len(runs) - 1, 1)
    max_failed = max([int((run.get("totals") or {}).get("failed", 0)) for run in runs] + [1])

    def x(index: int) -> float:
        return pad + index * step

    def y(rate: float) -> float:
        return pad + (100 - rate) / 100 * (height - 2 * pad)

    grid = []
    for rate in (0, 25, 50, 75, 100):
        line_y = y(rate)
        grid.append(f"<line x1='{pad}' y1='{line_y:.1f}' x2='{width - pad}' y2='{line_y:.1f}' stroke='#eef2f7'/>")
        grid.append(f"<text x='{pad - 8}' y='{line_y + 4:.1f}' text-anchor='end' font-size='11' fill='#9ca3af'>{rate}%</text>")

    points = []
    dots = []
    bars = []
    labels = []
    for index, run in enumerate(runs):
        totals = run.get("totals") or {}
        rate = float(totals.get("pass_rate", 0))
        points.append(f"{x(index):.1f},{y(rate):.1f}")
        dots.append(f"<circle cx='{x(index):.1f}' cy='{y(rate):.1f}' r='3.5' fill='#2563eb'/>")
        failed = int(totals.get("failed", 0))
        bar_height = (failed / max_failed) * 34 if failed else 0
        if bar_height:
            bars.append(
                f"<rect x='{x(index) - 7:.1f}' y='{height - pad - bar_height:.1f}' width='14' "
                f"height='{bar_height:.1f}' fill='#fecaca' rx='2'/>"
            )
        run_id = str((run.get("run") or {}).get("id", ""))
        total = int((run.get("totals") or {}).get("total", 0))
        labels.append(
            f"<text x='{x(index):.1f}' y='{height - pad + 16}' text-anchor='middle' "
            f"font-size='10' fill='#9ca3af'>{_e(run_id[-6:])} /{total}</text>"
        )

    legend = (
        f"<g font-size='11' fill='#6b7280'>"
        f"<line x1='{pad}' y1='18' x2='{pad + 22}' y2='18' stroke='#2563eb' stroke-width='2'/>"
        f"<text x='{pad + 28}' y='22'>通过率</text>"
        f"<rect x='{pad + 96}' y='11' width='14' height='10' fill='#fecaca' rx='2'/>"
        f"<text x='{pad + 116}' y='22'>失败用例数（最高 {max_failed} 条）</text></g>"
    )
    return (
        f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' role='img'>"
        f"{''.join(grid)}{''.join(bars)}{legend}"
        f"<polyline points='{' '.join(points)}' fill='none' stroke='#2563eb' stroke-width='2'/>"
        f"{''.join(dots)}{''.join(labels)}</svg>"
    )


def _module_section(modules: list) -> str:
    if not modules:
        return ""
    rows = []
    for module in modules:
        total = max(int(module.get("total", 0)), 1)
        passed = int(module.get("passed", 0))
        failed = int(module.get("failed", 0)) + int(module.get("error", 0))
        skipped = int(module.get("skipped", 0))
        width = passed / total * 100
        color = "#16a34a" if failed == 0 else "#dc2626"
        rows.append(
            "<tr>"
            f"<td>{_e(module.get('name'))}<br><span class='hint'>{_e(module.get('file'))}</span></td>"
            f"<td>{total}</td><td>{passed}</td><td>{failed}</td><td>{skipped}</td>"
            f"<td>{int(module.get('xfailed', 0))}</td><td>{_e(module.get('duration'))}s</td>"
            f"<td><div class='bar'><i style='width:{width:.0f}%;background:{color}'></i></div></td>"
            "</tr>"
        )
    return (
        "<section><h2>模块覆盖</h2><table><thead><tr>"
        "<th>模块</th><th>用例数</th><th>通过</th><th>失败/错误</th><th>跳过</th><th>缺陷守护</th><th>耗时</th><th>通过占比</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
    )


def _defect_section(defects: list) -> str:
    if not defects:
        return "<section><h2>缺陷看板</h2><p class='hint'>本次执行未涉及已登记缺陷。</p></section>"
    rows = []
    for defect in defects:
        fixed = defect.get("status") == "fixed"
        tag = (
            "<span class='tag t-xpassed'>已修复（可移除 xfail 标记）</span>"
            if fixed
            else "<span class='tag t-xfailed'>仍存在</span>"
        )
        rows.append(
            "<tr>"
            f"<td><code>{_e(defect.get('id'))}</code></td><td>{tag}</td>"
            f"<td>{_e(defect.get('desc'))}</td>"
            f"<td>{_e('、'.join(defect.get('cases') or []))}</td>"
            "</tr>"
        )
    return (
        "<section><h2>缺陷看板（由 xfail 守护用例自动汇总）</h2><table><thead><tr>"
        "<th>缺陷单</th><th>状态</th><th>现象与影响</th><th>守护用例</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><div class='hint'>缺陷修复后对应用例会变成 XPASS，这里的<strong>状态会自动变为“已修复”</strong>，"
        "提醒你移除 <code>known_defect</code> 标记——让已知问题变成可跟踪资产。</div></section>"
    )


def _triage_section(cases: list) -> str:
    defect_cases, env_cases, test_cases, skip_cases = [], [], [], []
    for case in cases:
        outcome = case.get("outcome")
        message = case.get("message") or ""
        if outcome in ("xfailed", "xpassed"):
            defect_cases.append(f"{case.get('name')}｜{case.get('defect')}")
        elif outcome in ("failed", "error"):
            if any(hint in message for hint in ENV_HINTS):
                env_cases.append(f"{case.get('name')}｜{message[:80]}")
            else:
                test_cases.append(f"{case.get('name')}｜{message[:80]}")
        elif outcome == "skipped":
            skip_cases.append(f"{case.get('name')}｜{message[:80]}")

    def box(title: str, rows: list, note: str) -> str:
        body = "".join(f"<li>{_e(row)}</li>" for row in rows[:6]) or "<li>无</li>"
        more = f"<li>…另有 {len(rows) - 6} 条</li>" if len(rows) > 6 else ""
        return f"<div class='box'><h3>{_e(title)}（{len(rows)}）</h3><ul>{body}{more}</ul><div class='hint'>{_e(note)}</div></div>"

    return (
        "<section><h2>失败与跳过诊断</h2><div class='triage'>"
        + box("产品缺陷（xfail 守护）", defect_cases, "已登记缺陷，修复后自动转 XPASS")
        + box("环境问题", env_cases, "账号/网络/插件等环境原因，不代表业务有缺陷")
        + box("用例问题", test_cases, "断言或数据需要人工确认")
        + box("跳过", skip_cases, "含环境能力不足与数据不满足前置条件")
        + "</div></section>"
    )


def _capability_section(capabilities: dict) -> str:
    features = capabilities.get("features") or {}
    details = capabilities.get("details") or {}
    if not features:
        return ""
    offline = bool(capabilities.get("offline"))
    rows = []
    for name, ok in features.items():
        if offline:
            tag = "<span class='tag t-skipped'>未探测</span>"
        else:
            tag = "<span class='tag t-passed'>支持</span>" if ok else "<span class='tag t-skipped'>不支持</span>"
        rows.append(f"<tr><td>{_e(name)}</td><td>{tag}</td><td>{_e(details.get(name, ''))}</td></tr>")
    base_url = capabilities.get("base_url") or capabilities.get("reachable")
    if offline:
        note = (
            "本次为<strong>离线模式</strong>：只执行不依赖真实环境的框架自测用例，未探测真实环境能力，"
            "因此上表显示“未探测”而不是“不支持”。"
        )
    else:
        note = (
            f"站点可达：{_e(base_url)}。能力不足时相关用例会<strong>明确跳过并写明原因</strong>，"
            "而不是静默通过——报告要能回答“为什么没跑”。"
        )
    return (
        "<section><h2>环境能力矩阵</h2><table><thead><tr><th>能力</th><th>结果</th><th>实测依据</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        f"<div class='hint'>{note}</div></section>"
    )


def _case_section(cases: list) -> str:
    options = "".join(
        f"<option value='{key}'>{_e(OUTCOME_LABELS[key])}</option>" for key in OUTCOME_ORDER
    )
    rows = []
    for case in cases:
        outcome = case.get("outcome", "passed")
        search = " ".join(
            [str(case.get("nodeid", "")), str(case.get("module", "")), str(case.get("name", "")),
             str(case.get("message", "")), ",".join(case.get("types") or [])]
        ).lower()
        types = ",".join(case.get("types") or [])
        rows.append(
            f"<tr class='case-row' data-outcome='{_e(outcome)}' data-types='{_e(types)}' data-search=\"{_e(search)}\">"
            f"<td>{_e(case.get('module'))}</td>"
            f"<td>{_e(case.get('name'))}<br><span class='hint'>{_e(','.join(case.get('types') or []))}</span></td>"
            f"<td><span class='tag t-{_e(outcome)}'>{_e(OUTCOME_LABELS.get(outcome, outcome))}</span></td>"
            f"<td>{_e(case.get('duration'))}s</td>"
            f"<td class='msg'>{_e(case.get('message'))}</td>"
            "</tr>"
        )
    types = sorted({name for case in cases for name in (case.get("types") or [])})
    type_options = "".join(f"<option value='{_e(name)}'>{_e(name)}</option>" for name in types)
    return (
        "<section><h2>用例明细</h2>"
        "<div class='filters'>"
        "<input type='search' id='kw' placeholder='搜索用例名 / 模块 / 失败信息' style='min-width:280px' oninput='applyFilter()'>"
        f"<select id='oc' onchange='applyFilter()'><option value='all'>全部结果</option>{options}</select>"
        f"<select id='ty' onchange='applyFilter()'><option value='all'>全部类型</option>{type_options}</select>"
        "<span class='hint'>显示 <b id='cnt'>0</b> 条；点击行可展开说明</span>"
        "</div>"
        "<table id='cases'><thead><tr><th>模块</th><th>用例</th><th>结果</th><th>耗时</th><th>说明（点击展开）</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table></section>"
    )
