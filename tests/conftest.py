import time
from pathlib import Path
from typing import Any, Dict

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import importer
from app.db import Base, get_session
from app.main import app

FIXTURE_TEXT = (Path(__file__).parent / "fixtures" / "extrato_btg_sintetico.txt").read_text()

SUPABASE_URL = "https://proj.supabase.co"
JWT_SECRET = "segredo-de-teste-com-pelo-menos-32-bytes!!"
USER_A = {"sub": "11111111-1111-1111-1111-111111111111", "email": "a@example.com"}
USER_B = {"sub": "22222222-2222-2222-2222-222222222222", "email": "b@example.com"}


def make_token(
    user: Dict[str, str] = USER_A,
    secret: str = JWT_SECRET,
    algorithm: str = "HS256",
    expires_in: int = 3600,
    **overrides: Any,
) -> str:
    claims: Dict[str, Any] = {
        **user,
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": int(time.time()) + expires_in,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm)


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key-de-teste")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("ALLOWED_EMAILS", "a@example.com,b@example.com")


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture()
def anon_client(session, monkeypatch):
    # O PDF real não vai pro repositório: os testes injetam o texto sintético já extraído.
    monkeypatch.setattr(importer, "extract_text", lambda _content: FIXTURE_TEXT)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def client(anon_client):
    """Cliente já autenticado como o usuário A."""
    anon_client.cookies.set("sb_access", make_token(USER_A))
    return anon_client


def client_for(session, user: Dict[str, str]) -> TestClient:
    other = TestClient(app, follow_redirects=False)
    other.cookies.set("sb_access", make_token(user))
    return other
