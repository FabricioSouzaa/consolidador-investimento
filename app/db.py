from typing import Any, Dict, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import DATABASE_URL


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Postgres atrás do pooler do Supabase (modo transaction) + funções serverless do Vercel:
    # o pooler já gerencia as conexões (NullPool) e não suporta prepared statements.
    kwargs: Dict[str, Any] = {
        "poolclass": NullPool,
        "connect_args": {"prepare_threshold": None, "connect_timeout": 10},
    }
    try:
        return create_engine(url, **kwargs)
    except ArgumentError:
        # A mensagem original do SQLAlchemy inclui a URL inteira (com a senha).
        raise RuntimeError(
            "DATABASE_URL inválida. Senhas com caracteres especiais (@, #, %) "
            "precisam ser codificadas na URL."
        ) from None


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
