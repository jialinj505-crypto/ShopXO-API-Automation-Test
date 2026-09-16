"""购物车模块：加购、列表、改数量、删除。"""
import json

from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class CartAPI(BaseAPI):
    name = "CartAPI"
    auth_type = AuthType.USER

    def add(self, goods_id: int, stock: int = 1, spec=None) -> dict:
        """加入购物车。"""
        data = {"goods_id": goods_id, "stock": stock}
        if spec is not None:
            data["spec"] = spec if isinstance(spec, str) else json.dumps(spec, ensure_ascii=False)
        return self.post(f"{API_PREFIX}cart/save", data=data, idempotent=False)

    def list(self) -> dict:
        """购物车列表（含 common_cart_total 商品总数）。"""
        return self.post(f"{API_PREFIX}cart/index")

    def update_stock(self, cart_id: int, goods_id: int, stock: int) -> dict:
        """修改购物车商品数量。"""
        return self.post(
            f"{API_PREFIX}cart/stock",
            data={"id": cart_id, "goods_id": goods_id, "stock": stock},
            idempotent=False,
        )

    def delete(self, ids) -> dict:
        """删除购物车商品，支持单个 id / 多个 id（英文逗号分隔）/ id 列表。"""
        if isinstance(ids, (list, tuple, set)):
            ids = ",".join(str(i) for i in ids)
        return self.post(f"{API_PREFIX}cart/delete", data={"id": str(ids)}, idempotent=False)

    # ------------------------------------------------------------ 业务辅助
    def find_item(self, goods_id: int):
        """按商品 ID 找到购物车记录（用例里清理数据时常用）。"""
        cart = self.list()
        items = ((cart.get("data") or {}).get("data")) or []
        for item in items:
            if str(item.get("goods_id")) == str(goods_id):
                return item
        return None

    def clear(self) -> int:
        """清空当前账号购物车，返回清理的条目数（用例前置/后置环境清理）。"""
        cart = self.list()
        items = ((cart.get("data") or {}).get("data")) or []
        if not items:
            return 0
        ids = [item["id"] for item in items]
        self.delete(ids)
        return len(ids)
