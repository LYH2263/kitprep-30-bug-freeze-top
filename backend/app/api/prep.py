import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import PrepRun, ShortageEntry
from app.services.prep_runner import generate_prep_run
router = APIRouter(prefix="/prep", tags=["prep"])


def _entry_dict(e: ShortageEntry) -> dict:
    return {
        "ingredient_id": e.ingredient_id,
        "ingredient_code": e.code,
        "ingredient_name": e.name,
        "unit": e.unit,
        "storage_type": e.storage_type,
        "need_qty": e.need_qty,
        "stock_qty": e.stock_qty,
        "gross_shortage": e.gross_shortage,
        "covered_qty": e.covered_qty,
        "shortage": e.shortage_qty,
    }


@router.post("/run")
def run_prep(db: Session = Depends(get_db)):
    """只出当前有效单；不扣减库存。失败四处回滚（在 prep_runner 内完成）。"""
    run, payload = generate_prep_run(db)
    return {"id": run.id, "created_at": run.created_at.isoformat(), **payload}


@router.get("/latest")
def latest(db: Session = Depends(get_db)):
    run = db.scalars(select(PrepRun).order_by(PrepRun.id.desc())).first()
    if not run:
        raise HTTPException(404, "尚无备料单")
    data = json.loads(run.result_json)
    return {"id": run.id, "created_at": run.created_at.isoformat(), **data}


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PrepRun, run_id)
    if not run:
        raise HTTPException(404, "备料单不存在")
    data = json.loads(run.result_json)
    return {"id": run.id, "created_at": run.created_at.isoformat(), **data}


@router.get("/shortages")
def shortages(db: Session = Depends(get_db)):
    """缺料贴读 shortage_entries 快照投影（不做实时 JOIN，历史贴原样）。"""
    run = db.scalars(select(PrepRun).order_by(PrepRun.id.desc())).first()
    if not run:
        raise HTTPException(404, "尚无备料单")
    entries = db.scalars(
        select(ShortageEntry)
        .where(ShortageEntry.prep_run_id == run.id)
        .order_by(ShortageEntry.id)
    ).all()
    data = json.loads(run.result_json)
    return {
        "run_id": run.id,
        "mode": run.mode,
        "order": data.get("order"),
        "shortages": [_entry_dict(e) for e in entries],
        "stats": data.get("stats", {}),
    }
