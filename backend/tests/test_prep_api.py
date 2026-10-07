"""API 层测试：标记/开关保存校验、不扣账、历史不可变、409/404、回滚。"""
from sqlalchemy import func, select

from app.models.models import (
    Ingredient,
    KitchenOrder,
    PrepRun,
    ShortageEntry,
    SystemSetting,
)


def _stock_snapshot(Session) -> dict:
    db = Session()
    try:
        return {i.code: (i.stock_qty, i.storage_type)
                for i in db.scalars(select(Ingredient)).all()}
    finally:
        db.close()


def _settings_value(Session) -> bool:
    db = Session()
    try:
        return bool(db.get(SystemSetting, 1).allow_frozen_substitute)
    finally:
        db.close()


# ---------- 标记保存 ----------

def test_markers_persist(client, db_session):
    r = client.put("/api/inventory/markers", json={"markers": [
        {"code": "I-RC", "storage_type": "frozen"},
        {"code": "I-SC", "storage_type": None},
    ]})
    assert r.status_code == 200
    assert r.json()["updated"] == 2
    db = db_session()
    try:
        by_code = {i.code: i.storage_type for i in db.scalars(select(Ingredient)).all()}
        assert by_code["I-RC"] == "frozen"
        assert by_code["I-SC"] is None
        assert by_code["I-PR"] == "fresh"  # seed 标记仍在
    finally:
        db.close()


def test_markers_unknown_code_rejects_all(client, db_session):
    before = _stock_snapshot(db_session)
    r = client.put("/api/inventory/markers", json={"markers": [
        {"code": "I-RC", "storage_type": "frozen"},       # 合法
        {"code": "I-NOPE", "storage_type": "fresh"},      # 编码对不上
    ]})
    assert r.status_code == 400
    assert _stock_snapshot(db_session) == before


def test_markers_bad_enum_and_duplicate(client, db_session):
    before = _stock_snapshot(db_session)
    r = client.put("/api/inventory/markers", json={"markers": [
        {"code": "I-RC", "storage_type": "cold"}
    ]})
    assert r.status_code == 400
    r = client.put("/api/inventory/markers", json={"markers": [
        {"code": "I-RC", "storage_type": "fresh"},
        {"code": "I-RC", "storage_type": "frozen"},
    ]})
    assert r.status_code == 400
    assert _stock_snapshot(db_session) == before


def test_inventory_totals(client):
    r = client.get("/api/inventory")
    assert r.status_code == 200
    body = r.json()
    assert body["fresh_stock_total"] == 16.0   # 8 + 3 + 5
    assert body["frozen_stock_total"] == 30.0  # I-FZ


# ---------- 开关 ----------

def test_switch_strict_bool(client, db_session):
    assert client.put("/api/settings", json={"allow_frozen_substitute": True}).status_code == 200
    assert _settings_value(db_session) is True
    assert client.put("/api/settings", json={"allow_frozen_substitute": False}).status_code == 200
    assert _settings_value(db_session) is False
    for bad in ("true", "false", 1, 0):
        r = client.put("/api/settings", json={"allow_frozen_substitute": bad})
        assert r.status_code == 400, bad
        assert _settings_value(db_session) is False


# ---------- 生成：不扣账、分模型、缺料贴 ----------

def test_run_does_not_deduct_stock_and_writes_entries(client, db_session):
    before = _stock_snapshot(db_session)
    r = client.post("/api/prep/run")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "forbidden"
    # 鲜毛缺 = 猪肉2 + 茄子6 + 鸡肉1 = 9；冻仓 30 不得抹 0
    assert body["stats"]["fresh_gross_total"] == 9.0
    assert body["stats"]["fresh_net_total"] == 9.0
    fresh_short = {s["ingredient_code"]: s["shortage"] for s in body["shortages"]
                   if s["storage_type"] == "fresh"}
    assert fresh_short == {"I-PR": 2.0, "I-EG": 6.0, "I-CK": 1.0}
    assert _stock_snapshot(db_session) == before  # 结存前后逐行一致

    db = db_session()
    try:
        run = db.scalars(select(PrepRun).order_by(PrepRun.id.desc())).first()
        assert run.mode == "forbidden"
        entry_codes = {e.code for e in db.scalars(
            select(ShortageEntry).where(ShortageEntry.prep_run_id == run.id)).all()}
        assert {"I-PR", "I-EG", "I-CK", "I-ND", "I-OL"} <= entry_codes
        assert "I-FZ" not in entry_codes
    finally:
        db.close()


def test_switch_on_then_run_covers_fresh_shortage(client, db_session):
    r1 = client.post("/api/prep/run").json()
    id1 = r1["id"]
    assert client.put("/api/settings", json={"allow_frozen_substitute": True}).status_code == 200
    r2 = client.post("/api/prep/run").json()
    assert r2["mode"] == "allowed_frozen"
    assert r2["stats"]["frozen_pool"] == 30.0
    assert r2["stats"]["fresh_net_total"] == 0.0
    assert {s["ingredient_code"] for s in r2["shortages"] if s["storage_type"] == "fresh"} == set()
    # 普通缺料仍在（面条6、油0.45）
    assert {s["ingredient_code"] for s in r2["shortages"]} >= {"I-ND", "I-OL"}

    # 历史第一单原样不变（禁替毛缺）
    hist = client.get(f"/api/prep/runs/{id1}").json()
    assert hist["mode"] == "forbidden"
    assert hist["stats"]["fresh_net_total"] == 9.0
    db = db_session()
    try:
        old_entries = db.scalars(
            select(ShortageEntry).where(ShortageEntry.prep_run_id == id1)
            .order_by(ShortageEntry.id)).all()
        assert sum(e.shortage_qty for e in old_entries if e.storage_type == "fresh") == 9.0
        latest = db.scalars(select(PrepRun).order_by(PrepRun.id.desc())).first()
        assert latest.id == r2["id"]
    finally:
        db.close()


def test_shortages_endpoint_matches_run(client):
    run = client.post("/api/prep/run").json()
    sh = client.get("/api/prep/shortages").json()
    assert sh["run_id"] == run["id"]
    assert [(s["ingredient_id"], s["shortage"]) for s in sh["shortages"]] == \
           [(s["ingredient_id"], s["shortage"]) for s in run["shortages"]]


# ---------- 当前有效单 ----------

def test_no_open_order_409(client, db_session):
    db = db_session()
    try:
        db.query(KitchenOrder).update({KitchenOrder.status: "closed"})
        db.commit()
    finally:
        db.close()
    r = client.post("/api/prep/run")
    assert r.status_code == 409
    db = db_session()
    try:
        assert db.scalar(select(func.count()).select_from(PrepRun)) == 0
    finally:
        db.close()


def test_multiple_open_orders_409(client, db_session):
    db = db_session()
    try:
        db.add(KitchenOrder(code="KO-0902", outlet="二店", status="open"))
        db.commit()
    finally:
        db.close()
    assert client.post("/api/prep/run").status_code == 409


# ---------- 无历史：不得副作用现算 ----------

def test_latest_and_shortages_404_without_run(client, db_session):
    assert client.get("/api/prep/latest").status_code == 404
    assert client.get("/api/prep/shortages").status_code == 404
    db = db_session()
    try:
        assert db.scalar(select(func.count()).select_from(PrepRun)) == 0
        assert db.scalar(select(func.count()).select_from(ShortageEntry)) == 0
    finally:
        db.close()


# ---------- 提交失败四处回滚 ----------

def test_marker_commit_failure_rolls_back(client, db_session, monkeypatch):
    from app.api import inventory as inv_api

    def boom(self):
        raise RuntimeError("commit boom")

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", boom)
    r = client.put("/api/inventory/markers", json={"markers": [
        {"code": "I-RC", "storage_type": "frozen"}]})
    assert r.status_code == 500
    monkeypatch.undo()
    # 新连接视角：标记未落下
    db = db_session()
    try:
        assert db.scalars(select(Ingredient).where(Ingredient.code == "I-RC")).first().storage_type is None
    finally:
        db.close()
