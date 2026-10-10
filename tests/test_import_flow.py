from decimal import Decimal

from sqlalchemy import func, select

from app.models import Movement, Position, Statement

PDF = {"file": ("extrato.pdf", b"%PDF-1.4 conteudo qualquer", "application/pdf")}


def test_importacao_grava_posicoes_e_movimentos(client, session):
    response = client.post("/import", files=PDF)
    assert response.status_code == 200
    assert session.scalar(select(func.count()).select_from(Statement)) == 1
    assert session.scalar(select(func.count()).select_from(Position)) == 6
    assert session.scalar(select(func.count()).select_from(Movement)) > 0


def test_pagina_mostra_total_consolidado(client):
    client.post("/import", files=PDF)
    html = client.get("/").text
    assert "R$ 2,000.00" in html  # 1.000 renda variável + 1.000 renda fixa
    assert "FIIA11" in html and "CDB000AAAAA" in html


def test_reimportar_mesmo_arquivo_nao_duplica(client, session):
    client.post("/import", files=PDF)
    response = client.post("/import", files=PDF)
    assert response.status_code == 400
    assert "já foi importado" in response.text
    assert session.scalar(select(func.count()).select_from(Statement)) == 1


def test_arquivo_que_nao_e_pdf_e_recusado(client, session):
    response = client.post("/import", files={"file": ("x.csv", b"a,b\n1,2", "text/csv")})
    assert response.status_code == 400
    assert session.scalar(select(func.count()).select_from(Statement)) == 0


def test_valores_que_nao_batem_com_sumario_nao_sao_gravados(client, session, monkeypatch):
    from app import importer
    from tests.conftest import FIXTURE_TEXT

    monkeypatch.setattr(
        importer,
        "extract_text",
        lambda _c: FIXTURE_TEXT.replace("Total em ETF's", "x").replace(
            "ABCD11 ETF EXEMPLO CI 10 20,00 18,00 200,00", ""
        ),
    )
    response = client.post("/import", files=PDF)
    assert response.status_code == 400
    assert "não batem" in response.text
    assert session.scalar(select(func.count()).select_from(Statement)) == 0


def test_dinheiro_nao_usa_float(session, client):
    client.post("/import", files=PDF)
    position = session.scalar(select(Position).where(Position.code == "FIIB11"))
    assert position.gross_balance == Decimal("200.00")
    assert isinstance(position.gross_balance, Decimal)
