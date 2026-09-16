"""配置层：环境、域名、超时重试、账号、目录等全局配置。

所有可变量都支持通过环境变量覆盖，避免把环境相关或敏感信息写死在代码里，
便于在本地、Jenkins 流水线、不同测试环境之间切换。
"""
import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SCHEMA_DIR = DATA_DIR / "schemas"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"
ALLURE_RESULTS_DIR = REPORT_DIR / "allure-results"
ALLURE_REPORT_DIR = REPORT_DIR / "allure-report"
HTML_REPORT = REPORT_DIR / "report.html"
LOG_FILE = LOG_DIR / "autotest.log"

for _d in (LOG_DIR, REPORT_DIR, ALLURE_RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def env(key: str, default):
    """读取环境变量并做类型转换（int/float/bool 自动识别）。"""
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


# ---------------------------------------------------------------- 被测环境
ENV_NAME = env("SHOPXO_ENV", "test")
BASE_URL = env("SHOPXO_BASE_URL", "http://shop-xo.hctestedu.com")

# 前台 App 接口前缀 和 商家后台接口前缀（文档中给出的两个入口）
API_PREFIX = "/index.php?s=/api/"
ADMIN_PREFIX = "/admin.php?s=/admin/"
WEB_PREFIX = "/index.php?s=/"

# 文档规定的公共参数：每次请求都会自动注入
COMMON_PARAMS = {
    "application": env("SHOPXO_APPLICATION", "app"),
    "application_client_type": env("SHOPXO_CLIENT_TYPE", "weixin"),
}

# ---------------------------------------------------------------- 请求策略
REQUEST_TIMEOUT = env("SHOPXO_TIMEOUT", 15)
# 幂等接口失败重试次数（0 表示不重试）；非幂等接口（下单/支付等）强制不重试
RETRY_TIMES = env("SHOPXO_RETRY_TIMES", 2)
RETRY_INTERVAL = env("SHOPXO_RETRY_INTERVAL", 0.5)
RETRY_BACKOFF = env("SHOPXO_RETRY_BACKOFF", 2.0)
# 触发重试的 HTTP 状态码 / 业务码 / 网络异常
RETRY_STATUS_CODES = (500, 502, 503, 504)
_retry_biz = env("SHOPXO_RETRY_BIZ_CODES", "")
RETRY_BIZ_CODES = (
    tuple(int(code) for code in _retry_biz.split(",") if code.strip()) if _retry_biz else (-500,)
)

# ---------------------------------------------------------------- 测试账号
# 说明：账号来自《华测商城-接口文档》公开的沙箱测试账号。
# 注意：公开沙箱的密码可能被他人修改或被整体重置（实测文档里的初始密码已失效），
#      跑测试前建议先执行 `python tools/check_login.py` 自检；
#      可用 SHOPXO_USER / SHOPXO_PWD 覆盖，真实项目请在 Jenkins 凭据中注入，不要提交到仓库。
USER_ACCOUNTS = {
    "default": {
        "accounts": env("SHOPXO_USER", "huace_tester"),
        "pwd": env("SHOPXO_PWD", "123456"),
        "type": "username",
    },
    "wrong_pwd": {"accounts": env("SHOPXO_USER", "huace_tester"), "pwd": "wrong_pwd_123", "type": "username"},
    "not_exist": {"accounts": "not_exist_user_zzz", "pwd": "123456", "type": "username"},
}

ADMIN_ACCOUNT = {
    "accounts": env("SHOPXO_ADMIN_USER", "admin"),
    "pwd": env("SHOPXO_ADMIN_PWD", "admin123"),
}

# ---------------------------------------------------------------- 业务默认数据
DEFAULT_ADDRESS = {
    "name": "自动化测试",
    "tel": "13800138000",
    "address": "自动化测试专用地址-请在用例结束后清理",
    "province": 9,
    "city": 152,
    "county": 1896,
}

# 稳定的在售商品（沙箱环境 12 号为单规格商品；多规格商品在用例里动态搜索选取）
DEFAULT_GOODS_ID = env("SHOPXO_GOODS_ID", 12)

# 优惠券 / 商家后台能力相关（这两个模块在沙箱环境不可用时用例会自动跳过）
COUPON_PLUGIN_NAME = env("SHOPXO_COUPON_PLUGIN", "coupon")
SHOP_PLUGIN_NAME = env("SHOPXO_SHOP_PLUGIN", "shop")

# 每个用例创建的测试数据统一使用该前缀，便于识别与清理
TEST_DATA_PREFIX = env("SHOPXO_DATA_PREFIX", "AutoTest")

# ---------------------------------------------------------------- 离线模式
# SHOPXO_OFFLINE=1：不访问真实环境，只执行不依赖环境的框架自测用例（tests/unit、报告工具自测）。
# 用途：CI 的 PR 门禁要"快、稳、不卡在别人的沙箱上"——离线用例 0 网络依赖，
#      真实环境回归交给定时任务执行（见 .github/workflows/api-test.yml）。
OFFLINE = env("SHOPXO_OFFLINE", False)
