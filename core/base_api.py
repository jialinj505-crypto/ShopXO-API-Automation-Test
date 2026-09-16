"""BaseAPI —— 接口请求底层驱动（框架核心）。

职责边界：**只负责"怎么发请求"，不关心"业务断言"**。
上层 `api_objects/*` 只声明路由与参数，`tests/*` 只写业务与断言，实现分层解耦。

能力清单：
1. 统一鉴权：根据 auth 类型自动注入 Token（业务码 -400 自动失效重登）；
2. 请求重试：网络异常 / 5xx / 指定业务码按退避策略重试，且**非幂等接口强制不重试**；
3. 超时控制：连接与读取超时统一管理；
4. 公共参数：按接口文档自动注入 application / application_client_type；
5. 可观测性：结构化日志 + Allure 请求/响应附件 + 可复现的 curl 命令；
6. 响应容错：非 JSON / 空响应不抛裸异常，统一转成框架错误码，便于断言与定位。
"""
import json as _json
import time

import requests

from config.setting import (
    BASE_URL,
    COMMON_PARAMS,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF,
    RETRY_BIZ_CODES,
    RETRY_INTERVAL,
    RETRY_STATUS_CODES,
    RETRY_TIMES,
)
from core.allure_utils import attach_json, attach_text
from core.auth import TOKEN_INVALID_CODES, AuthType, TokenManager
from core.logger import get_logger

_UNSET = object()

# 框架错误码（负值，与 ShopXO 业务码区分开，便于快速识别是"框架层"还是"业务层"问题）
CODE_NON_JSON = -9998
CODE_NETWORK = -9999


class ApiError(Exception):
    """请求层异常：网络不可达、重试耗尽等（区别于业务失败 code != 0）。"""


class BaseAPI:
    """所有接口对象的基类。"""

    name = "BaseAPI"
    auth_type = AuthType.NONE      # 子类声明默认鉴权方式
    default_idempotent = True      # 子类可声明默认是否幂等

    def __init__(self, base_url=None, auth=None, timeout=None, retry_times=None, retry_interval=None):
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.auth = self.auth_type if auth is None else auth
        self.timeout = REQUEST_TIMEOUT if timeout is None else timeout
        self.retry_times = RETRY_TIMES if retry_times is None else retry_times
        self.retry_interval = RETRY_INTERVAL if retry_interval is None else retry_interval
        self.logger = get_logger(f"shopxo.api.{self.name}")

        # 复用连接（长连接）显著提升批量用例执行速度
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{self.base_url}/",
            }
        )
        # 最近一次请求的完整上下文，供断言失败时排查/附件使用
        self.last_exchange = {}

    # ------------------------------------------------------------------ 工具
    def build_url(self, endpoint: str) -> str:
        if endpoint.startswith("http"):
            return endpoint
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    @staticmethod
    def mask_payload(payload) -> dict:
        """日志/附件脱敏：token、密码只保留首尾，避免凭据随报告外发。

        注意：脱敏不按长度区别对待——短密码同样是敏感信息，一旦被拼进
        `build_curl()` 或写进 Allure 附件，就等于泄露。
        """
        if not isinstance(payload, dict):
            return payload
        masked = dict(payload)
        for key in ("token", "pwd", "password"):
            if key in masked and masked[key]:
                masked[key] = TokenManager.mask(str(masked[key]))
        return masked

    @classmethod
    def mask_nested(cls, payload):
        """递归脱敏：字典按敏感键名脱敏，列表逐项处理，其它类型原样返回。

        用于**响应体**：登录接口会在 `data.token` 里返回凭据，
        响应体会作为附件写进报告，所以必须和请求参数一样脱敏。
        """
        if isinstance(payload, dict):
            return {
                key: TokenManager.mask(str(value))
                if cls._is_sensitive_key(key) and value
                else cls.mask_nested(value)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [cls.mask_nested(item) for item in payload]
        return payload

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        key = str(key).lower()
        return key in ("token", "pwd", "password") or key.endswith("token")

    def build_curl(self) -> str:
        """根据最近一次请求生成可直接复现的 curl 命令。"""
        ex = self.last_exchange or {}
        if not ex:
            return ""
        params = ex.get("params") or {}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = ex.get("url", "")
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        lines = [f"curl -X {ex.get('method', 'POST')} '{url}'"]
        for k, v in (ex.get("data") or {}).items():
            lines.append(f"  -d '{k}={v}'")
        return " \\\n".join(lines)

    # ------------------------------------------------------------------ 请求
    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params=None,
        data=None,
        json_body=None,
        auth=_UNSET,
        common=True,
        retry_times=None,
        idempotent=None,
        attach=True,
        timeout=None,
        **kwargs,
    ) -> dict:
        """统一请求入口。

        :param auth: 鉴权方式；不传则使用类默认值，传 AuthType.NONE 可强制免登录
        :param idempotent: 是否幂等；非幂等接口（下单/支付等）不会重试
        :param common: 是否自动注入文档要求的公共参数
        :param attach: 是否把请求/响应写入 Allure 附件
        """
        method = method.upper()
        url = self.build_url(endpoint)
        params = dict(params or {})
        if data is not None:
            data = dict(data)

        if common:
            if method == "GET":
                for key, value in COMMON_PARAMS.items():
                    params.setdefault(key, value)
            else:
                if data is None:
                    data = {}
                for key, value in COMMON_PARAMS.items():
                    data.setdefault(key, value)

        auth_type = self.auth if auth is _UNSET else auth
        is_idempotent = self.default_idempotent if idempotent is None else idempotent
        max_retry = self.retry_times if retry_times is None else retry_times
        attempts = max_retry + 1 if is_idempotent else 1
        if not is_idempotent and max_retry:
            self.logger.debug("[重试] %s 为非幂等接口，本次禁用重试", endpoint)

        attempt = 0
        re_login_done = False
        last_result = None
        token_injected = False       # 上一轮尝试的 token 是否由框架注入（决定重试前是否刷新）
        while attempt < attempts:
            attempt += 1
            if token_injected:
                # 框架注入的 token 每轮尝试前都清掉重新注入：
                # token 失效（-400）时 invalidate() 已清缓存，这里的 get_token() 会真正重新登录，
                # 从而避免"重试仍带旧 token、必然再撞一次 -400"的假自愈。
                params.pop("token", None)
            token_injected = self._inject_token(auth_type, params, data)

            started = time.perf_counter()
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params or None,
                    data=data,
                    json=json_body,
                    timeout=timeout or self.timeout,
                    **kwargs,
                )
            except requests.exceptions.RequestException as exc:  # 网络层异常
                elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                error = f"{type(exc).__name__}: {exc}"
                self.logger.warning(
                    "[请求异常] %s %s 第%s/%s次 耗时%sms 原因=%s", method, endpoint, attempt, attempts, elapsed_ms, error
                )
                self.last_exchange = {
                    "method": method,
                    "url": url,
                    "params": self.mask_payload(params),
                    "data": self.mask_payload(data),
                    "error": error,
                    "elapsed_ms": elapsed_ms,
                    "attempt": attempt,
                }
                if attempt < attempts:
                    self._sleep(attempt, endpoint, error)
                    continue
                raise ApiError(f"[{self.name}] {method} {endpoint} 请求失败（已尝试 {attempt} 次）：{error}") from exc

            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            result = self._parse(response)
            self._record(method, endpoint, url, params, data, response, result, elapsed_ms, attempt)
            self._log(method, endpoint, result, elapsed_ms, attempt, attempts)

            # ---- token 失效：自动重新登录（额外奖励一次尝试机会）----
            if (
                auth_type != AuthType.NONE
                and result.get("code") in TOKEN_INVALID_CODES
                and not re_login_done
            ):
                re_login_done = True
                attempts += 1
                TokenManager.invalidate(auth_type)
                self.logger.warning(
                    "[鉴权] %s %s 返回 token 失效(code=%s)：已清除缓存，下一次尝试将重新登录并携带新 token",
                    method, endpoint, result.get("code"),
                )
                continue

            # ---- 需要重试的情形：5xx / 指定业务码 ----
            retry_reason = None
            if response.status_code in RETRY_STATUS_CODES:
                retry_reason = f"HTTP {response.status_code}"
            elif result.get("code") in RETRY_BIZ_CODES:
                retry_reason = f"业务码 {result.get('code')} {result.get('msg')}"

            if retry_reason and attempt < attempts:
                self._sleep(attempt, endpoint, retry_reason)
                last_result = result
                continue

            if attach:
                self._attach(result)
            return result

        if attach:
            self._attach(last_result or {})
        return last_result or {"code": CODE_NETWORK, "msg": "请求未执行", "data": None}

    # ------------------------------------------------------------- 便捷方法
    def get(self, endpoint, **kwargs) -> dict:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint, **kwargs) -> dict:
        return self.request("POST", endpoint, **kwargs)

    def close(self):
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 内部
    def _inject_token(self, auth_type, params: dict, data) -> bool:
        """统一鉴权：按文档要求把 token 放入 GET 参数。

        :return: 本次的 token 是否**由框架注入**。
            调用方显式传入 token 时返回 False（不覆盖，便于构造"伪造 token"等异常用例），
            `request()` 据此判断重试前是否需要把上一轮的 token 去掉重新注入——
            这是"登录失效自动重登"能真正生效的关键（见 `request()`）。
        """
        if auth_type != AuthType.USER:
            return False
        if "token" in params or (isinstance(data, dict) and "token" in data):
            return False
        params["token"] = TokenManager.get_token(AuthType.USER)
        return True

    def _parse(self, response) -> dict:
        """解析响应：非 JSON 不抛裸异常，转为框架错误码。"""
        status = response.status_code
        try:
            payload = response.json()
        except ValueError:
            text = (response.text or "").strip()
            return {
                "code": CODE_NON_JSON,
                "msg": f"响应非 JSON（HTTP {status}），可能是 HTML 页面或空响应",
                "data": None,
                "_raw": text[:1000],
                "_http_status": status,
            }
        if not isinstance(payload, dict):
            return {
                "code": CODE_NON_JSON,
                "msg": f"响应结构异常，期望对象实际为 {type(payload).__name__}",
                "data": payload,
                "_http_status": status,
            }
        payload["_http_status"] = status
        return payload

    def _record(self, method, endpoint, url, params, data, response, result, elapsed_ms, attempt) -> None:
        self.last_exchange = {
            "method": method,
            "endpoint": endpoint,
            "url": url,
            "params": self.mask_payload(params),
            "data": self.mask_payload(data),
            "http_status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "attempt": attempt,
            "code": result.get("code"),
            "msg": result.get("msg"),
            "response": self._safe_payload(result),
        }

    @classmethod
    def _safe_payload(cls, result: dict) -> dict:
        """去掉内部字段并做脱敏，保留业务响应体用于附件。

        两个目的：`_` 开头的内部字段（`_raw`/`_http_status`）不进附件；
        响应体里的 token 等凭据必须脱敏——否则登录响应会把 token 明文写进报告。
        """
        cleaned = {k: v for k, v in result.items() if not k.startswith("_")}
        return cls.mask_nested(cleaned)

    def _log(self, method, endpoint, result, elapsed_ms, attempt, attempts) -> None:
        code = result.get("code")
        message = f"{method} {endpoint} -> code={code} msg={result.get('msg')} (耗时{elapsed_ms}ms, 第{attempt}/{attempts}次)"
        if code == 0:
            self.logger.info(message)
        else:
            self.logger.warning(message)

    def _sleep(self, attempt: int, endpoint: str, reason: str) -> None:
        delay = self.retry_interval * (RETRY_BACKOFF ** (attempt - 1))
        self.logger.warning("[重试] %s 第%s次失败(%s)，%.2fs 后进行第%s次重试", endpoint, attempt, reason, delay, attempt + 1)
        time.sleep(delay)

    def _attach(self, result: dict) -> None:
        """把可复现信息写入 Allure 报告。"""
        try:
            attach_text(self.build_curl(), name="请求(可复现 curl)")
            attach_json(self.last_exchange.get("response"), name=f"响应 code={result.get('code')} msg={result.get('msg')}")
        except Exception:  # noqa: BLE001
            pass
