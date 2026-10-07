"""备料单生成编排：统一加锁顺序、单事务提交。

写模型并发约束（必须长期遵守）：
- 所有写操作（生成备料单、保存开关、保存鲜冻标记，以及将来的开单/关单）
  都必须先锁 system_settings 单行，再按 ingredient id 升序锁原料行。
- 单行串行点保证写者之间锁等待图不成环（无死锁），且生成时读到的
  「允许冻顶鲜」开关必是某个已提交值——禁止一单内一边禁替一边允许替。
"""
from __future__ import annotations
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import SETTING_ROW_ID
from app.models.models import (
    BomLine,
    Ingredient,
    KitchenOrder,
    OrderLine,
    PrepRun,
    ShortageEntry,
    SystemSetting,
)
from app.services.bom_engine import build_prep, result_to_dict


def _is_postgres(db: Session) -> bool:
    return db.bind.dialect.name == "postgresql"


def acquire_write_locks(
    db: Session,
    *,
    lock_all_ingredients: bool = False,
    ingredient_ids: list[int] | None = None,
) -> SystemSetting:
    """① 锁 system_settings 单行 → ② 按 id 升序锁原料行（PostgreSQL 行锁）。"""
    settings_stmt = select(SystemSetting).where(SystemSetting.id == SETTING_ROW_ID)
    if _is_postgres(db):
        settings_stmt = settings_stmt.with_for_update()
    setting = db.scalars(settings_stmt).first()
    if setting is None:  # 迁移未执行/数据损坏
        raise HTTPException(500, "系统设置未初始化")

    if lock_all_ingredients:
        ing_stmt = select(Ingredient).order_by(Ingredient.id)
        if _is_postgres(db):
            ing_stmt = ing_stmt.with_for_update()
        db.scalars(ing_stmt).all()
    elif ingredient_ids:
        ing_stmt = (
            select(Ingredient)
            .where(Ingredient.id.in_(sorted(set(ingredient_ids))))
            .order_by(Ingredient.id)
        )
        if _is_postgres(db):
            ing_stmt = ing_stmt.with_for_update()
        db.scalars(ing_stmt).all()
    return setting


def _load_open_order(db: Session) -> KitchenOrder:
    """当前有效单 = 唯一 status='open' 的订单；0 张或多张都无法确定。"""
    orders = db.scalars(
        select(KitchenOrder).where(KitchenOrder.status == "open").order_by(KitchenOrder.id)
    ).all()
    if len(orders) == 0:
        raise HTTPException(409, "当前没有有效单（open），无法生成备料单")
    if len(orders) > 1:
        raise HTTPException(409, "存在多张有效单（open），无法确定当前单")
    return orders[0]


def generate_prep_run(db: Session) -> tuple[PrepRun, dict]:
    """单事务生成当前有效单的备料单 + 缺料贴。全程不写 stock_qty（不扣账）。"""
    setting = acquire_write_locks(db, lock_all_ingredients=True)
    try:
        order = _load_open_order(db)
        ols = [
            {"dish_id": l.dish_id, "portions": l.portions}
            for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()
        ]
        bom = [
            {"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
            for b in db.scalars(select(BomLine)).all()
        ]
        ingredients = {
            i.id: {
                "code": i.code,
                "name": i.name,
                "unit": i.unit,
                "stock_qty": i.stock_qty,
                "storage_type": i.storage_type,
            }
            for i in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()
        }
        # 只传已提交的布尔值；未保存的 UI 开关状态没有通道进入这里。
        result = build_prep(
            ols, bom, ingredients,
            allow_frozen_substitute=True,
        )
        order_meta = {"id": order.id, "code": order.code, "outlet": order.outlet}
        payload = result_to_dict(result, order_meta)
        run = PrepRun(
            order_id=order.id,
            mode=result.mode,
            result_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(run)
        db.flush()  # 取 run.id，供缺料贴同事务写入
        for e in result.entries:
            db.add(ShortageEntry(
                prep_run_id=run.id,
                ingredient_id=e.ingredient_id,
                code=e.code,
                name=e.name,
                unit=e.unit,
                storage_type=e.storage_type,
                need_qty=e.need_qty,
                stock_qty=e.stock_qty,
                gross_shortage=e.gross_shortage,
                covered_qty=e.covered_qty,
                shortage_qty=e.shortage_qty,
            ))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "生成备料单失败，鲜仓账/冻仓账/当前单/缺料贴均已回滚")
    return run, payload
