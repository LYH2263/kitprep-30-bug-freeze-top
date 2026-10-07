"""build_prep 两套互斥写模型的纯函数测试（无需数据库）。"""
import pytest

from app.services.bom_engine import build_prep, result_to_dict


def _ings():
    # id 1/2/3 鲜品；4 冻品（BOM 中出现）；5 冻品（无 BOM 引用，纯冻池）；6 未标记
    return {
        1: {"code": "F1", "name": "鲜1", "unit": "kg", "stock_qty": 1.0, "storage_type": "fresh"},
        2: {"code": "F2", "name": "鲜2", "unit": "kg", "stock_qty": 3.0, "storage_type": "fresh"},
        3: {"code": "F3", "name": "鲜3", "unit": "kg", "stock_qty": 0.0, "storage_type": "fresh"},
        4: {"code": "Z1", "name": "冻1", "unit": "kg", "stock_qty": 100.0, "storage_type": "frozen"},
        5: {"code": "Z2", "name": "冻2", "unit": "kg", "stock_qty": 5.0, "storage_type": "frozen"},
        6: {"code": "N1", "name": "未标", "unit": "kg", "stock_qty": 0.0, "storage_type": None},
    }


def _order_bom():
    # 一份菜需要：鲜1=3（毛缺2）、鲜2=3（足，0）、鲜3=2（毛缺2）、冻1=10（足，0）、未标=1（毛缺1）
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 3.0},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 3.0},
        {"dish_id": 1, "ingredient_id": 3, "qty_per_portion": 2.0},
        {"dish_id": 1, "ingredient_id": 4, "qty_per_portion": 10.0},
        {"dish_id": 1, "ingredient_id": 6, "qty_per_portion": 1.0},
    ]
    return order_lines, bom


def test_forbidden_ignores_frozen_stock_completely():
    order_lines, bom = _order_bom()
    base = _ings()
    r1 = build_prep(order_lines, bom, base, allow_frozen_substitute=False)
    flooded = {**base, 4: {**base[4], "stock_qty": 999.0}, 5: {**base[5], "stock_qty": 999.0}}
    r2 = build_prep(order_lines, bom, flooded, allow_frozen_substitute=False)
    # 冻仓再多，禁替模型的缺料贴/统计/鲜品行必须一致——鲜缺不许被冻仓抹成 0
    assert r1.entries == r2.entries
    assert r1.stats == r2.stats
    fresh1 = [l for l in r1.lines if l.storage_type == "fresh"]
    fresh2 = [l for l in r2.lines if l.storage_type == "fresh"]
    assert fresh1 == fresh2

    by_id = {l.ingredient_id: l for l in r1.lines}
    assert by_id[1].shortage == 2.0          # 鲜1 毛缺全额
    assert by_id[3].shortage == 2.0          # 鲜3 毛缺全额
    assert by_id[1].covered_qty == 0.0
    assert r1.mode == "forbidden"
    assert r1.stats["frozen_pool"] == 0.0
    assert r1.stats["covered_by_frozen"] == 0.0
    assert r1.stats["fresh_gross_total"] == 4.0
    assert r1.stats["fresh_net_total"] == 4.0

    entry_ids = {e.ingredient_id for e in r1.entries}
    assert entry_ids == {1, 3, 6}            # 鲜缺 + 未标普通缺料；充足行不写
    assert {e.ingredient_id for e in r1.entries if e.storage_type == "fresh"} == {1, 3}


def test_forbidden_frozen_and_unmarked_own_shortage():
    # 冻品自身库存不足时按本行账正常写贴
    ings = _ings()
    ings[4]["stock_qty"] = 2.0  # 冻1 需 10，缺 8
    order_lines, bom = _order_bom()
    r = build_prep(order_lines, bom, ings, allow_frozen_substitute=False)
    by_id = {l.ingredient_id: l for l in r.lines}
    assert by_id[4].shortage == 8.0
    assert 4 in {e.ingredient_id for e in r.entries}


def test_allowed_pool_partial_coverage_in_id_order():
    order_lines, bom = _order_bom()
    ings = _ings()
    ings[5]["stock_qty"] = 3.0  # 冻池 = 100(frozen Z1 本行用 10 仍余 90)…实际 Z1 有 100
    # Z1 库存 100 全进池 → 池=103，足够覆盖全部鲜缺 4。改为压小池验证顺序分配：
    ings[4]["stock_qty"] = 0.0  # 冻1 自身缺 10，同时其库存 0 进池
    ings[5]["stock_qty"] = 3.0  # 池=3：鲜1(id=1)毛缺2 全覆盖，鲜3(id=3)只覆盖1、净缺1
    r = build_prep(order_lines, bom, ings, allow_frozen_substitute=True)
    assert r.mode == "allowed_frozen"
    assert r.stats["frozen_pool"] == 3.0
    by_id = {l.ingredient_id: l for l in r.lines}
    assert by_id[1].covered_qty == 2.0 and by_id[1].shortage == 0.0
    assert by_id[3].covered_qty == 1.0 and by_id[3].shortage == 1.0
    assert r.stats["covered_by_frozen"] == 3.0
    assert r.stats["fresh_net_total"] == 1.0
    # 全覆盖的鲜1 不写贴；鲜3 仍写
    assert {e.ingredient_id for e in r.entries if e.storage_type == "fresh"} == {3}


def test_allowed_pool_covers_all_fresh_shortage():
    order_lines, bom = _order_bom()
    r = build_prep(order_lines, bom, _ings(), allow_frozen_substitute=True)
    # 冻池 105 覆盖全部鲜毛缺 4
    assert r.stats["fresh_gross_total"] == 4.0
    assert r.stats["fresh_net_total"] == 0.0
    assert {e.ingredient_id for e in r.entries if e.storage_type == "fresh"} == set()
    # 未标缺料不受冻池影响，仍写贴
    assert 6 in {e.ingredient_id for e in r.entries}
    d = result_to_dict(r, {"id": 1})
    assert all(s["storage_type"] != "fresh" for s in d["shortages"])


def test_allowed_pool_includes_unreferenced_frozen():
    order_lines, bom = _order_bom()
    ings = _ings()
    ings[4]["stock_qty"] = 0.0   # BOM 中冻品无库存
    ings[5]["stock_qty"] = 4.0   # 仅靠无 BOM 引用冻品构成池
    r = build_prep(order_lines, bom, ings, allow_frozen_substitute=True)
    assert r.stats["frozen_pool"] == 4.0
    assert r.stats["fresh_net_total"] == 0.0


def test_non_bool_switch_raises():
    order_lines, bom = _order_bom()
    for bad in ("true", "false", 1, 0, None):
        with pytest.raises(TypeError):
            build_prep(order_lines, bom, _ings(), allow_frozen_substitute=bad)


def test_unmarked_behaves_like_legacy():
    # 未标记原料 + 无开关语义：旧公式 max(0, need-stock)
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    r = build_prep(order_lines, bom, ings, allow_frozen_substitute=False)
    assert r.lines[0].storage_type is None
    assert r.lines[0].shortage == 0.0
    assert r.entries == []
