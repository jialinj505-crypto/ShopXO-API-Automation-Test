"""统一 Token 鉴权封装。

解决问题：
1. 接口调用方不再手写 token —— `api_objects` 只声明 auth 类型，token 由框架注入；
2. 一次登录、全程复用 —— token 在进程内缓存，避免每个用例重复登录；
3. 失效自动恢复 —— 业务码 -400（登录失效）时由 BaseAPI 自动失效并重新登录；
4. 线程安全 —— 并发(xdist/多线程)场景下不会重复登录或拿到脏 token。
"""
from enum import Enum
from threading import RLock

from config.setting import USER_ACCOUNTS
from core.logger import get_logger

logger = get_logger("shopxo.auth")

# 业务码：token 失效，需要重新登录
TOKEN_INVALID_CODES = (-400, 401)


class AuthType(str, Enum):
    """鉴权类型。"""

    NONE = "none"      # 免登录接口（登录、首页、搜索、地区等）
    USER = "user"      # 前台用户 token
    ADMIN = "admin"    # 商家后台（会话型，见 api_objects/admin_api.py）


class AuthError(Exception):
    """鉴权失败（登录接口未返回 token 等）。"""


class TokenManager:
    """Token 统一管理：缓存 / 获取 / 失效 / 重登。"""

    _lock = RLock()
    _tokens = {}
    _accounts = {AuthType.USER: dict(USER_ACCOUNTS["default"])}
    _login_times = {}

    # ------------------------------------------------------------ 配置
    @classmethod
    def configure(cls, auth_type: AuthType, account: dict) -> None:
        """配置某类鉴权使用的账号（支持用例覆盖，如切换测试账号）。"""
        with cls._lock:
            cls._accounts[auth_type] = dict(account)
            cls._tokens.pop(auth_type, None)

    @classmethod
    def account(cls, auth_type: AuthType = AuthType.USER) -> dict:
        with cls._lock:
            return dict(cls._accounts.get(auth_type) or {})

    # ------------------------------------------------------------ 取用
    @classmethod
    def get_token(cls, auth_type: AuthType = AuthType.USER, force: bool = False) -> str:
        """获取 token；force=True 时强制重新登录。"""
        with cls._lock:
            if force:
                cls._tokens.pop(auth_type, None)
            if auth_type in cls._tokens:
                return cls._tokens[auth_type]

            account = cls._accounts.get(auth_type)
            if not account:
                raise AuthError(f"未配置鉴权类型[{auth_type}]的账号，请先调用 TokenManager.configure()")

            token = cls._login(auth_type, account)
            cls._tokens[auth_type] = token
            cls._login_times[auth_type] = cls._login_times.get(auth_type, 0) + 1
            logger.info("[鉴权] %s 登录成功（第 %s 次），token=%s", auth_type.value, cls._login_times[auth_type], cls.mask(token))
            return token

    @classmethod
    def set_token(cls, auth_type: AuthType, token: str) -> None:
        """直接注入 token（供登录用例回填，避免二次登录）。"""
        with cls._lock:
            cls._tokens[auth_type] = token

    @classmethod
    def invalidate(cls, auth_type: AuthType = AuthType.USER) -> None:
        """使 token 失效，下次获取时自动重新登录。"""
        with cls._lock:
            cls._tokens.pop(auth_type, None)
            logger.warning("[鉴权] %s token 已失效，下次调用将自动重新登录", auth_type.value)

    @classmethod
    def login_times(cls, auth_type: AuthType = AuthType.USER) -> int:
        with cls._lock:
            return cls._login_times.get(auth_type, 0)

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _login(auth_type: AuthType, account: dict) -> str:
        # 延迟导入，避免 core -> api_objects -> core 的循环依赖
        from api_objects.user_api import UserAPI

        if auth_type != AuthType.USER:
            raise AuthError(f"鉴权类型[{auth_type}]不支持账号密码登录，请使用对应的 API 对象")
        res = UserAPI(auth=AuthType.NONE).login(
            account["accounts"], account["pwd"], account.get("type", "username")
        )
        if res.get("code") != 0 or not (res.get("data") or {}).get("token"):
            raise AuthError(f"登录失败：code={res.get('code')} msg={res.get('msg')}")
        return res["data"]["token"]

    @staticmethod
    def mask(token: str) -> str:
        """日志脱敏：只保留首尾少量字符。"""
        if not token:
            return "<empty>"
        if len(token) <= 8:
            return token[:2] + "***"
        return f"{token[:6]}***{token[-4:]}"
