"""登录凭证预检工具。

用途：跑测试前确认被测环境的测试账号是否可用。
公开沙箱（如 shop-xo.hctestedu.com）的账号可能被他人改密码或被整体重置，
此时不是框架/用例的问题，而是环境凭证问题——本工具用于快速区分这两种情况。

用法：
    python tools/check_login.py                          # 检查 config 中的默认账号
    python tools/check_login.py -u 账号 -p 密码            # 检查指定账号
    python tools/check_login.py --try 123456,huace123456  # 依次尝试候选密码

退出码：0 = 可登录；1 = 不可登录
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_objects.user_api import UserAPI  # noqa: E402
from config.setting import BASE_URL, USER_ACCOUNTS  # noqa: E402


def check(accounts: str, pwd: str, label: str = ""):
    """调用登录接口并打印结果。"""
    res = UserAPI().login(accounts, pwd)
    code, msg = res.get("code"), res.get("msg")
    ok = code == 0
    print(f"[{'通过' if ok else '失败'}] {label}账号={accounts} -> code={code} msg={msg}")
    return ok, res


def main() -> int:
    parser = argparse.ArgumentParser(description="登录凭证预检")
    parser.add_argument("-u", "--user", help="账号（默认取 config 中的测试账号）")
    parser.add_argument("-p", "--pwd", help="密码（默认取 config 中的测试账号）")
    parser.add_argument("--try", dest="candidates", help="候选密码，逗号分隔，依次尝试")
    args = parser.parse_args()

    default = USER_ACCOUNTS["default"]
    accounts = args.user or default["accounts"]
    pwd = args.pwd or default["pwd"]

    print(f"被测环境: {BASE_URL}")
    print(f"接口文档默认账号: {default['accounts']}")
    ok, res = check(accounts, pwd)

    if not ok:
        print("原始响应: " + json.dumps(res, ensure_ascii=False)[:300])

    if not ok and args.candidates:
        print("\n尝试候选密码（连续失败可能触发风控，请谨慎使用）...")
        for cand in [c.strip() for c in args.candidates.split(",") if c.strip()]:
            good, _ = check(accounts, cand, label="候选密码 ")
            if good:
                print(f"\n可用密码: {cand}")
                print(f"请先设置环境变量再跑测试：$env:SHOPXO_USER='{accounts}'; $env:SHOPXO_PWD='{cand}'")
                return 0

    if not ok:
        print("\n结论：当前账号无法登录（大概率是公开沙箱被重置或密码被他人修改，不是用例问题）。")
        print("处理建议：")
        print("  1) 拿到可用账号后设置环境变量：$env:SHOPXO_USER='账号'; $env:SHOPXO_PWD='密码'")
        print("  2) 先跑不依赖登录的用例：python run.py -m smoke")
        print("  3) 再跑全量：python run.py   （登录类用例仍会失败，依赖登录的用例会明确跳过并写明原因）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
