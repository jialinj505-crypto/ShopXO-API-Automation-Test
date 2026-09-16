"""用户模块：登录、积分、消息、留言。"""
from config.setting import API_PREFIX
from core.auth import AuthType
from core.base_api import BaseAPI


class UserAPI(BaseAPI):
    name = "UserAPI"
    auth_type = AuthType.USER

    # ------------------------------------------------------------ 登录
    def login(self, accounts: str, pwd: str, type: str = "username") -> dict:
        """账号登录（免登录接口，登录成功后返回 token）。"""
        return self.post(
            f"{API_PREFIX}user/login",
            data={"accounts": accounts, "pwd": pwd, "type": type},
            auth=AuthType.NONE,
        )

    # ------------------------------------------------------------ 用户中心
    def integral_list(self, page: int = 1) -> dict:
        """我的积分列表。"""
        return self.post(f"{API_PREFIX}userintegral/index", data={"page": page})

    def message_list(self, page: int = 1) -> dict:
        """消息列表。"""
        return self.post(f"{API_PREFIX}message/index", data={"page": page})

    # ------------------------------------------------------------ 留言（工单）
    def answer_add(self, name: str, tel: str, content: str) -> dict:
        """提交留言。"""
        return self.post(
            f"{API_PREFIX}answer/add",
            data={"name": name, "tel": tel, "content": content},
            idempotent=False,
        )

    def answer_list(self, page: int = 1) -> dict:
        """我的留言列表。"""
        return self.post(f"{API_PREFIX}answer/index", data={"page": page})
