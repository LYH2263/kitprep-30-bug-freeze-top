from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import STORAGE_FRESH, STORAGE_FROZEN, STORAGE_TYPES
from app.database import get_db
from app.models.models import Ingredient
from app.services.prep_runner import acquire_write_locks

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _row(i: Ingredient) -> dict:
    return {
        "id": i.id,
        "code": i.code,
        "name": i.name,
        "unit": i.unit,
        "stock_qty": i.stock_qty,
        "storage_type": i.storage_type,
    }


def _inventory_payload(ingredients: list[Ingredient]) -> dict:
    rows = [_row(i) for i in ingredients]
    return {
        "items": rows,
        "fresh_stock_total": round(
            sum(i.stock_qty for i in ingredients if i.storage_type == STORAGE_FRESH), 3
        ),
        "frozen_stock_total": round(
            sum(i.stock_qty for i in ingredients if i.storage_type == STORAGE_FROZEN), 3
        ),
    }


@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    ingredients = db.scalars(select(Ingredient).order_by(Ingredient.id)).all()
    return _inventory_payload(list(ingredients))


@router.put("/markers")
def update_markers(payload: dict = Body(...), db: Session = Depends(get_db)):
    """整批保存鲜/冻标记。任何一项非法 → 400，四处全部停在保存前。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("markers"), list):
        raise HTTPException(400, "请求体必须是 {markers: [{code, storage_type}]}")
    markers = payload["markers"]

    # —— 纯载荷校验（不持锁、不写库）——
    seen: set[str] = set()
    duplicate: list[str] = []
    for m in markers:
        if not isinstance(m, dict) or "code" not in m or "storage_type" not in m:
            raise HTTPException(400, "每项必须包含 code 与 storage_type")
        code, storage_type = m["code"], m["storage_type"]
        if not isinstance(code, str) or not code:
            raise HTTPException(400, "code 必须是非空字符串")
        if storage_type is not None and storage_type not in STORAGE_TYPES:
            raise HTTPException(400, f"storage_type 非法：{storage_type!r}（只允许 fresh/frozen/null）")
        if code in seen:
            duplicate.append(code)
        seen.add(code)
    if duplicate:
        raise HTTPException(400, f"批次内存在重复编码：{sorted(set(duplicate))}")

    try:
        acquire_write_locks(db, ingredient_ids=[])  # 先占单行串行点
        ingredients = db.scalars(
            select(Ingredient).where(Ingredient.code.in_(seen)).order_by(Ingredient.id)
        ).all() if seen else []
        found = {i.code: i for i in ingredients}
        unknown = sorted(seen - found.keys())
        if unknown:
            db.rollback()
            raise HTTPException(400, f"编码对不上现有原料：{unknown}")

        wanted = {m["code"]: m["storage_type"] for m in markers}
        for code, ing in found.items():
            ing.storage_type = wanted[code]
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "保存标记失败，已回滚")

    all_rows = db.scalars(select(Ingredient).order_by(Ingredient.id)).all()
    return {"updated": len(markers), **_inventory_payload(list(all_rows))}
