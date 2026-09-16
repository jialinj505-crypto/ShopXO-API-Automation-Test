"""pytest 全局夹具与钩子。

职责：
1. 环境初始化 / 销毁：会话开始探测环境能力、记录环境信息；会话结束释放所有连接；
2. 鉴权夹具：token 只登录一次，全程复用（TokenManager 缓存）；
3. 业务夹具：购物车清理、临时地址、临时订单等，保证用例之间互不干扰、残留数据可回收；
4. 能力门控：环境不具备的能力（优惠券插件 / 商家后台）自动跳过并给出明确原因，绝不"假绿"；
5. 结果归档：把每次执行的结构化结果写入 reports/ 并渲染质量看板（见 core/report_plugin.py），
   解决 pytest-html 报告"每次执行都被覆盖、历史结果留不下来"的问题。
"""
import json
import os
import platform
import sys

import pytest

from api_objects import (
    AddressAPI,
    AdminAPI,
    CartAPI,
    CouponAPI,
    GoodsAPI,
    HomeAPI,
    OrderAPI,
    SearchAPI,
    UserAPI,
)
from config.setting import (
    ALLURE_RESULTS_DIR,
    BASE_URL,
    DEFAULT_ADDRESS,
    DEFAULT_GOODS_ID,
    ENV_NAME,
    OFFLINE,
    TEST_DATA_PREFIX,
    USER_ACCOUNTS,
)
from core import env_check, report_plugin
from core.auth import AuthType, TokenManager
from core.data_loader import unique
from core.logger import get_logger

logger = get_logger("shopxo.conftest")

# 会话级 API 对象登记表：会话结束时统一关闭，避免连接泄漏
_API_SESSIONS = []

# ---------------------------------------------------------------------- 插件注册
# 把结果归档插件（core/report_plugin.py）挂到本 conftest：
# 显式赋值这几个钩子，避免依赖 `-p` 的加载时序，同时保证插件实现只有一份。
pytest_addoption = report_plugin.pytest_addoption
pytest_sessionstart = report_plugin.pytest_sessionstart
pytest_runtest_makereport = report_plugin.pytest_runtest_makereport
pytest_sessionfinish = report_plugin.pytest_sessionfinish


# ---------------------------------------------------------------------- 钩子
def pytest_collection_modifyitems(config, items):
    """按环境能力自动跳过用例：@pytest.mark.requires("coupon") 等。

    两种筛选模式：
    1. 离线模式（SHOPXO_OFFLINE=1）：只保留 @pytest.mark.offline 的框架自测用例，
       其余依赖真实环境的用例全部取消选择——CI 的 PR 门禁因此"快、稳、不卡在别人的沙箱上"；
    2. 常规模式：@pytest.mark.requires("coupon") 在能力缺失时自动跳过，并写明真实原因。

    设置环境变量 SHOPXO_FORCE_FEATURES=1 可强制执行被门控的用例，
    用于在能力探测有误或需要验证门控用例本身时排查问题。
    """
    if OFFLINE:
        selected = [item for item in items if item.get_closest_marker("offline")]
        deselected = [item for item in items if not item.get_closest_marker("offline")]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected
        logger.info("[离线模式] 仅执行 %s 条离线用例，取消选择 %s 条依赖真实环境的用例", len(selected), len(deselected))
        return

    capabilities = env_check.probe()
    features = capabilities.get("features", {})
    force = os.environ.get("SHOPXO_FORCE_FEATURES", "").strip().lower() in ("1", "true", "yes", "on")
    for item in items:
        marker = item.get_closest_marker("requires")
        if not marker:
            continue
        name = marker.args[0] if marker.args else marker.kwargs.get("name")
        if not name:
            continue
        if not features.get(name) and not force:
            reason = capabilities.get("details", {}).get(name, "环境能力缺失")
            item.add_marker(pytest.mark.skip(reason=f"环境[{BASE_URL}]不支持能力[{name}]：{reason}"))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """执行结束后打印环境能力矩阵，明确哪些模块被跳过以及为什么。"""
    capabilities = env_check.probe()
    terminalreporter.write_sep("=", "测试环境能力矩阵")
    terminalreporter.write_line(env_check.summary(capabilities))
    for key, value in capabilities.get("details", {}).items():
        terminalreporter.write_line(f"  {key}: {value}")


# ---------------------------------------------------------------------- 环境
def _write_env_files(capabilities: dict) -> None:
    """写入 Allure 环境信息与能力矩阵文件，便于 CI 归档与问题回溯。"""
    try:
        ALLURE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Environment={ENV_NAME}",
            f"Base.URL={BASE_URL}",
            f"Python={sys.version.split()[0]}",
            f"OS={platform.system()} {platform.release()}",
            f"User.Login={capabilities.get('user_login')}",
            f"Coupon.Plugin={capabilities.get('features', {}).get('coupon')}",
            f"Shop.Plugin={capabilities.get('features', {}).get('shop')}",
            f"Merchant.Admin={capabilities.get('features', {}).get('merchant')}",
            f"Probe.Time={capabilities.get('checked_at')}",
        ]
        (ALLURE_RESULTS_DIR / "environment.properties").write_text("\n".join(lines), encoding="utf-8")

        # Allure 缺陷分类：把失败用例按"产品缺陷 / 环境问题 / 用例问题"归类
        categories = [
            {"name": "产品缺陷", "matchedStatuses": ["failed"], "messageRegex": ".*(BUG-[A-Z]+-[A-Z0-9-]+|缺陷).*"},
            {"name": "环境/网络问题", "matchedStatuses": ["failed", "broken"], "messageRegex": ".*(ApiError|Connection|Timeout|不可达).*"},
            {"name": "用例/断言问题", "matchedStatuses": ["failed"], "messageRegex": ".*"},
        ]
        (ALLURE_RESULTS_DIR / "categories.json").write_text(
            json.dumps(categories, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[环境] 环境信息写入失败：%s", exc)


@pytest.fixture(scope="session", autouse=True)
def env_init():
    """会话级环境初始化 / 销毁（离线模式下不探测真实环境）。"""
    capabilities = env_check.probe()
    logger.info("环境能力矩阵：\n%s", env_check.summary(capabilities))
    if not OFFLINE:
        # 离线模式不覆盖真实探测结果文件，避免把"没探测"写成"探测失败"
        _write_env_files(capabilities)
        env_check.dump("reports/env_probe.json")
    if capabilities.get("reachable") is False:
        logger.error("[环境] 被测站点不可达，请检查网络或 SHOPXO_BASE_URL 配置")
    yield capabilities
    for api in _API_SESSIONS:
        api.close()
    logger.info("[环境] 用例执行结束，已释放 %s 个接口会话", len(_API_SESSIONS))


@pytest.fixture(scope="session")
def capabilities(env_init):
    """环境能力矩阵。"""
    return env_init


# ---------------------------------------------------------------------- 鉴权
@pytest.fixture(scope="session")
def token(env_init):
    """登录 token（会话级只登录一次，后续用例复用）。"""
    if not env_init.get("user_login"):
        pytest.skip(f"环境登录不可用：{env_init.get('details', {}).get('user_login')}")
    return TokenManager.get_token(AuthType.USER)


# ---------------------------------------------------------------------- 接口对象
@pytest.fixture(scope="session")
def user_api(env_init):
    api = UserAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def goods_api(env_init):
    api = GoodsAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def search_api(env_init):
    api = SearchAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def home_api(env_init):
    api = HomeAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def cart_api(env_init):
    api = CartAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def order_api(env_init):
    api = OrderAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def address_api(env_init):
    api = AddressAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def coupon_api(env_init):
    """优惠券接口对象（仅在环境安装优惠券插件时才会被用例使用）。"""
    api = CouponAPI()
    _API_SESSIONS.append(api)
    return api


@pytest.fixture(scope="session")
def admin_api(env_init):
    """商家后台接口对象（会话鉴权，仅在后台入口开放时才会被用例使用）。"""
    api = AdminAPI()
    _API_SESSIONS.append(api)
    return api


# ---------------------------------------------------------------------- 数据
@pytest.fixture
def test_name():
    """唯一测试数据名称（时间戳+随机串），避免多人共用测试环境时互相干扰。"""
    return unique(TEST_DATA_PREFIX)


@pytest.fixture
def clean_cart(cart_api, token):
    """购物车用例前置/后置清理，保证用例可重复执行。"""
    removed = cart_api.clear()
    if removed:
        logger.info("[数据清理] 前置清空购物车，移除 %s 条历史数据", removed)
    yield cart_api
    removed = cart_api.clear()
    if removed:
        logger.info("[数据清理] 后置清空购物车，移除 %s 条测试数据", removed)


@pytest.fixture
def temp_address(address_api, token, test_name):
    """创建临时收货地址，用例结束后自动删除（不污染共享测试环境）。"""
    res = address_api.save(
        name=test_name,
        tel=DEFAULT_ADDRESS["tel"],
        address=DEFAULT_ADDRESS["address"],
        province=DEFAULT_ADDRESS["province"],
        city=DEFAULT_ADDRESS["city"],
        county=DEFAULT_ADDRESS["county"],
        alias="AutoTest",
    )
    assert res.get("code") == 0, f"前置创建地址失败：code={res.get('code')} msg={res.get('msg')}"
    record = address_api.find_by_name(test_name)
    assert record, "前置创建地址后未查询到该地址"
    yield {"id": record["id"], "name": test_name, "raw": record}
    try:
        address_api.cleanup_by_name(test_name)
        logger.info("[数据清理] 已删除临时收货地址 %s", record["id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[数据清理] 删除临时地址失败：%s", exc)


@pytest.fixture(scope="session")
def payment_id(order_api, cart_api, token):
    """从订单确认页动态获取可用支付方式（沙箱通常仅"货到付款"）。"""
    cart_api.clear()
    cart_api.add(DEFAULT_GOODS_ID, 1)
    item = cart_api.find_item(DEFAULT_GOODS_ID)
    res = order_api.confirm(item["id"], address_id=0) if item else {}
    cart_api.clear()
    payments = ((res.get("data") or {}).get("payment_list")) or []
    value = payments[0]["id"] if payments else 3
    logger.info("[环境] 使用支付方式 payment_id=%s", value)
    return value


@pytest.fixture
def temp_order(order_api, cart_api, temp_address, payment_id, token):
    """创建一笔待付款订单，用例结束后自动取消 + 删除，并清空购物车。"""
    cart_api.clear()
    assert cart_api.add(DEFAULT_GOODS_ID, 1).get("code") == 0, "前置加购失败"
    item = cart_api.find_item(DEFAULT_GOODS_ID)
    assert item, "前置加购后未查询到购物车记录"
    res = order_api.submit(item["id"], address_id=temp_address["id"], payment_id=payment_id)
    order_id = ((res.get("data") or {}).get("order_ids") or [None])[0] if res.get("code") == 0 else None
    assert order_id, f"前置提交订单失败：code={res.get('code')} msg={res.get('msg')}"
    logger.info("[测试数据] 已创建待付款订单 %s", order_id)

    yield {"id": order_id, "payment_id": payment_id, "goods_id": DEFAULT_GOODS_ID, "address_id": temp_address["id"]}

    try:
        detail = order_api.detail(order_id)
        status, _ = OrderAPI.status_of(detail)
        if str(status) in ("1", "2"):  # 待付款 / 待发货 -> 先取消再删除
            order_api.cancel(order_id)
        res = order_api.delete(order_id)
        logger.info("[数据清理] 订单 %s 清理结果：code=%s msg=%s", order_id, res.get("code"), res.get("msg"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[数据清理] 订单 %s 清理失败：%s", order_id, exc)
    finally:
        cart_api.clear()


@pytest.fixture(scope="session")
def spec_goods(search_api):
    """动态挑选一个多规格商品，避免商品数据变化导致用例失效。"""
    res = search_api.search(wd=None, page=1)
    items = ((res.get("data") or {}).get("data")) or []
    for item in items:
        if str(item.get("is_exist_many_spec", "0")) == "1":
            logger.info("[环境] 选中多规格商品 id=%s title=%s", item.get("id"), item.get("title"))
            return item
    pytest.skip("当前环境搜索结果中没有多规格商品，跳过规格相关用例")


@pytest.fixture
def account():
    """默认测试账号（可通过环境变量注入，避免把账号写死在用例里）。"""
    return dict(USER_ACCOUNTS["default"])
