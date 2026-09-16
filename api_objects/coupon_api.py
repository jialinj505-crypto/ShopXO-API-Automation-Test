"""优惠券模块（ShopXO 插件式接口）。

关键事实（已在沙箱实测）：优惠券在 ShopXO 中属于插件能力（plugins_coupon），
- 无插件环境下 `GET /index.php?s=/index/coupon/index` 与 `/api/coupon/*` 均不存在（404）；
- 插件接口统一走分发入口 `/index.php?s=/api/plugins/index`，
  由 pluginsname + pluginscontrol + pluginsaction 决定具体控制器与方法；
- 优惠券数据也会随首页 / 商品详情 / 订单确认接口下发（字段 plugins_coupon_data）。

因此本模块采用"能力自适应"设计：
- 已安装插件的环境：直接执行领取、查询、下单用券等流程；
- 未安装插件的环境：用例按 @pytest.mark.requires("coupon") 自动跳过并说明原因，
  同时仍然校验首页/订单确认响应中若出现 plugins_coupon_data 时的结构正确性。
"""
from config.setting import API_PREFIX, COUPON_PLUGIN_NAME
from core.auth import AuthType
from core.base_api import BaseAPI
from core.env_check import Feature, capability


class CouponAPI(BaseAPI):
    name = "CouponAPI"
    auth_type = AuthType.USER
    plugin = COUPON_PLUGIN_NAME

    # ------------------------------------------------------------ 能力判断
    @staticmethod
    def available() -> bool:
        """当前环境是否具备优惠券插件能力。"""
        return capability(Feature.COUPON.value)

    # ------------------------------------------------------------ 插件分发
    def _plugin(self, control: str, action: str, **params) -> dict:
        data = {"pluginsname": self.plugin, "pluginscontrol": control, "pluginsaction": action}
        data.update({k: v for k, v in params.items() if v is not None})
        return self.post(f"{API_PREFIX}plugins/index", data=data)

    def coupon_list(self, page: int = 1, **params) -> dict:
        """可领取优惠券列表。"""
        return self._plugin("index", "index", page=page, **params)

    def receive(self, coupon_id) -> dict:
        """领取优惠券（非幂等）。"""
        return self._plugin("index", "receive", id=coupon_id)

    def my_coupon_list(self, page: int = 1, status=None) -> dict:
        """我的优惠券列表。"""
        return self._plugin("usercoupon", "index", page=page, status=status)

    # ------------------------------------------------------------ 响应数据提取
    @staticmethod
    def extract_plugin_data(response: dict, key: str = "plugins_coupon_data"):
        """从首页 / 商品详情 / 订单确认响应中提取优惠券插件数据块。

        兼容 ShopXO 单层(data.plugins_coupon_data) 与双层(data.data.plugins_coupon_data) 结构。
        """
        data = response.get("data")
        if isinstance(data, dict):
            if key in data:
                return data[key]
            inner = data.get("data")
            if isinstance(inner, dict) and key in inner:
                return inner[key]
        return None
