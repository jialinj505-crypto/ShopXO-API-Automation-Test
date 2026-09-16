"""测试环境能力探测。

背景：同一个自动化框架要跑在不同环境上（沙箱 / 预发 / 多商户环境），
不同环境安装的插件、开放的后台入口并不一致。与其让用例"假绿"或大面积报错，
不如先探测环境能力，再决定哪些模块可以执行、哪些按明确原因跳过。

探测结果用于：
1. `@pytest.mark.requires("coupon")` 标记的用例在能力缺失时自动 skip（含原因）；
2. Allure 报告中记录本次执行环境的能力矩阵，便于回溯"为什么没跑"。
"""
import json
from datetime import datetime
from enum import Enum

import requests

from config.setting import (
    ADMIN_PREFIX,
    API_PREFIX,
    BASE_URL,
    COMMON_PARAMS,
    COUPON_PLUGIN_NAME,
    OFFLINE,
    REQUEST_TIMEOUT,
    SHOP_PLUGIN_NAME,
    USER_ACCOUNTS,
)
from core.logger import get_logger

logger = get_logger("shopxo.env")

_CACHE = {}


class Feature(str, Enum):
    """需要环境具备的能力（缺少时相关模块自动跳过）。"""

    COUPON = "coupon"       # 优惠券插件
    SHOP = "shop"           # 多商户/店铺插件
    MERCHANT = "merchant"   # 商家后台入口


def _request(method: str, path: str, data=None, token=None, timeout: int = None) -> dict:
    """轻量探测请求（不经过 BaseAPI，避免探测失败影响框架自身日志/断言）。"""
    payload = dict(data or {})
    payload.update(COMMON_PARAMS)
    if token:
        payload["token"] = token
    response = requests.request(
        method, f"{BASE_URL}/{path.lstrip('/')}", data=payload, timeout=timeout or REQUEST_TIMEOUT
    )
    try:
        body = response.json()
        body["_http_status"] = response.status_code
        return body
    except ValueError:
        return {"code": None, "msg": "非 JSON 响应", "data": None, "_http_status": response.status_code, "_text": response.text[:300]}


def _check_plugin(name: str) -> tuple:
    """探测插件是否安装，返回 (是否可用, 原因)。

    三种情况必须区分开，**不能让"探测不出来"变成"能力可用"**：
    - `code=-10` 或 msg 含"未安装" → 明确未安装（相关用例按原因跳过）；
    - 请求异常 / 非 JSON 响应（被 WAF 或登录页拦截）/ 非 0 业务码 → 探测失败（不确定），
      同样不认为能力可用，原因里带上异常原文与 HTTP 状态，便于判断是超时、连接被拒还是被拦截；
    - `code=0` → 能力可用。
    """
    try:
        res = _request("POST", f"{API_PREFIX}plugins/index",
                       {"pluginsname": name, "pluginscontrol": "index", "pluginsaction": "index"})
        code = res.get("code")
        message = str(res.get("msg", ""))
        if code == -10 or "未安装" in message:
            return False, message or f"code={code}"
        if code is None:
            return False, f"探测失败（非 JSON 响应，HTTP {res.get('_http_status')}）：{message}"
        if code != 0:
            return False, f"探测失败（code={code} msg={message}）"
        return True, message or "code=0"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[环境] 插件[%s]探测异常：%s: %s", name, type(exc).__name__, exc)
        return False, f"探测异常：{type(exc).__name__}: {exc}"


def _check_admin() -> tuple:
    """探测商家后台入口是否可用（沙箱环境后台常被禁用，返回 非法访问）。"""
    try:
        response = requests.get(f"{BASE_URL}{ADMIN_PREFIX}login/index", timeout=REQUEST_TIMEOUT)
        text = response.text or ""
        if "非法访问" in text or "无权限" in text:
            return False, "后台入口被禁用（返回：非法访问）"
        if response.status_code >= 500:
            return False, f"后台服务异常 HTTP {response.status_code}"
        if any(key in text for key in ("密码", "登录", "password", "pwd")):
            return True, "后台登录页可访问"
        return False, f"后台返回内容无法识别（{len(text)} 字节）"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[环境] 商家后台探测异常：%s: %s", type(exc).__name__, exc)
        return False, f"探测异常：{type(exc).__name__}: {exc}"


def offline_result() -> dict:
    """离线模式的能力矩阵占位值（**不发起任何网络请求**）。"""
    return {
        "base_url": BASE_URL,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "offline": True,
        "reachable": None,
        "user_login": None,
        "features": {Feature.COUPON.value: False, Feature.SHOP.value: False, Feature.MERCHANT.value: False},
        "details": {"mode": "离线模式（SHOPXO_OFFLINE=1）：未探测真实环境，仅执行不依赖环境的框架自测用例"},
    }


def probe(force: bool = False) -> dict:
    """探测并缓存当前环境能力（离线模式直接返回占位值，不发请求）。"""
    if OFFLINE:
        _CACHE.clear()
        _CACHE.update(offline_result())
        return _CACHE
    if _CACHE and not force:
        return _CACHE

    result = {
        "base_url": BASE_URL,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reachable": False,
        "user_login": False,
        "features": {Feature.COUPON.value: False, Feature.SHOP.value: False, Feature.MERCHANT.value: False},
        "details": {},
    }
    try:
        response = requests.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        result["reachable"] = response.status_code < 500
        result["details"]["site"] = f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        result["details"]["site"] = f"不可达：{type(exc).__name__}"
        logger.error("[环境] 被测站点不可达：%s", exc)
        _CACHE.update(result)
        return result

    token = None
    account = USER_ACCOUNTS["default"]
    try:
        res = _request("POST", f"{API_PREFIX}user/login", dict(account))
        result["user_login"] = res.get("code") == 0
        result["details"]["user_login"] = f"code={res.get('code')} msg={res.get('msg')}"
        token = (res.get("data") or {}).get("token") if result["user_login"] else None
    except Exception as exc:  # noqa: BLE001
        result["details"]["user_login"] = f"探测异常：{type(exc).__name__}"

    # 关键路由可用性（决定对应用例是否需要跳过）
    route_probes = {
        "search": ("POST", f"{API_PREFIX}search/index", {"wd": "iphone", "page": 1}, False),
        "goods_detail": ("POST", f"{API_PREFIX}goods/detail", {"goods_id": 12}, False),
        "cart": ("POST", f"{API_PREFIX}cart/index", {}, True),
        "order": ("POST", f"{API_PREFIX}order/index", {"page": 1}, True),
        "address": ("POST", f"{API_PREFIX}useraddress/index", {}, True),
        "message": ("POST", f"{API_PREFIX}message/index", {}, True),
        "region": ("POST", f"{API_PREFIX}region/index", {"pid": 0}, False),
    }
    for name, (method, path, data, need_token) in route_probes.items():
        if need_token and not token:
            result["details"][f"route:{name}"] = "缺少 token，未探测"
            continue
        try:
            res = _request(method, path, data, token)
            ok = res.get("code") == 0
            result["details"][f"route:{name}"] = f"code={res.get('code')} msg={res.get('msg')}"
            result.setdefault("routes", {})[name] = ok
        except Exception as exc:  # noqa: BLE001
            result["details"][f"route:{name}"] = f"探测异常：{type(exc).__name__}"
            result.setdefault("routes", {})[name] = False

    # 插件与后台能力
    coupon_ok, coupon_msg = _check_plugin(COUPON_PLUGIN_NAME)
    shop_ok, shop_msg = _check_plugin(SHOP_PLUGIN_NAME)
    admin_ok, admin_msg = _check_admin()
    result["features"][Feature.COUPON.value] = coupon_ok
    result["features"][Feature.SHOP.value] = shop_ok
    result["features"][Feature.MERCHANT.value] = admin_ok
    result["details"]["coupon"] = coupon_msg
    result["details"]["shop"] = shop_msg
    result["details"]["merchant"] = admin_msg

    logger.info(
        "[环境] %s 可达=%s 登录=%s 优惠券插件=%s 商家后台=%s",
        result["base_url"], result["reachable"], result["user_login"], coupon_ok, admin_ok,
    )
    _CACHE.clear()
    _CACHE.update(result)
    return result


def capability(name: str) -> bool:
    """查询某项能力是否可用。"""
    return bool(probe().get("features", {}).get(name))


def summary(data: dict = None) -> str:
    """生成可读的能力矩阵（写入 Allure 环境信息与日志）。"""
    data = data or probe()
    if data.get("offline"):
        return f"离线模式：未探测真实环境（配置的被测环境：{data.get('base_url')}）"
    lines = [
        f"被测环境: {data.get('base_url')}",
        f"环境可达: {data.get('reachable')}",
        f"用户登录: {data.get('user_login')}",
        f"优惠券插件: {data.get('features', {}).get('coupon')}",
        f"多商户插件: {data.get('features', {}).get('shop')}",
        f"商家后台: {data.get('features', {}).get('merchant')}",
    ]
    return "\n".join(lines)


def dump(path) -> None:
    """把探测结果落盘，便于 CI 归档与问题回溯。"""
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(probe(), fp, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[环境] 能力矩阵落盘失败：%s", exc)
