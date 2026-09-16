"""端到端（E2E）闭环测试：登录 -> 搜索 -> 商品详情 -> 加购 -> 改数量 -> 确认订单 -> 提交订单 -> 订单详情 -> 取消 -> 删除。

为什么需要 E2E：
单接口用例只能证明"某个接口返回值没变"，而真实业务是跨模块的链路。
这条闭环把 6 个模块串起来，任何一环的数据不一致都会在这里暴露
（例如：搜索到的商品无法加购、加购金额与订单金额不一致、下单后购物车未清空等）。
"""
import pytest

from api_objects.order_api import OrderAPI
from core.allure_utils import attach_json, mark, step
from core.assert_helper import Assert


@pytest.mark.e2e
@pytest.mark.p0
@pytest.mark.positive
def test_shopping_flow_end_to_end(
    user_api, search_api, goods_api, cart_api, order_api, clean_cart, temp_address, payment_id, account
):
    """完整下单闭环（含数据清理，可重复执行）。"""
    mark(
        feature="端到端闭环",
        story="登录-搜索-加购-下单-取消",
        title="用户完整购物链路 E2E",
        description="覆盖 用户/商品/搜索/购物车/订单/地址 六个模块的跨接口数据一致性",
        severity="blocker",
    )
    order_id = None
    keyword = "iphone"
    try:
        # ---------------------------------------------------------- 1. 登录
        with step("1. 登录获取鉴权 token"):
            login = user_api.login(account["accounts"], account["pwd"], account.get("type", "username"))
        Assert.success(login, "1-登录")
        Assert.schema(login, "login_success", "1-登录")
        token = login["data"]["token"]
        Assert.is_true(len(str(token)) >= 8, "登录未返回有效 token")

        # ---------------------------------------------------------- 2. 搜索商品
        with step(f"2. 搜索商品：wd={keyword}"):
            search = search_api.search(wd=keyword, page=1)
        Assert.success(search, "2-搜索")
        items = search["data"]["data"]
        Assert.not_empty(items, "2-搜索结果为空")
        goods = items[0]
        goods_id = goods["id"]
        Assert.is_true(keyword.lower() in str(goods["title"]).lower(), "搜索结果与关键字不匹配")

        # ---------------------------------------------------------- 3. 商品详情
        with step(f"3. 查询商品详情：goods_id={goods_id}"):
            detail = goods_api.detail(goods_id)
        Assert.success(detail, "3-商品详情")
        goods_detail = detail["data"]["goods"]
        Assert.is_true(str(goods_detail["is_shelves"]) == "1", "3-商品未上架，无法下单")
        Assert.is_true(str(goods_detail["id"]) == str(goods_id), "3-详情商品与搜索结果不一致")

        # ---------------------------------------------------------- 4. 加入购物车
        with step(f"4. 加入购物车：goods_id={goods_id} 数量=1"):
            clean_cart.clear()
            add = cart_api.add(goods_id, 1)
        Assert.success(add, "4-加购")
        cart_item = cart_api.find_item(goods_id)
        Assert.not_none(cart_item, "4-购物车中未找到刚加入的商品")

        # ---------------------------------------------------------- 5. 修改数量
        with step("5. 修改购物车数量为 2"):
            update = cart_api.update_stock(cart_item["id"], goods_id, 2)
        Assert.success(update, "5-修改数量")
        cart_item = cart_api.find_item(goods_id)
        Assert.is_true(str(cart_item["stock"]) == "2", f"5-数量修改失败：{cart_item['stock']}")
        Assert.money(cart_item["total_price"], float(cart_item["price"]) * 2, "5-购物车小计")

        # ---------------------------------------------------------- 6. 确认订单
        with step("6. 进入订单确认页，校验金额与地址"):
            confirm = order_api.confirm(cart_item["id"], address_id=temp_address["id"])
        Assert.success(confirm, "6-订单确认")
        base = confirm["data"]["base"]
        Assert.money(base["total_price"], cart_item["total_price"], "6-订单确认页商品总额", tol=0.02)
        # base.goods_count 为"商品种类数(购物车行数)"，本次购物车为 1 种商品、2 件
        Assert.is_true(int(base["goods_count"]) == 1, f"6-商品种类数不符：{base['goods_count']}")

        # ---------------------------------------------------------- 7. 提交订单
        with step("7. 提交订单，生成订单号"):
            submit = order_api.submit(cart_item["id"], address_id=temp_address["id"], payment_id=payment_id)
        Assert.success(submit, "7-提交订单")
        order_id = (submit["data"]["order_ids"] or [None])[0]
        Assert.not_empty(order_id, "7-未返回订单号")
        attach_json({"goods_id": goods_id, "order_id": order_id, "amount": base["total_price"]}, name="闭环关键数据")

        # ---------------------------------------------------------- 8. 订单详情校验
        with step("8. 校验订单详情与下单数据一致"):
            order_detail = order_api.detail(order_id)
        Assert.success(order_detail, "8-订单详情")
        Assert.schema(order_detail, "order_detail", "8-订单详情")
        detail_data = order_detail["data"]["data"]
        status, status_name = OrderAPI.status_of(order_detail)
        Assert.is_true(str(status) == "1", f"8-新订单状态异常：{status} {status_name}")
        Assert.money(detail_data["total_price"], base["total_price"], "8-订单金额与确认页不一致", tol=0.02)

        # ---------------------------------------------------------- 9. 购物车已清空
        with step("9. 校验下单后商品已从购物车移除"):
            cart_after = cart_api.list()
        Assert.success(cart_after, "9-购物车列表")
        Assert.is_true(cart_api.find_item(goods_id) is None, "9-下单后商品仍在购物车中")

        # ---------------------------------------------------------- 10. 取消订单
        with step("10. 取消订单，状态应变为已取消"):
            cancel = order_api.cancel(order_id)
        Assert.success(cancel, "10-取消订单")
        status_after, name_after = OrderAPI.status_of(order_api.detail(order_id))
        Assert.is_true(str(status_after) == "5", f"10-取消后状态异常：{status_after} {name_after}")
    finally:
        # ------------------------------------------------------ 11. 数据清理
        with step("11. 清理测试数据（取消并删除订单、清空购物车）"):
            try:
                if order_id:
                    order_api.cancel(order_id)
                    order_api.delete(order_id)
            except Exception:  # noqa: BLE001 - 清理失败不影响用例结论
                pass
            clean_cart.clear()
