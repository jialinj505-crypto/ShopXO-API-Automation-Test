"""统一执行入口：本地调试与 Jenkins 流水线共用同一套参数。

用法示例：
    python run.py                          # 全量回归（HTML 报告 + Allure 原始结果 + 质量看板）
    python run.py -m smoke                 # 只跑冒烟用例
    python run.py -m "p0 and not e2e"      # 只跑 P0 单接口用例
    python run.py -n 4                     # 4 进程并行（pytest-xdist）
    python run.py --marker regression --rerun 1   # 失败重跑 1 次（pytest-rerunfailures）
    python run.py --base-url http://127.0.0.1     # 指定被测环境
    python run.py --tag 发版前回归           # 给本次执行打标签（趋势图上可区分）
    python run.py --open                   # 执行结束后自动打开质量看板
    python run.py --allure-report          # 额外生成 Allure HTML 报告（需安装 allure 命令行）

每次执行的结果都会按运行编号归档，**历史结果不会被覆盖**：

    reports/dashboard.html                  最新质量看板（自包含，可离线打开）
    reports/summary.json                    最新结构化结果（看板数据源）
    reports/report.html                     最新 pytest-html 报告（Jenkins 归档用）
    reports/history/<run_id>/               本次执行快照：report.html + summary.json + dashboard.html
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
HISTORY_DIR = REPORT_DIR / "history"
ALLURE_RESULTS = REPORT_DIR / "allure-results"
ALLURE_REPORT = REPORT_DIR / "allure-report"
HTML_REPORT = REPORT_DIR / "report.html"
SUMMARY_FILE = REPORT_DIR / "summary.json"
DASHBOARD = REPORT_DIR / "dashboard.html"


def module_available(name: str) -> bool:
    """判断依赖是否安装（未安装的能力自动降级，不阻断用例执行）。"""
    return importlib.util.find_spec(name) is not None


def build_pytest_args(args, run_id: str) -> list:
    cmd = [sys.executable, "-m", "pytest"]

    if args.marker:
        cmd += ["-m", args.marker]
    elif args.offline:
        cmd += ["-m", "offline"]
    if args.keyword:
        cmd += ["-k", args.keyword]
    if args.workers and args.workers > 1:
        cmd += ["-n", str(args.workers)]

    # Allure：装了 allure-pytest 就产出原始结果，可用 allure 命令行生成 HTML
    if module_available("allure_pytest") and not args.no_allure:
        cmd += [f"--alluredir={ALLURE_RESULTS}", "--clean-alluredir"]
    # HTML 报告：pytest-html
    if module_available("pytest_html") and not args.no_html:
        cmd += [f"--html={HTML_REPORT}", "--self-contained-html"]
    # 失败重跑：仅对幂等接口有意义，因此默认关闭
    if args.rerun:
        cmd += ["--reruns", str(args.rerun), "--reruns-delay", "2"]

    # 结果归档与看板（core/report_plugin.py）：运行编号决定 history/ 下的归档目录，历史不被覆盖
    cmd += ["--run-id", run_id, "--history-keep", str(args.history_keep)]
    if args.tag:
        cmd += ["--run-tag", args.tag]
    if args.no_dashboard:
        cmd += ["--no-dashboard"]

    cmd += args.extra
    return cmd


def archive_html_report(run_id: str) -> Path:
    """把本次 pytest-html 报告复制进 history/<run_id>/，避免被下一次执行覆盖。"""
    run_dir = HISTORY_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if HTML_REPORT.exists():
        shutil.copy2(HTML_REPORT, run_dir / "report.html")
    return run_dir


def print_summary(run_id: str) -> None:
    """读取结构化结果，在控制台给出一行式结论。"""
    if not SUMMARY_FILE.exists():
        return
    try:
        summary = json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    totals = summary.get("totals", {})
    print(
        "本次结果 : "
        f"总数 {totals.get('total', 0)} | 通过 {totals.get('passed', 0)} | 失败 {totals.get('failed', 0)} | "
        f"错误 {totals.get('error', 0)} | 跳过 {totals.get('skipped', 0)} | 缺陷守护 {totals.get('xfailed', 0)} | "
        f"通过率 {totals.get('pass_rate', 0)}%（可执行通过率 {totals.get('executed_pass_rate', 0)}%）"
    )
    print(f"运行编号 : {run_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ShopXO 接口自动化测试统一入口")
    parser.add_argument("-m", "--marker", default=os.environ.get("PYTEST_MARKER", ""), help="pytest 标记表达式")
    parser.add_argument("-k", "--keyword", default="", help="按用例名关键字筛选")
    parser.add_argument("-n", "--workers", type=int, default=0, help="并行进程数（>1 时启用 xdist）")
    parser.add_argument("--rerun", type=int, default=0, help="失败用例重跑次数")
    parser.add_argument("--base-url", default="", help="被测环境地址（等价于 SHOPXO_BASE_URL）")
    parser.add_argument("--env", default="", help="环境标识，如 test/staging（等价于 SHOPXO_ENV）")
    parser.add_argument("--tag", default="", help="本次执行标签（趋势图上可区分，如 smoke/发版前回归）")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="离线模式：只跑不依赖真实环境的框架自测用例（tests/unit 等），0 网络依赖、秒级完成",
    )
    parser.add_argument("--history-keep", type=int, default=50, help="历史结果保留次数（默认 50）")
    parser.add_argument("--no-html", action="store_true", help="不生成 pytest-html 报告")
    parser.add_argument("--no-allure", action="store_true", help="不产出 Allure 原始结果")
    parser.add_argument("--no-dashboard", action="store_true", help="不生成质量看板")
    parser.add_argument("--open", action="store_true", help="执行结束后自动打开质量看板")
    parser.add_argument("--allure-report", action="store_true", help="额外调用 allure 命令生成 HTML 报告")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="透传给 pytest 的其他参数")
    args = parser.parse_args()

    if args.base_url:
        os.environ["SHOPXO_BASE_URL"] = args.base_url
    if args.env:
        os.environ["SHOPXO_ENV"] = args.env
    if args.offline:
        os.environ["SHOPXO_OFFLINE"] = "1"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    # 未显式指定标签时，用执行范围作为标签，趋势图上能区分"全量/冒烟/离线"等不同范围
    args.tag = args.tag or ("offline" if args.offline else (args.marker or "全量"))
    cmd = build_pytest_args(args, run_id)

    print("=" * 78)
    print("ShopXO 接口自动化测试" + ("（离线模式：不访问真实环境）" if args.offline else ""))
    print(f"被测环境 : {os.environ.get('SHOPXO_BASE_URL', 'http://shop-xo.hctestedu.com')}")
    print(f"运行编号 : {run_id}{'（标签：' + args.tag + '）' if args.tag else ''}")
    print(f"执行命令 : {' '.join(str(c) for c in cmd)}")
    print("=" * 78, flush=True)

    # 直接透传子进程输出，Jenkins 控制台可实时看到执行进度
    result = subprocess.run(cmd, cwd=str(ROOT))

    # 归档本次 HTML 报告（结果为结构化归档由插件在会话结束时写入）
    run_dir = archive_html_report(run_id)

    if args.allure_report:
        allure_cli = shutil.which("allure")
        if not allure_cli:
            print("[警告] 未找到 allure 命令行，跳过 HTML 报告生成（原始结果已保留在 reports/allure-results）")
        elif ALLURE_RESULTS.exists():
            subprocess.run([allure_cli, "generate", str(ALLURE_RESULTS), "-o", str(ALLURE_REPORT), "--clean"], cwd=str(ROOT))

    print()
    print_summary(run_id)
    print(f"归档目录 : {run_dir.relative_to(ROOT)}（history/<运行编号>/，历史结果不会被覆盖）")
    if not args.no_dashboard and DASHBOARD.exists():
        print(f"质量看板 : {DASHBOARD.relative_to(ROOT)}")
    print(f"执行结束，退出码={result.returncode}")

    if args.open and DASHBOARD.exists():
        webbrowser.open(DASHBOARD.as_uri())
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
