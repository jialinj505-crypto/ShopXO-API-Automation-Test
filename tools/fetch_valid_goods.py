"""数据维护工具：从真实搜索接口抓取在售商品，生成/刷新测试数据集。

背景：测试数据不应该"手工编造"。这个脚本调用被测系统自己的搜索接口，
抓取真实商品（ID、标题、价格、库存、是否多规格），落盘为 data/valid_goods.json，
供用例（尤其是加购、下单链路）引用，环境数据变化后可一键刷新。

用法：
    python tools/fetch_valid_goods.py                      # 默认抓 20 条
    python tools/fetch_valid_goods.py --limit 50 --wd 手机
    python tools/fetch_valid_goods.py --out data/valid_goods.json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api_objects.search_api import SearchAPI  # noqa: E402
from config.setting import DATA_DIR  # noqa: E402
from core.auth import AuthType  # noqa: E402


def fetch(limit: int = 20, wd: str = None, page: int = 1) -> list:
    """抓取在售商品（免登录即可调用搜索接口）。"""
    api = SearchAPI(auth=AuthType.NONE)
    res = api.search(wd=wd, page=page)
    api.close()
    if res.get("code") != 0:
        raise SystemExit(f"搜索接口调用失败：code={res.get('code')} msg={res.get('msg')}")

    goods_list = []
    for item in ((res.get("data") or {}).get("data")) or []:
        if str(item.get("is_shelves")) != "1":
            continue
        goods_list.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "inventory": item.get("inventory"),
                "is_exist_many_spec": str(item.get("is_exist_many_spec", "0")),
                "brand_name": item.get("brand_name"),
                "goods_url": item.get("goods_url"),
            }
        )
        if len(goods_list) >= limit:
            break
    return goods_list


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取在售商品生成测试数据")
    parser.add_argument("--limit", type=int, default=20, help="抓取条数")
    parser.add_argument("--wd", default=None, help="搜索关键字（默认取全部商品）")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--out", default="data/valid_goods.json", help="输出文件（相对项目根目录）")
    args = parser.parse_args()

    goods_list = fetch(limit=args.limit, wd=args.wd, page=args.page)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "api/search/index",
        "total": len(goods_list),
        "goods": goods_list,
    }
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)

    print(f"已抓取 {len(goods_list)} 条在售商品 -> {out_path}")
    for item in goods_list[:5]:
        print(f"  id={item['id']:<6} 库存={item['inventory']:<12} 多规格={item['is_exist_many_spec']} {item['title'][:40]}")
    if len(goods_list) > 5:
        print(f"  ...（其余 {len(goods_list) - 5} 条见文件）")
    return 0 if goods_list else 1


if __name__ == "__main__":
    sys.exit(main())
