"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients.

鲜/冻分账两套互斥写模型（见 app.constants）：
- forbidden（禁替）：鲜缺只跟鲜仓账。鲜品本行 stock_qty 即鲜仓库存，
  冻仓数据在禁替分支里根本不参与计算（不构建冻池）。
- allowed_frozen（允许冻顶鲜）：冻仓总量池 = 全部冻品 stock_qty 之和
  （含未被任何 BOM 引用的冻品），按 ingredient_id 升序冲减鲜品毛缺。
  注意：冻品库存"一物两用"——冻品若出现在 BOM 中，既按本行库存算其
  自身缺料，又全额计入冻池，这是业务规定。
未标记原料（storage_type=None）鲜冻不区分，永远只按本行账算缺。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

from app.constants import MODE_ALLOWED, MODE_FORBIDDEN, STORAGE_FRESH, STORAGE_FROZEN

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float
    storage_type: str | None = None

@dataclass
class PrepLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    storage_type: str | None
    need_qty: float
    stock_qty: float
    gross_shortage: float   # 毛缺 = max(0, need − 本行库存)
    covered_qty: float      # 冻仓池冲减量（仅 allowed_frozen 鲜行可能 >0）
    shortage: float         # 净缺（缺料贴口径）

@dataclass
class ShortageEntryData:
    """与 shortage_entries 表列一一对应的写入投影。"""
    ingredient_id: int
    code: str
    name: str
    unit: str
    storage_type: str | None
    need_qty: float
    stock_qty: float
    gross_shortage: float
    covered_qty: float
    shortage_qty: float

@dataclass
class PrepResult:
    mode: str
    lines: list[PrepLine]
    entries: list[ShortageEntryData]
    stats: dict

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion."""
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
            storage_type=ing.get("storage_type"),
        ))
    return lines

def _to_entry(line: PrepLine) -> ShortageEntryData:
    return ShortageEntryData(
        ingredient_id=line.ingredient_id,
        code=line.ingredient_code,
        name=line.ingredient_name,
        unit=line.unit,
        storage_type=line.storage_type,
        need_qty=line.need_qty,
        stock_qty=line.stock_qty,
        gross_shortage=line.gross_shortage,
        covered_qty=line.covered_qty,
        shortage_qty=line.shortage,
    )

def _base_stats(lines: list[PrepLine]) -> dict:
    return {
        "ingredient_count": len(lines),
        "shortage_count": sum(1 for l in lines if l.shortage > 0),
        "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
    }

def _build_forbidden(merged: list[NeedLine]) -> PrepResult:
    """禁替模型：鲜/冻/未标一律只按本行账，冻仓在本分支内不存在。"""
    lines: list[PrepLine] = []
    entries: list[ShortageEntryData] = []
    for m in merged:
        line = PrepLine(
            ingredient_id=m.ingredient_id,
            ingredient_code=m.ingredient_code,
            ingredient_name=m.ingredient_name,
            unit=m.unit,
            storage_type=m.storage_type,
            need_qty=m.need_qty,
            stock_qty=m.stock_qty,
            gross_shortage=m.shortage,
            covered_qty=0.0,
            shortage=m.shortage,
        )
        lines.append(line)
        if line.shortage > 0:
            entries.append(_to_entry(line))
    fresh_gross = round(sum(l.gross_shortage for l in lines if l.storage_type == STORAGE_FRESH), 3)
    stats = {
        **_base_stats(lines),
        "fresh_gross_total": fresh_gross,
        "fresh_net_total": fresh_gross,
        "frozen_pool": 0.0,
        "covered_by_frozen": 0.0,
    }
    return PrepResult(mode=MODE_FORBIDDEN, lines=lines, entries=entries, stats=stats)

def _build_allowed(merged: list[NeedLine], ingredients: dict[int, dict]) -> PrepResult:
    """允许冻顶鲜模型：冻仓总量池按 ingredient_id 升序冲减鲜品毛缺。"""
    # 池取自完整原料账：含未被 BOM 引用的冻品。
    pool = round(
        sum(float(i.get("stock_qty", 0)) for i in ingredients.values()
            if i.get("storage_type") == STORAGE_FROZEN),
        3,
    )
    remain = pool
    lines: list[PrepLine] = []
    entries: list[ShortageEntryData] = []
    for m in merged:  # explode_and_merge 已按 ingredient_id 升序
        cover = 0.0
        if m.storage_type == STORAGE_FRESH and m.shortage > 0:
            cover = round(min(m.shortage, remain), 3)
            remain = round(remain - cover, 3)
        net = round(m.shortage - cover, 3)
        line = PrepLine(
            ingredient_id=m.ingredient_id,
            ingredient_code=m.ingredient_code,
            ingredient_name=m.ingredient_name,
            unit=m.unit,
            storage_type=m.storage_type,
            need_qty=m.need_qty,
            stock_qty=m.stock_qty,
            gross_shortage=m.shortage,
            covered_qty=cover,
            shortage=net,
        )
        lines.append(line)
        if line.shortage > 0:  # 被冻池全覆盖（净缺=0）的鲜行不写贴
            entries.append(_to_entry(line))
    fresh_gross = round(sum(l.gross_shortage for l in lines if l.storage_type == STORAGE_FRESH), 3)
    fresh_net = round(sum(l.shortage for l in lines if l.storage_type == STORAGE_FRESH), 3)
    stats = {
        **_base_stats(lines),
        "fresh_gross_total": fresh_gross,
        "fresh_net_total": fresh_net,
        "frozen_pool": pool,
        "covered_by_frozen": round(pool - remain, 3),
    }
    return PrepResult(mode=MODE_ALLOWED, lines=lines, entries=entries, stats=stats)

def build_prep(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
    allow_frozen_substitute: bool,
) -> PrepResult:
    """按已保存的开关值只走一套写模型。两个分支互斥，禁止各算一遍再合成。"""
    if type(allow_frozen_substitute) is not bool:
        raise TypeError("allow_frozen_substitute 必须是严格布尔值")
    merged = explode_and_merge(order_lines, bom_lines, ingredients)
    if allow_frozen_substitute:
        return _build_allowed(merged, ingredients)
    return _build_forbidden(merged)

def result_to_dict(result: PrepResult, order: dict) -> dict:
    shortage_ids = {e.ingredient_id for e in result.entries}
    return {
        "schema": 2,
        "mode": result.mode,
        "order": order,
        "prep_lines": [asdict(l) for l in result.lines],
        "shortages": [asdict(l) for l in result.lines if l.ingredient_id in shortage_ids],
        "stats": result.stats,
    }
