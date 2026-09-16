"""预检工具：检查测试数据引用的商品在当前环境下是否仍然上架、可售。

为什么需要它：
商品会下架、库存会清零。如果用例硬编码一个已下架的商品 ID，回归会大面积失败，
定位成本很高。把这一步做成 CI 前置检查（或定时任务），可以提前发现"数据失效"而不是"代码问题"。

用法：
    python tools/check_goods_status.py                      # 检查配置中的默认商品
    python tools/check_goods_status.py --goods-id 12 --goods-id 1
    python tools/check_goods_status.py --json data/valid_goods.json   # 检查数据集里的商品

退出码：0=全部可用；1=存在不可用商品（便于在 Jenkins 中作为卡点）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api_objects.goods_api import GoodsAPI  # noqa: E402
from config.setting import DATA_DIR, DEFAULT_GOODS_ID  # noqa: E402
from core.auth import AuthType  # noqa: E402


def load_goods_ids_from_json(path: Path) -> list:
    """从数据文件里读取商品 ID（兼容 list / {"cases": [...]} / {"goods": [...]} 结构）。"""
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if isinstance(data, dict):
        for key in ("goods", "cases", "data"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    ids = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            if "goods_id" in item:
                ids.append(item["goods_id"])
            elif "id" in item:
                ids.append(item["id"])
    return ids


def check(goods_ids) -> list:
    api = GoodsAPI(auth=AuthType.NONE)
    results = []
    for goods_id in goods_ids:
        res = api.detail(goods_id)
        goods = ((res.get("data") or {}).get("goods")) or {}
        ok = res.get("code") == 0 and str(goods.get("is_shelves")) == "1"
        results.append(
            {
                "goods_id": goods_id,
                "code": res.get("code"),
                "msg": res.get("msg"),
                "title": goods.get("title"),
                "price": goods.get("price"),
                "inventory": goods.get("inventory"),
                "is_shelves": goods.get("is_shelves"),
                "ok": ok,
            }
        )
    api.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="商品可用性预检")
    parser.add_argument("--goods-id", action="append", type=int, default=[], help="待检查的商品ID，可重复传入")
    parser.add_argument("--json", default="", help="从数据文件读取商品ID，如 data/valid_goods.json")
    args = parser.parse_args()

    goods_ids = args.goods_id or [DEFAULT_GOODS_ID]
    if args.json:
        path = Path(args.json)
        if not path.is_absolute():
            path = ROOT / path
        goods_ids = load_goods_ids_from_json(path) or goods_ids

    results = check(goods_ids)
    print(f"{'商品ID':<10}{'状态':<8}{'是否上架':<10}{'库存':<12}标题")
    print("-" * 90)
    for item in results:
        status = "可用" if item["ok"] else f"不可用(code={item['code']})"
        print(f"{str(item['goods_id']):<10}{status:<8}{str(item['is_shelves']):<10}{str(item['inventory']):<12}{item['title'] or item['msg']}")

    bad = [item for item in results if not item["ok"]]
    if bad:
        print(f"\n[失败] {len(bad)} 个商品不可用，请更新测试数据（data/ 目录）后再执行回归")
        return 1
    print(f"\n[通过] {len(results)} 个商品均可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
