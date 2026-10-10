from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import AssetClass, MovementType
from app.parsers.btg_extrato import extract_text, parse_date, parse_extrato, parse_number

FIXTURE = Path(__file__).parent / "fixtures" / "extrato_btg_sintetico.txt"
REAL_PDF = Path(__file__).parent.parent / "BTG Docs"


@pytest.fixture(scope="module")
def parsed():
    return parse_extrato(FIXTURE.read_text())


def test_parse_number_formato_brasileiro():
    assert parse_number("1.234,56") == Decimal("1234.56")
    assert parse_number("85.000,0") == Decimal("85000.0")
    assert parse_number("-") is None


def test_parse_date_ano_com_dois_digitos():
    assert parse_date("30/09/26") == date(2026, 9, 30)


def test_periodo(parsed):
    assert (parsed.period_start, parsed.period_end) == (date(2026, 9, 1), date(2026, 9, 30))


def test_posicoes_renda_variavel_classificadas_por_tipo(parsed):
    classes = {p.code: p.asset_class for p in parsed.positions}
    assert classes["ABCD11"] == AssetClass.ETF
    assert classes["FIIA11"] == AssetClass.FII
    assert classes["FIIB11"] == AssetClass.FIAGRO
    assert classes["FIIC11"] == AssetClass.FIINFRA


def test_posicao_valores(parsed):
    fii = next(p for p in parsed.positions if p.code == "FIIA11")
    assert fii.quantity == Decimal("5")
    assert fii.avg_price == Decimal("95.00")
    assert fii.gross_balance == Decimal("500.00")


def test_renda_fixa_le_detalhamento(parsed):
    cdb = next(p for p in parsed.positions if p.code == "CDB000AAAAA")
    assert cdb.asset_class == AssetClass.CDB
    assert cdb.invested == Decimal("600.00")
    assert cdb.gross_balance == Decimal("630.00")
    assert cdb.net_balance == Decimal("625.00")
    assert cdb.maturity_date == date(2028, 7, 3)
    assert cdb.index_name == "CDI"


def test_rendimento_etf_sem_coluna_tipo(parsed):
    mov = next(m for m in parsed.movements if m.code == "ABCD11")
    assert mov.type == MovementType.RENDIMENTO
    assert (mov.gross_value, mov.net_value) == (Decimal("7.69"), Decimal("6.54"))


def test_evento_sem_valor_vira_evento(parsed):
    mov = next(m for m in parsed.movements if m.description.startswith("VENCIMENTO"))
    assert mov.type == MovementType.EVENTO
    assert mov.gross_value is None


def test_compra_classificada(parsed):
    mov = next(m for m in parsed.movements if m.type == MovementType.COMPRA)
    assert mov.code == "FIIA11"
    assert mov.net_value == Decimal("196.50")


def test_conta_corrente_credito_e_debito(parsed):
    types = {m.type for m in parsed.movements if m.code is None}
    assert types == {MovementType.CREDITO_CONTA, MovementType.DEBITO_CONTA}


def test_valores_em_transito(parsed):
    assert parsed.in_transit == [
        (date(2026, 10, 8), "RENDIMENTO - ETF EXEMPLO CI", Decimal("2.00"))
    ]


def test_reconciliacao_com_sumario_bate(parsed):
    assert parsed.reconcile() == []


def test_reconciliacao_detecta_divergencia(parsed):
    broken = parse_extrato(FIXTURE.read_text())
    broken.positions = broken.positions[:-1]
    assert broken.reconcile() != []


def test_secao_nao_suportada_gera_aviso_e_nao_quebra():
    text = FIXTURE.read_text().replace("Posição - ETF", "Posição - Ações")
    # "Ações" é suportado; usamos uma seção inexistente para testar o aviso
    text = text.replace("Posição - Ações", "Posição - Termo")
    result = parse_extrato(text)
    assert any("não suportada" in w for w in result.warnings)


def test_documento_invalido_e_rejeitado():
    with pytest.raises(ValueError):
        parse_extrato("isto não é um extrato")


@pytest.mark.skipif(not list(REAL_PDF.glob("Extrato*.pdf")), reason="PDF real só existe local")
def test_pdf_real_reconcilia_com_sumario():
    pdf = next(REAL_PDF.glob("Extrato*.pdf"))
    result = parse_extrato(extract_text(pdf.read_bytes()))
    assert result.positions, "nenhuma posição lida do PDF real"
    assert result.reconcile() == []


@pytest.mark.skipif(not list(REAL_PDF.glob("Extrato*.pdf")), reason="PDF real só existe local")
def test_pdf_real_le_conta_corrente_e_proventos():
    pdf = next(REAL_PDF.glob("Extrato*.pdf"))
    result = parse_extrato(extract_text(pdf.read_bytes()))
    kinds = {m.type for m in result.movements}
    assert MovementType.RENDIMENTO in kinds
    assert MovementType.CREDITO_CONTA in kinds
