"""订单模块：确认订单、提交订单、列表、详情、取消、删除、支付、收货、评价。

幂等性声明（决定失败时是否重试）：
- 查询类（列表/详情）  -> 幂等，可重试
- 写操作（提交/支付/评价）-> 非幂等，禁止重试，避免重复下单
- 取消/删除              -> 重复调用返回业务提示，可按幂等处理
"""
from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class OrderAPI(BaseAPI):
    name = "OrderAPI"
    auth_type = AuthType.USER

    # ------------------------------------------------------------ 下单
    def confirm(self, ids, buy_type: str = "cart", address_id: int = 0) -> dict:
        """订单确认页数据（商品、支付方式、金额、地址）。"""
        return self.post(
            f"{API_PREFIX}buy/index",
            data={"ids": self._join(ids), "buy_type": buy_type, "address_id": address_id},
        )

    def submit(self, ids, address_id: int = 0, payment_id: int = 0, buy_type: str = "cart") -> dict:
        """提交订单（非幂等，禁用重试）。"""
        return self.post(
            f"{API_PREFIX}buy/add",
            data={
                "ids": self._join(ids),
                "buy_type": buy_type,
                "address_id": address_id,
                "payment_id": payment_id,
            },
            idempotent=False,
        )

    # ------------------------------------------------------------ 查询
    def list(self, page: int = 1, status: str = "-1", keywords: str = None) -> dict:
        """订单列表（status=-1 全部；1 待付款；5 已取消）。"""
        data = {"page": page, "status": status}
        if keywords:
            data["keywords"] = keywords
        return self.post(f"{API_PREFIX}order/index", data=data)

    def detail(self, order_id) -> dict:
        """订单详情。"""
        return self.post(f"{API_PREFIX}order/detail", data={"id": order_id})

    # ------------------------------------------------------------ 操作
    def cancel(self, order_id) -> dict:
        """取消订单。"""
        return self.post(f"{API_PREFIX}order/cancel", data={"id": order_id})

    def delete(self, order_id) -> dict:
        """删除订单（仅允许删除已取消/已完成等终态订单）。"""
        return self.post(f"{API_PREFIX}order/delete", data={"id": order_id})

    def pay(self, order_id, payment_id: int) -> dict:
        """订单支付（非幂等）。"""
        return self.post(f"{API_PREFIX}order/pay", data={"id": order_id, "payment_id": payment_id}, idempotent=False)

    def collect(self, order_id) -> dict:
        """确认收货。"""
        return self.post(f"{API_PREFIX}order/collect", data={"id": order_id})

    def comments(self, order_id, content: str, rating: int = 5, is_anonymous: int = 0) -> dict:
        """订单商品评价（非幂等）。"""
        return self.post(
            f"{API_PREFIX}order/comments",
            data={"id": order_id, "content": content, "rating": rating, "is_anonymous": is_anonymous},
            idempotent=False,
        )

    # ------------------------------------------------------------ 工具
    @staticmethod
    def _join(ids) -> str:
        if isinstance(ids, (list, tuple, set)):
            return ",".join(str(i) for i in ids)
        return str(ids)

    @staticmethod
    def status_of(order_detail_response: dict):
        """从订单详情响应中取出状态（兼容单层与双层 data 结构）。"""
        data = order_detail_response.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        return data.get("status"), data.get("status_name")
