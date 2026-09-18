"""Allure 命令行安装脚本：把官方 allure-commandline 装到项目内 .tools/，不污染系统 PATH。

为什么需要它：`allure-pytest` 只是 Python 插件，负责产出原始结果（`reports/allure-results`）；
要把原始结果渲染成 HTML 报告，必须再有官方 **allure 命令行**（依赖 Java 8+）。
本项目把 Allure 当"可选增强"，装在 `.tools/` 下由 `run.py` 自动识别
（查找顺序：`ALLURE_HOME` → `.tools/allure-*` → 系统 PATH），没装也不影响用例执行。

用法：
    python tools/get_allure.py                     # 安装最新版
    python tools/get_allure.py --version 2.46.1    # 安装指定版本
    python tools/get_allure.py --force             # 已安装也重新下载
    python tools/get_allure.py --check             # 只检查当前是否可用，不下载

实现要点（都是实际踩到的）：
1. 部分受限网络访问 github.com 会超时，但 api.github.com 可达——因此优先用
   「release 资产 API + Accept: application/octet-stream」下载，失败再回退到浏览器下载地址；
2. 下载后按 release API 公布的 sha256 digest 校验，避免拿到损坏或被篡改的包；
3. 解压后立刻执行 `allure --version` 自检，Java 不满足时给出明确提示，而不是等到跑报告才报错。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / ".tools"
API = "https://api.github.com/repos/allure-framework/allure2/releases"
UA = {"User-Agent": "shopxo-api-autotest-get-allure"}


def api_get(url: str, timeout: int = 20) -> dict:
    """访问 GitHub API，并把网络/HTTP 异常转换成可读提示（工具不该抛裸 traceback）。"""
    try:
        resp = requests.get(url, headers={**UA, "Accept": "application/vnd.github+json"}, timeout=timeout)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "未知"
        if status == 404:
            raise SystemExit(f"GitHub 上找不到该资源（HTTP 404）：{url}\n       请确认版本号是否存在，例如 --version 2.46.1")
        raise SystemExit(f"访问 GitHub API 失败（HTTP {status}）：{url}")
    except requests.RequestException as exc:
        raise SystemExit(
            f"访问 GitHub API 失败：{type(exc).__name__}: {exc}\n"
            "       若处于受限网络，可手动下载 allure-commandline 解压到项目 .tools/ 目录，或设置 ALLURE_HOME 指向它"
        )
    return resp.json()


def resolve_asset(version: str) -> dict:
    """取指定版本的 zip 资产信息：API 地址、浏览器下载地址、大小与 sha256。"""
    release = api_get(f"{API}/tags/{version}")
    for asset in release.get("assets", []):
        if asset.get("name") == f"allure-{version}.zip":
            digest = asset.get("digest") or ""
            return {
                "api_url": asset["url"],  # 受限网络下这条通道可用（走 release-assets CDN）
                "browser_url": asset["browser_download_url"],
                "size": asset.get("size"),
                "sha256": digest.split(":", 1)[-1] if digest.startswith("sha256:") else "",
            }
    raise SystemExit(f"未在 release {version} 中找到 allure-{version}.zip")


def latest_version() -> str:
    return api_get(f"{API}/latest")["tag_name"].lstrip("v")


def download(dest: Path, asset: dict) -> None:
    """下载 zip：先 API 通道，失败回退浏览器地址；流式写入并校验大小与 sha256。"""
    attempts = [
        ("API 资产通道", asset["api_url"], {**UA, "Accept": "application/octet-stream"}),
        ("浏览器下载地址", asset["browser_url"], dict(UA)),
    ]
    last_error = None
    for label, url, headers in attempts:
        try:
            print(f"    下载方式：{label}")
            with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                written = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
                        written += len(chunk)
            print(f"    已下载 {written:,} 字节")
            break
        except Exception as exc:  # noqa: BLE001 - 逐个通道回退
            last_error = exc
            print(f"    失败（{type(exc).__name__}: {str(exc)[:80]}），尝试下一个通道")
    else:
        raise SystemExit(f"下载失败：{last_error}")

    if asset.get("size") and dest.stat().st_size != asset["size"]:
        raise SystemExit(f"大小校验失败：{dest.stat().st_size} != {asset['size']}")
    if asset.get("sha256"):
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest != asset["sha256"]:
            raise SystemExit(f"sha256 校验失败：\n  实际 {digest}\n  期望 {asset['sha256']}")
        print("    sha256 校验：通过")
    else:
        print("    sha256 校验：跳过（该 release 未公布 digest）")


def cli_path(version: str) -> Path:
    exe = "allure.bat" if os.name == "nt" else "allure"
    return TOOLS_DIR / f"allure-{version}" / "bin" / exe


def self_check(path: Path) -> bool:
    """执行 `allure --version` 自检（同时验证 Java 是否满足要求）。

    输出重定向到临时文件而不是用管道捕获：部分受限/沙箱环境禁止创建管道（WinError 5 拒绝访问），
    重定向到文件在受限环境下同样可用，因此这个自检在任何环境都能跑。
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "version.txt"
        try:
            with open(out_file, "w+", encoding="utf-8", errors="replace") as fh:
                result = subprocess.run(
                    [str(path), "--version"], stdout=fh, stderr=subprocess.STDOUT, timeout=120, check=False
                )
        except Exception as exc:  # noqa: BLE001
            print(f"    ❌ 无法执行：{type(exc).__name__}: {exc}")
            return False
        text = out_file.read_text(encoding="utf-8", errors="replace").strip()

    if result.returncode != 0:
        print(f"    ❌ 执行失败（退出码 {result.returncode}）：{text[:300]}")
        print("       多为 Java 版本问题：Allure 需要 Java 8+，请检查 `java -version` 与 JAVA_HOME。")
        return False
    print(f"    ✅ allure 版本：{text}（Java 环境满足要求）")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 Allure 命令行到项目内 .tools/")
    parser.add_argument("--version", default="", help="指定版本，如 2.46.1；默认取最新版")
    parser.add_argument("--force", action="store_true", help="已安装也重新下载")
    parser.add_argument("--check", action="store_true", help="只检查是否可用，不下载")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from run import find_allure  # noqa: PLC0415 - 复用 run.py 的三级查找，避免两处逻辑不一致

    if args.check:
        found = find_allure()
        print(f"allure 命令行：{found or '未找到'}")
        if not found:
            return 1
        # 注意：必须返回 int，直接 return self_check(...) 会因 sys.exit(True) 变成退出码 1
        return 0 if self_check(Path(found)) else 1

    version = args.version or latest_version()
    target = cli_path(version)
    print(f"目标位置：{target}")

    if target.exists() and not args.force:
        print(f"已存在 allure {version}，跳过下载（如需重装加 --force）")
        return 0 if self_check(target) else 1

    asset = resolve_asset(version)
    TOOLS_DIR.mkdir(exist_ok=True)
    zip_path = TOOLS_DIR / f"allure-{version}.zip"
    print(f"开始安装 allure {version}（约 {(asset.get('size') or 0) / 1048576:.1f} MB）")
    download(zip_path, asset)

    print(f"    解压到：{TOOLS_DIR}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(TOOLS_DIR)
    zip_path.unlink(missing_ok=True)

    if not target.exists():
        raise SystemExit(f"解压后未找到命令行：{target}")
    if os.name != "nt":
        # zipfile.extractall 不保留 zip 内的可执行权限，Linux/macOS 上必须补执行位，否则自检会 Permission denied
        target.chmod(0o755)
    print("    自检：")
    ok = self_check(target)
    if ok:
        print("\n安装完成。生成 HTML 报告：")
        print("    .\\.venv\\Scripts\\python.exe run.py --allure-report        # 跑完自动渲染")
        print("    allure serve reports\\allure-results                     # 或临时起服务直接看")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
