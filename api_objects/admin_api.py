"""商家模块（后台管理端）接口：商家登录、商品管理、订单管理、优惠券管理。

与前台的区别（面试常问）：
1. 入口不同：后台走 admin.php（商家/平台管理端），前台走 index.php?s=/api/；
2. 鉴权不同：后台是**会话(Cookie)鉴权 + 图形验证码**，不是 token；因此这里单独维护会话；
3. 断言不同：后台多数接口返回 HTML 或 JSON（ajax=ajax 时返回 JSON），需要按 ajax 模式调用。

当前沙箱环境的商家后台入口被禁用（请求 /admin.php?s=/admin/login/index 返回"非法访问"），
所以测试用例通过 @pytest.mark.requires("merchant") 自动跳过；
在后台可用的环境（本地部署 / 预发）上，本模块即可直接执行。
"""
from config.setting import ADMIN_ACCOUNT, ADMIN_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI
from core.env_check import Feature, capability


class AdminAPI(BaseAPI):
    name = "AdminAPI"
    auth_type = AuthType.NONE      # 后台使用会话鉴权，不走 token 注入
    default_idempotent = True

    # ------------------------------------------------------------ 能力判断
    @staticmethod
    def available() -> bool:
        """当前环境是否开放商家后台。"""
        return capability(Feature.MERCHANT.value)

    # ------------------------------------------------------------ 登录
    def login(self, accounts: str = None, pwd: str = None, verify: str = "") -> dict:
        """商家后台登录（ajax 模式返回 JSON）。

        :param verify: 图形验证码；后台开启验证码的环境需要先获取验证码图片并识别/人工输入
        """
        return self.post(
            f"{ADMIN_PREFIX}login/index",
            data={
                "accounts": accounts or ADMIN_ACCOUNT["accounts"],
                "pwd": pwd or ADMIN_ACCOUNT["pwd"],
                "type": "username",
                "verify": verify,
                "ajax": "ajax",
            },
            auth=AuthType.NONE,
            idempotent=False,
        )

    def is_logged_in(self) -> bool:
        """通过后台首页接口校验会话是否有效。"""
        res = self.post(f"{ADMIN_PREFIX}index/index", data={"ajax": "ajax"}, auth=AuthType.NONE)
        return res.get("code") == 0

    # ------------------------------------------------------------ 商品管理
    def goods_list(self, page: int = 1, keywords: str = None) -> dict:
        """商品列表。"""
        return self.post(
            f"{ADMIN_PREFIX}goods/index",
            data={"page": page, "keywords": keywords, "ajax": "ajax"},
            auth=AuthType.NONE,
        )

    def goods_shelves(self, goods_ids, is_shelves: int = 1) -> dict:
        """商品上下架（非幂等）。"""
        if isinstance(goods_ids, (list, tuple, set)):
            goods_ids = ",".join(str(i) for i in goods_ids)
        return self.post(
            f"{ADMIN_PREFIX}goods/shelves",
            data={"ids": goods_ids, "is_shelves": is_shelves, "ajax": "ajax"},
            auth=AuthType.NONE,
            idempotent=False,
        )

    # ------------------------------------------------------------ 订单管理
    def order_list(self, page: int = 1, status: str = "-1", keywords: str = None) -> dict:
        """订单列表（商家视角）。"""
        return self.post(
            f"{ADMIN_PREFIX}order/index",
            data={"page": page, "status": status, "keywords": keywords, "ajax": "ajax"},
            auth=AuthType.NONE,
        )

    def order_delivery(self, order_id, express_id=None, express_number: str = None) -> dict:
        """订单发货（非幂等）。"""
        return self.post(
            f"{ADMIN_PREFIX}order/delivery",
            data={"id": order_id, "express_id": express_id, "express_number": express_number, "ajax": "ajax"},
            auth=AuthType.NONE,
            idempotent=False,
        )

    # ------------------------------------------------------------ 优惠券管理
    def coupon_list(self, page: int = 1, keywords: str = None) -> dict:
        """优惠券列表（商家/平台发券管理）。"""
        return self.post(
            f"{ADMIN_PREFIX}coupon/index",
            data={"page": page, "keywords": keywords, "ajax": "ajax"},
            auth=AuthType.NONE,
        )
