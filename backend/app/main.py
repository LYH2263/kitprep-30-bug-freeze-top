from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.database import SessionLocal, engine
from app.services.schema_init import ensure_system_setting, run_light_migrations
from app.services.seed import ensure_seed_extras, seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_light_migrations(engine)
    db = SessionLocal()
    try:
        ensure_system_setting(db)
        if settings.seed_on_empty:
            seed_if_empty(db)
            ensure_seed_extras(db)
    finally:
        db.close()
    yield


app = FastAPI(title="KitPrep", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
