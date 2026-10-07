from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from app.constants import STORAGE_FRESH, STORAGE_FROZEN
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine

# 经典种子原料中按业务标鲜的编码；大米/面条/生抽/食用油不标
SEED_FRESH_CODES = ("I-PR", "I-EG", "I-CK")
# 新增冻品：不挂任何 BOM，只构成冻仓总量池
SEED_FROZEN_EXTRA = ("I-FZ", "冷冻备用五花肉", "kg", 30.0)

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Dish)) or 0) > 0:
        return
    dishes = [("D-HS", "红烧肉套餐"), ("D-YC", "鱼香茄子"), ("D-JT", "鸡汤面")]
    dish_ids = {}
    for code, name in dishes:
        d = Dish(code=code, name=name, portion_unit="份")
        db.add(d); db.flush(); dish_ids[code] = d.id
    ings = [
        ("I-PR", "五花肉", "kg", 8.0, STORAGE_FRESH),
        ("I-EG", "茄子", "kg", 3.0, STORAGE_FRESH),
        ("I-CK", "鸡肉", "kg", 5.0, STORAGE_FRESH),
        ("I-RC", "大米", "kg", 20.0, None),
        ("I-ND", "面条", "kg", 4.0, None),
        ("I-SC", "生抽", "L", 2.0, None),
        ("I-OL", "食用油", "L", 1.5, None),
        ("I-FZ", SEED_FROZEN_EXTRA[1], SEED_FROZEN_EXTRA[2], SEED_FROZEN_EXTRA[3], STORAGE_FROZEN),
    ]
    ing_ids = {}
    for code, name, unit, stock, storage_type in ings:
        i = Ingredient(code=code, name=name, unit=unit, stock_qty=stock, storage_type=storage_type)
        db.add(i); db.flush(); ing_ids[code] = i.id
    bom = [
        ("D-HS", "I-PR", 0.25), ("D-HS", "I-RC", 0.15), ("D-HS", "I-SC", 0.02), ("D-HS", "I-OL", 0.03),
        ("D-YC", "I-EG", 0.3), ("D-YC", "I-RC", 0.15), ("D-YC", "I-SC", 0.015), ("D-YC", "I-OL", 0.025),
        ("D-JT", "I-CK", 0.12), ("D-JT", "I-ND", 0.2), ("D-JT", "I-SC", 0.01),
    ]
    for dcode, icode, qty in bom:
        db.add(BomLine(dish_id=dish_ids[dcode], ingredient_id=ing_ids[icode], qty_per_portion=qty))
    order = KitchenOrder(code="KO-0901", outlet="城西门店", status="open")
    db.add(order); db.flush()
    for dcode, portions in [("D-HS", 40), ("D-YC", 30), ("D-JT", 50)]:
        db.add(OrderLine(order_id=order.id, dish_id=dish_ids[dcode], portions=portions))
    db.commit()

def ensure_seed_extras(db: Session) -> None:
    """旧库（seed_if_empty 已跳过）幂等补齐鲜冻标记与冻品，绝不覆盖用户已保存的标记。"""
    code, name, unit, stock = SEED_FROZEN_EXTRA
    exists = db.scalar(select(Ingredient.id).where(Ingredient.code == code))
    if not exists:
        db.add(Ingredient(code=code, name=name, unit=unit, stock_qty=stock, storage_type=STORAGE_FROZEN))
    db.execute(
        update(Ingredient)
        .where(Ingredient.code.in_(SEED_FRESH_CODES), Ingredient.storage_type.is_(None))
        .values(storage_type=STORAGE_FRESH)
    )
    db.commit()
