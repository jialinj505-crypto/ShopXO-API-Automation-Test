"""把结果汇总转成 Markdown 摘要，用于 CI 构建页面（GitHub Actions Step Summary / Jenkins / 企业微信）。

用法：
    python tools/ci_summary.py                        # 打印到控制台
    python tools/ci_summary.py --output ci-summary.md # 写入文件
    python tools/ci_summary.py >> "$GITHUB_STEP_SUMMARY"   # GitHub Actions 构建摘要

设计说明：把"结果转摘要"做成独立脚本而不是写在流水线内联脚本里，
好处是本地可运行、可单测、Jenkins 与 GitHub Actions 共用同一份实现。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_FILE = ROOT / "reports" / "summary.json"


def render(summary: dict) -> str:
    """把结构化结果渲染成 Markdown 摘要（只读 summary.json，不重新解析文本报告）。"""
    run = summary.get("run") or {}
    totals = summary.get("totals") or {}
    lines = [
        f"### 质量看板 · 运行编号 {run.get('id')}（标签 {run.get('tag') or '无'}）",
        "",
        f"- 用例总数：{totals.get('total', 0)}（环境：{(summary.get('environment') or {}).get('base_url')}）",
        f"- 通过 {totals.get('passed', 0)}｜失败 {totals.get('failed', 0)}｜错误 {totals.get('error', 0)}"
        f"｜跳过 {totals.get('skipped', 0)}｜缺陷守护 {totals.get('xfailed', 0)}",
        f"- 通过率 {totals.get('pass_rate', 0)}%｜可执行通过率 {totals.get('executed_pass_rate', 0)}%",
        f"- 耗时 {run.get('duration', 0)}s",
    ]
    defects = summary.get("defects") or []
    if defects:
        open_defects = [item for item in defects if item.get("status") != "fixed"]
        lines.append(
            f"- 已登记缺陷 {len(defects)} 个（仍存在 {len(open_defects)} 个）："
            + "、".join(item.get("id", "") for item in defects)
        )
    lines += ["", "详细看板与历史归档见本次构建的 Artifacts。"]

    if int(totals.get("failed", 0)) + int(totals.get("error", 0)) > 0:
        lines.append("")
        lines.append("> ⚠️ 本次存在失败/错误用例，请查看看板「失败与跳过诊断」分区定位。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 CI 构建页面的 Markdown 结果摘要")
    parser.add_argument("--summary", default=str(SUMMARY_FILE), help="结果汇总文件路径")
    parser.add_argument("--output", default="", help="输出文件路径（默认打印到控制台）")
    args = parser.parse_args()

    path = Path(args.summary)
    if not path.exists():
        print(f"未找到结果汇总文件：{path}（可能本次未执行测试）")
        return 0
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"读取结果汇总失败：{type(exc).__name__}: {exc}")
        return 0

    text = render(summary)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
