import os
from collections.abc import Callable

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////app/data/ticorates.db")

# check_same_thread=False: safe for asyncio (single-threaded event loop).
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Creates a short-lived Session per operation; released before any async I/O.
SessionFactory = Callable[[], Session]


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session_factory() -> SessionFactory:
    """FastAPI dependency: returns a factory for creating short-lived DB sessions."""
    return lambda: Session(engine)
