"""地址模块：地区数据、收货地址增删改查。"""
from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class AddressAPI(BaseAPI):
    name = "AddressAPI"
    auth_type = AuthType.USER

    # ------------------------------------------------------------ 地区（免登录）
    def region_list(self, pid: int = 0) -> dict:
        """地区节点数据：pid=0 取省级，传入省级 id 取市级，以此类推。"""
        return self.post(f"{API_PREFIX}region/index", data={"pid": pid}, auth=AuthType.NONE)

    # ------------------------------------------------------------ 地址
    def list(self, page: int = 1) -> dict:
        """收货地址列表。"""
        return self.post(f"{API_PREFIX}useraddress/index", data={"page": page})

    def detail(self, address_id) -> dict:
        """收货地址详情。"""
        return self.post(f"{API_PREFIX}useraddress/detail", data={"id": address_id})

    def save(self, name: str, tel: str, address: str, province, city, county, **extra) -> dict:
        """新增收货地址（不传 id）。"""
        data = {"name": name, "tel": tel, "address": address, "province": province, "city": city, "county": county}
        data.update(extra)
        return self.post(f"{API_PREFIX}useraddress/save", data=data, idempotent=False)

    def update(self, address_id, **fields) -> dict:
        """修改收货地址（传 id 即为更新）。"""
        data = dict(fields)
        data["id"] = address_id
        return self.post(f"{API_PREFIX}useraddress/save", data=data, idempotent=False)

    def delete(self, address_id) -> dict:
        """删除收货地址。"""
        return self.post(f"{API_PREFIX}useraddress/delete", data={"id": address_id}, idempotent=False)

    # ------------------------------------------------------------ 业务辅助
    def find_by_name(self, name: str):
        """按收货人姓名查找地址（用例反查自己创建的地址 id）。"""
        res = self.list()
        items = ((res.get("data") or {}).get("data")) or []
        for item in items:
            if item.get("name") == name:
                return item
        return None

    def cleanup_by_name(self, name: str) -> int:
        """清理指定姓名的地址（含重复数据），返回删除条数。"""
        res = self.list()
        items = ((res.get("data") or {}).get("data")) or []
        targets = [item for item in items if item.get("name") == name]
        for item in targets:
            self.delete(item["id"])
        return len(targets)
