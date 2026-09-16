"""首页接口。"""
from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class HomeAPI(BaseAPI):
    name = "HomeAPI"
    auth_type = AuthType.USER

    def index(self) -> dict:
        """首页数据（轮播、导航、推荐商品、购物车总数等聚合数据）。"""
        return self.post(f"{API_PREFIX}index/index", auth=AuthType.NONE)

    def plugins_info(self, pluginsname: str, control: str = "index", action: str = "index") -> dict:
        """插件数据分发入口（优惠券/店铺等插件共用）。"""
        return self.post(
            f"{API_PREFIX}plugins/index",
            data={"pluginsname": pluginsname, "pluginscontrol": control, "pluginsaction": action},
            auth=AuthType.NONE,
        )
