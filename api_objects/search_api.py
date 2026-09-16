"""搜索模块：关键字搜索、筛选、分页。"""
from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class SearchAPI(BaseAPI):
    name = "SearchAPI"
    # 免登录接口：文档明确游客可搜索（实测不带 token 也返回 code=0）
    # 声明为 NONE 的意义：登录凭证失效时，搜索用例仍能正常执行，
    # 而不是被误报成"用例失败"——把环境问题的影响面收敛到真正依赖登录的用例上。
    auth_type = AuthType.NONE

    def search(self, wd: str = None, page: int = 1, **filters) -> dict:
        """商品搜索。

        :param wd: 搜索关键字（为空表示取默认列表）
        :param page: 页码
        :param filters: 文档支持的筛选条件，如 category_ids / brand_id / screening_price / order_by
        """
        data = {"page": page}
        if wd is not None:
            data["wd"] = wd
        for key, value in filters.items():
            if value is not None:
                data[key] = value
        # 搜索为幂等读接口：允许重试
        return self.post(f"{API_PREFIX}search/index", data=data)

    def search_page(self, wd: str = None, page: int = 1, **filters) -> dict:
        """语义化别名：返回分页结构（total / page_total / data）。"""
        return self.search(wd=wd, page=page, **filters)
