"""商品模块：详情、规格、库存、收藏。"""
import json

from config.setting import API_PREFIX, DEFAULT_GOODS_ID
from core.auth import AuthType
from core.base_api import BaseAPI


class GoodsAPI(BaseAPI):
    name = "GoodsAPI"
    # 商品详情/规格为免登录接口（游客可浏览）；仅收藏接口需要登录（见 favor 方法）
    auth_type = AuthType.NONE

    def detail(self, goods_id: int = DEFAULT_GOODS_ID, ajax: str = "ajax", with_user: bool = False) -> dict:
        """商品详情（游客可访问）。

        :param with_user: 是否携带 token。携带时会额外返回 is_favor 等个性化字段，
                          校验收藏状态等用户维度数据时必须置为 True。
        """
        return self.post(
            f"{API_PREFIX}goods/detail",
            data={"goods_id": goods_id, "ajax": ajax},
            auth=AuthType.USER if with_user else AuthType.NONE,
        )

    def spec_detail(self, goods_id: int = DEFAULT_GOODS_ID, spec=None) -> dict:
        """商品规格详情（价格、库存、重量等随规格变化的数据）。"""
        data = {"id": goods_id}
        if spec is not None:
            data["spec"] = spec if isinstance(spec, str) else json.dumps(spec, ensure_ascii=False)
        return self.post(f"{API_PREFIX}goods/specdetail", data=data)

    def spec_type(self, goods_id: int = DEFAULT_GOODS_ID, spec=None) -> dict:
        """获取下一级可选规格类型（多规格商品逐级选择时使用）。"""
        data = {"id": goods_id}
        if spec is not None:
            data["spec"] = spec if isinstance(spec, str) else json.dumps(spec, ensure_ascii=False)
        return self.post(f"{API_PREFIX}goods/spectype", data=data)

    def favor(self, goods_id: int = DEFAULT_GOODS_ID, is_mandatory_favor: int = 0) -> dict:
        """商品收藏 / 取消收藏（同一接口切换状态，必须登录）。"""
        return self.post(
            f"{API_PREFIX}goods/favor",
            data={"id": goods_id, "is_mandatory_favor": is_mandatory_favor},
            auth=AuthType.USER,
            idempotent=False,
        )
