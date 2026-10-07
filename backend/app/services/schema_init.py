"""无 Alembic 的幂等轻量迁移：create_all 建表 + inspect 给旧表补列 + 设置行兜底。

可重复执行；只添加 nullable 列，不改动/删除任何既有数据。
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.constants import SETTING_ROW_ID
from app.models.models import Base, SystemSetting


def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    expected = {
        "ingredients": ("storage_type", "VARCHAR(16)"),
        "prep_runs": ("mode", "VARCHAR(32)"),
    }
    for table, (column, ddl_type) in expected.items():
        if table not in inspector.get_table_names():
            continue  # create_all 会建整表
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def run_light_migrations(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)


def ensure_system_setting(db: Session) -> None:
    """system_settings 单行兜底（id=SETTING_ROW_ID，默认禁替）。"""
    if db.get(SystemSetting, SETTING_ROW_ID) is None:
        db.add(SystemSetting(id=SETTING_ROW_ID, allow_frozen_substitute=False))
        db.commit()
