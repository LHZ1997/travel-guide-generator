import json
import os
import subprocess
from typing import Optional

try:
    from .base import BaseSkill
except ImportError:
    from skills.base import BaseSkill


def _run_flyai(cmd: str, args: list[str]) -> dict:
    """Run a flyai CLI command and return parsed JSON.

    Sets NODE_TLS_REJECT_UNAUTHORIZED to work around corporate proxy SSL issues.
    Returns {"error": ...} on failure.
    """
    env = {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "0"}
    full_args = ["flyai", cmd] + args
    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode != 0:
            return {"error": f"flyai {cmd} failed: {result.stderr.strip()[:500]}"}
        stdout = result.stdout.strip()
        if not stdout:
            return {"error": f"flyai {cmd} returned empty result"}
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        return {"error": f"flyai {cmd} timed out after 30s"}
    except json.JSONDecodeError as e:
        return {"error": f"flyai {cmd} returned invalid JSON: {str(e)[:200]}"}
    except FileNotFoundError:
        return {"error": "flyai CLI not found. Install with: npm i -g @fly-ai/flyai-cli"}
    except Exception as e:
        return {"error": f"flyai {cmd} error: {str(e)[:500]}"}


def _extract_items(result: dict) -> list[dict]:
    """Extract item list from flyai response (handles different formats)."""
    data = result.get("data", {})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("itemList", [])
    return []


def _compact_item(item: dict, max_desc_len: int = 200) -> dict:
    """Compact a single item to reduce token usage."""
    desc = item.get("description", item.get("desc", ""))
    if desc and len(desc) > max_desc_len:
        desc = desc[:max_desc_len] + "..."
    compact = {
        "name": item.get("name", item.get("title", "")),
        "price": item.get("price", ""),
        "jumpUrl": item.get("jumpUrl", item.get("detailUrl", "")),
    }
    if desc:
        compact["description"] = desc
    if item.get("mainPic"):
        compact["image"] = item["mainPic"]
    if item.get("address"):
        compact["address"] = item["address"]
    if item.get("star") or item.get("poiLevel"):
        compact["rating"] = item.get("star") or f"{item.get('poiLevel')}A景区"
    if item.get("category"):
        compact["category"] = item["category"]
    ticket = item.get("ticketInfo", {})
    if ticket and ticket.get("price"):
        compact["ticket"] = f"{ticket.get('ticketName', '门票')}: {ticket['price']}"
    return compact


class FlyaiSearchPOI(BaseSkill):
    """Search attractions, scenic spots, museums, and activities via Fliggy/FlyAI."""

    name = "flyai_search_poi"
    description = (
        "搜索景点、博物馆、游乐园等旅游目的地信息。"
        "返回景点名称、地址、门票价格、图片、预订链接等实时数据。"
        "适用于查找具体城市的景点列表、按类别筛选(博物馆/自然风光/主题乐园等)。"
    )
    parameters = {
        "city_name": {
            "type": "string",
            "description": "城市名称，如'杭州'、'北京'、'贵阳'",
            "required": True,
        },
        "keyword": {
            "type": "string",
            "description": "景点关键词搜索，如'西湖'、'故宫'",
            "required": False,
        },
        "category": {
            "type": "string",
            "description": (
                "景点类别: 自然风光, 山湖田园, 博物馆, 历史古迹, 古镇古村, "
                "主题乐园, 园林花园, 宗教场所, 户外活动, 温泉, 滑雪 等"
            ),
            "required": False,
        },
    }

    def execute(self, city_name: str, keyword: Optional[str] = None, category: Optional[str] = None, **kwargs) -> dict:
        args = ["--city-name", city_name]
        if keyword:
            args.extend(["--keyword", keyword])
        if category:
            args.extend(["--category", category])

        result = _run_flyai("search-poi", args)
        if "error" in result:
            return result

        items = _extract_items(result)
        compacted = [_compact_item(it) for it in items[:15]]
        return {
            "query": {"city": city_name, "keyword": keyword, "category": category},
            "count": len(compacted),
            "results": compacted,
            "systemMessage": result.get("systemMessage", ""),
        }


class FlyaiSearchHotel(BaseSkill):
    """Search hotels, homestays, and accommodations via Fliggy/FlyAI."""

    name = "flyai_search_hotel"
    description = (
        "搜索酒店、民宿、客栈等住宿信息。"
        "返回酒店名称、地址、星级、价格、图片、预订链接等实时数据。"
        "支持按目的地、入住日期、价格上限、星级、附近景点等筛选。"
    )
    parameters = {
        "dest_name": {
            "type": "string",
            "description": "目的地城市或区域名称，如'杭州西湖'、'贵阳'",
            "required": True,
        },
        "poi_name": {
            "type": "string",
            "description": "附近景点名称，如'西湖'、'黄果树'，用于搜索景点周边酒店",
            "required": False,
        },
        "max_price": {
            "type": "integer",
            "description": "最高价格(元/晚)，如500",
            "required": False,
        },
        "hotel_stars": {
            "type": "string",
            "description": "酒店星级，逗号分隔，如'4,5'表示四星五星",
            "required": False,
        },
        "check_in_date": {
            "type": "string",
            "description": "入住日期 YYYY-MM-DD",
            "required": False,
        },
        "check_out_date": {
            "type": "string",
            "description": "离店日期 YYYY-MM-DD",
            "required": False,
        },
    }

    def execute(
        self,
        dest_name: str,
        poi_name: Optional[str] = None,
        max_price: Optional[int] = None,
        hotel_stars: Optional[str] = None,
        check_in_date: Optional[str] = None,
        check_out_date: Optional[str] = None,
        **kwargs,
    ) -> dict:
        args = ["--dest-name", dest_name]
        if poi_name:
            args.extend(["--poi-name", poi_name])
        if max_price:
            args.extend(["--max-price", str(max_price)])
        if hotel_stars:
            args.extend(["--hotel-stars", hotel_stars])
        if check_in_date:
            args.extend(["--check-in-date", check_in_date])
        if check_out_date:
            args.extend(["--check-out-date", check_out_date])

        result = _run_flyai("search-hotel", args)
        if "error" in result:
            return result

        items = _extract_items(result)
        compacted = [_compact_item(it) for it in items[:15]]
        return {
            "query": {"dest": dest_name, "poi": poi_name},
            "count": len(compacted),
            "results": compacted,
            "systemMessage": result.get("systemMessage", ""),
        }


class FlyaiKeywordSearch(BaseSkill):
    """Broad keyword search across all travel categories via Fliggy/FlyAI."""

    name = "flyai_keyword_search"
    description = (
        "飞猪关键词综合搜索，覆盖酒店、机票、景点、跟团游、签证等所有品类。"
        "一个查询搜索所有品类，返回标题、图片、价格、预订链接。"
        "适用于'某地有什么好玩的'、'某地美食推荐'等开放式查询。"
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "搜索关键词，如'贵州酸汤鱼'、'贵阳周边一日游'、'黄果树附近酒店'",
            "required": True,
        },
    }

    def execute(self, query: str, **kwargs) -> dict:
        result = _run_flyai("keyword-search", ["--query", query])
        if "error" in result:
            return result

        items = _extract_items(result)
        results = []
        for it in items[:15]:
            info = it.get("info", it)
            results.append({
                "title": info.get("title", ""),
                "price": info.get("price", ""),
                "url": info.get("jumpUrl", ""),
                "image": info.get("picUrl", ""),
                "rating": info.get("scoreDesc", ""),
            })
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "systemMessage": result.get("systemMessage", ""),
        }


class FlyaiAISearch(BaseSkill):
    """AI-powered semantic travel search returning rich structured results."""

    name = "flyai_ai_search"
    description = (
        "飞猪AI智能搜索，理解复杂自然语言意图，返回结构化推荐结果。"
        "返回包含名称、亮点、推荐理由、注意事项、预订链接等信息的Markdown格式结果。"
        "适用于'帮我规划3天杭州行程，预算2000'、'推荐适合亲子的北京景点'等复杂查询。"
    )
    parameters = {
        "query": {
            "type": "string",
            "description": (
                "自然语言查询，越具体越好。如'3天贵阳周边自驾游推荐景点和酒店，"
                "预算人均2000，喜欢自然风光'"
            ),
            "required": True,
        },
    }

    def execute(self, query: str, **kwargs) -> dict:
        result = _run_flyai("ai-search", ["--query", query])
        if "error" in result:
            return result

        data = result.get("data", "")
        return {
            "query": query,
            "content": data,  # Rich markdown results
            "systemMessage": result.get("systemMessage", ""),
        }
