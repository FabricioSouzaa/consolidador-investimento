from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import importer
from app.db import Base, get_session
from app.main import app

FIXTURE_TEXT = (Path(__file__).parent / "fixtures" / "extrato_btg_sintetico.txt").read_text()


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture()
def client(session, monkeypatch):
    # O PDF real não vai pro repositório: os testes injetam o texto sintético já extraído.
    monkeypatch.setattr(importer, "extract_text", lambda _content: FIXTURE_TEXT)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()
