"""接口层（Page Object 思想）：一个类对应一个业务模块，一个方法对应一个接口。

约定：
- 只负责"路由 + 参数 + 请求方式 + 鉴权方式"，不做业务断言；
- 幂等性由这里声明（下单/支付等非幂等接口禁用重试）；
- 用例层拿到的是解析后的响应 dict，断言统一走 core.assert_helper.Assert。
"""
from api_objects.address_api import AddressAPI
from api_objects.admin_api import AdminAPI
from api_objects.cart_api import CartAPI
from api_objects.coupon_api import CouponAPI
from api_objects.goods_api import GoodsAPI
from api_objects.home_api import HomeAPI
from api_objects.order_api import OrderAPI
from api_objects.search_api import SearchAPI
from api_objects.user_api import UserAPI

__all__ = [
    "AddressAPI",
    "AdminAPI",
    "CartAPI",
    "CouponAPI",
    "GoodsAPI",
    "HomeAPI",
    "OrderAPI",
    "SearchAPI",
    "UserAPI",
]
