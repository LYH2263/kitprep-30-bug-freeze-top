from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import SystemSetting
from app.services.prep_runner import acquire_write_locks

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_dict(s: SystemSetting) -> dict:
    return {
        "allow_frozen_substitute": bool(s.allow_frozen_substitute),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    setting = db.get(SystemSetting, 1)
    if setting is None:
        raise HTTPException(500, "系统设置未初始化")
    return _to_dict(setting)


@router.put("")
def put_settings(payload: dict = Body(...), db: Session = Depends(get_db)):
    # 严格布尔：拒绝 "true"/"false"/1/0 等，开关非法时停在保存前
    if not isinstance(payload, dict) or "allow_frozen_substitute" not in payload:
        raise HTTPException(400, "缺少 allow_frozen_substitute")
    value = payload["allow_frozen_substitute"]
    if type(value) is not bool:
        raise HTTPException(400, "allow_frozen_substitute 必须是严格布尔值")
    try:
        setting = acquire_write_locks(db)
        setting.allow_frozen_substitute = value
        # 只影响开关本身：历史备料单是快照（result_json + shortage_entries），
        # 一律钉死，绝不随本次翻开关而改字。
        db.commit()
        db.refresh(setting)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "保存开关失败，已回滚")
    return _to_dict(setting)
