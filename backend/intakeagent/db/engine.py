"""Engine factory and schema init."""

from __future__ import annotations

from sqlalchemy import Engine, text
from sqlmodel import SQLModel, create_engine

from intakeagent.db import models  # noqa: F401  (register tables)


def is_postgres(url: str) -> bool:
    return url.startswith("postgres")


def create_db_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # check_same_thread=False: FastAPI may touch the connection from worker threads.
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    if is_postgres(str(engine.url)):
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    SQLModel.metadata.create_all(engine)
