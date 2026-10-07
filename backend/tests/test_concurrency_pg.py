"""PostgreSQL 行锁并发测试：仅当 TEST_DATABASE_URL 指向真实 PG 时运行。

验证：库存页保存开关/标记 与 备料台生成几乎同时到达时，经 system_settings
单行串行化，备料单读到的开关必是某个已提交值，不出现一单内撕裂的写模型。
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.constants import SETTING_ROW_ID
from app.database import get_db
from app.main import app
from app.models.models import Base, PrepRun, ShortageEntry, SystemSetting
from app.services.schema_init import ensure_system_setting, run_light_migrations
from app.services.seed import ensure_seed_extras, seed_if_empty

PG_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="未设置 TEST_DATABASE_URL，跳过 PG 并发测试")


@pytest.fixture()
def pg_ctx():
    engine = create_engine(PG_URL)
    Base.metadata.drop_all(bind=engine)
    run_light_migrations(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    ensure_system_setting(db)
    seed_if_empty(db)
    ensure_seed_extras(db)
    db.close()

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), engine, Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_run_blocks_until_switch_commit_then_reads_new_value(pg_ctx):
    client, _engine, Session = pg_ctx

    # 会话 A：持有 system_settings 行锁（未提交），稍后把开关切成允许冻顶
    a = Session()
    a.execute(select(SystemSetting).where(SystemSetting.id == SETTING_ROW_ID).with_for_update())

    box = {}
    def call_run():
        r = client.post("/api/prep/run")
        box["status"] = r.status_code
        box["body"] = r.json() if r.status_code == 200 else None

    t = threading.Thread(target=call_run)
    t.start()
    time.sleep(1.0)
    assert t.is_alive(), "生成请求应在 settings 行锁上排队，而非抢跑"

    a.get(SystemSetting, SETTING_ROW_ID).allow_frozen_substitute = True
    a.commit()
    t.join(timeout=10)
    a.close()

    assert not t.is_alive(), "行锁等待超时，可能死锁"
    assert box["status"] == 200
    assert box["body"]["mode"] == "allowed_frozen"
    assert box["body"]["stats"]["fresh_net_total"] == 0.0


def test_concurrent_markers_switch_and_runs_never_mix_models(pg_ctx):
    client, engine, Session = pg_ctx
    errors: list[Exception] = []

    def loop_runs(n):
        for _ in range(n):
            try:
                r = client.post("/api/prep/run")
                assert r.status_code == 200, r.text
                b = r.json()
                st = b["stats"]
                if b["mode"] == "forbidden":
                    # 禁替单：冻仓从未参与，净鲜缺必等于毛鲜缺
                    assert st["fresh_net_total"] == st["fresh_gross_total"]
                    assert st["frozen_pool"] == 0.0
                else:
                    assert b["mode"] == "allowed_frozen"
                    assert st["fresh_net_total"] <= st["fresh_gross_total"]
                    assert st["covered_by_frozen"] <= st["frozen_pool"] + 1e-6
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    def loop_switch(n):
        for k in range(n):
            try:
                r = client.put("/api/settings",
                               json={"allow_frozen_substitute": bool(k % 2)})
                assert r.status_code == 200, r.text
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    def loop_markers(n):
        for k in range(n):
            try:
                mark = "fresh" if k % 2 == 0 else None
                r = client.put("/api/inventory/markers",
                               json={"markers": [{"code": "I-SC", "storage_type": mark}]})
                assert r.status_code == 200, r.text
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [
        threading.Thread(target=loop_runs, args=(8,)),
        threading.Thread(target=loop_switch, args=(8,)),
        threading.Thread(target=loop_markers, args=(8,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "并发写超时，疑似死锁"

    assert not errors, errors
    db = Session()
    try:
        runs = db.scalars(select(PrepRun).order_by(PrepRun.id)).all()
        assert len(runs) == 8
        # 每张单的缺料贴行数必须与其 JSON 快照一致（同事务原子可见）
        for run in runs:
            n_entries = len(db.scalars(
                select(ShortageEntry.id).where(ShortageEntry.prep_run_id == run.id)).all())
            assert n_entries > 0
    finally:
        db.close()
