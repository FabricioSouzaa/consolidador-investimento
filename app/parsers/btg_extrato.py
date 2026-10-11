"""Parser do "Extrato Mensal" de conta investimento do BTG Pactual (PDF).

A extração de texto do PDF do BTG perde algumas letras ("Renda Fixa" vira "Rend  Fix "),
então as seções são detectadas por trechos estáveis e as linhas de dados por estrutura
(datas, tickers, números), nunca por rótulos completos.

Seções ainda não suportadas (ex.: Ações, BDR, Tesouro) não quebram a importação: viram
`warnings` no resultado, para o usuário saber que algo ficou de fora.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pdfplumber

from app.models import AssetClass, MovementType

MAX_PAGES = 60  # um extrato mensal tem ~11 páginas; protege contra PDFs patológicos
NUM = r"\d[\d.]*,\d+"
DATE = r"\d{2}/\d{2}/\d{2}"
TICKER = r"[A-Z]{4}\d{1,2}"


def parse_number(text: str) -> Optional[Decimal]:
    """'1.234,56' -> Decimal('1234.56'); '-' -> None."""
    text = text.strip()
    if text in ("-", ""):
        return None
    return Decimal(text.replace(".", "").replace(",", "."))


def parse_date(text: str) -> date:
    day, month, year = text.split("/")
    return date(2000 + int(year), int(month), int(day))


@dataclass
class ParsedPosition:
    code: str
    name: str
    asset_class: AssetClass
    quantity: Decimal
    gross_balance: Decimal
    net_balance: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    invested: Optional[Decimal] = None
    issue_date: Optional[date] = None
    maturity_date: Optional[date] = None
    index_name: Optional[str] = None


@dataclass
class ParsedMovement:
    date: date
    type: MovementType
    description: str
    code: Optional[str] = None
    quantity: Optional[Decimal] = None
    gross_value: Optional[Decimal] = None
    net_value: Optional[Decimal] = None


@dataclass
class ParsedStatement:
    period_start: date
    period_end: date
    positions: List[ParsedPosition] = field(default_factory=list)
    movements: List[ParsedMovement] = field(default_factory=list)
    in_transit: List[Tuple[date, str, Decimal]] = field(default_factory=list)
    summary_gross: Dict[str, Decimal] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def reconcile(self) -> List[str]:
        """Compara o que foi lido com o Sumário do próprio extrato. Lista vazia = tudo bate."""
        problems: List[str] = []
        fixed = {
            AssetClass.CDB,
            AssetClass.LCI,
            AssetClass.LCA,
            AssetClass.CRI,
            AssetClass.CRA,
            AssetClass.DEBENTURE,
            AssetClass.TESOURO,
        }
        parsed = {
            "renda_variavel": sum(
                (p.gross_balance for p in self.positions if p.asset_class not in fixed),
                Decimal("0"),
            ),
            "renda_fixa": sum(
                (p.gross_balance for p in self.positions if p.asset_class in fixed), Decimal("0")
            ),
        }
        for key, value in parsed.items():
            expected = self.summary_gross.get(key)
            if expected is not None and expected != value:
                problems.append(f"{key}: extrato diz {expected}, parser leu {value}")
        return problems


_RV_CLASSES = {
    "ETF": AssetClass.ETF,
    "ACOES": AssetClass.ACAO,
    "BDR": AssetClass.BDR,
    "BDRS": AssetClass.BDR,
    "OPCOES": AssetClass.OPCAO,
}
_FUND_TYPES = {"FII": AssetClass.FII, "FIAGRO": AssetClass.FIAGRO, "FIINFRA": AssetClass.FIINFRA}
_RF_CLASSES = {
    "CDB": AssetClass.CDB,
    "LCI": AssetClass.LCI,
    "LCA": AssetClass.LCA,
    "CRI": AssetClass.CRI,
    "CRA": AssetClass.CRA,
}

_RV_POSITION = re.compile(rf"^({TICKER}) (.+) (\d[\d.]*) ({NUM}) ({NUM}) ({NUM})$")
_RV_MOVEMENT = re.compile(
    rf"^({DATE}) (.+?) ({TICKER})(?: ([A-Z]+))? (\d[\d.]*) (-|{NUM}) (-|{NUM}) (-|{NUM}) (-|{NUM})$"
)
_RF_DETAIL = re.compile(
    rf"^({DATE}) ({DATE}) ({DATE}) \S+ \d+ ({DATE}) (\S+) ({NUM}) ({NUM}) ({NUM}) ({NUM}) "
    rf"({NUM}) (-|{NUM}) (-|{NUM}) ({NUM})$"
)
_CASH_MOVEMENT = re.compile(rf"^({DATE}) (.+?) (-?{NUM}) (-?{NUM})$")
_TRANSIT = re.compile(rf"^({DATE}) (.+?) ({NUM})$")
_SUMMARY = re.compile(rf"^(.+?) ({NUM}) ({NUM}) ({NUM}) ({NUM})$")


def _normalize(text: str) -> str:
    table = str.maketrans("ÃÕÇÁÉÍÓÚÂÊÔ", "AOCAEIOUAEO")
    return text.upper().translate(table)


def _movement_type(description: str) -> MovementType:
    desc = _normalize(description)
    if desc.startswith(("RENDIMENTO", "DIVIDENDO", "JUROS SOBRE", "JCP")):
        return MovementType.RENDIMENTO
    if desc.startswith("COMPRA"):
        return MovementType.COMPRA
    if desc.startswith("VENDA"):
        return MovementType.VENDA
    return MovementType.EVENTO


def _summary_key(label: str) -> Optional[str]:
    label = _normalize(label)
    for needle, key in (
        ("VARIAVEL", "renda_variavel"),
        ("FIX", "renda_fixa"),
        ("CORRENTE", "conta_corrente"),
        ("TRANSITO", "transito"),
        ("TOTAL", "total"),
    ):
        if needle in label:
            return key
    return None


def extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError(f"PDF com {len(pdf.pages)} páginas; o limite é {MAX_PAGES}.")
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def parse_extrato(text: str) -> ParsedStatement:
    match = re.search(rf"Período de ({DATE})\D+?({DATE})", text)
    if not match:
        raise ValueError("Não encontrei o período do extrato: este não parece um extrato BTG.")
    result = ParsedStatement(parse_date(match.group(1)), parse_date(match.group(2)))

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    section = ""
    detail = ""
    issuer = ""

    for index, line in enumerate(lines):
        # --- cabeçalhos de seção -------------------------------------------------------------
        if m := re.search(r"variável - Posição - (.+)$", line):
            section, detail = "rv_pos", _normalize(m.group(1).strip())
            continue
        if m := re.search(r"variável - Movimentação - (.+)$", line):
            section, detail = "rv_mov", _normalize(m.group(1).strip())
            continue
        if m := re.search(r"- Detalhamento - (\w+) \| (.+)$", line):
            section, detail, issuer = "rf_det", m.group(1).upper(), m.group(2).strip()
            continue
        if re.search(r"Cont\S*\s+corrente - Movimentação", line):
            section = "cash_mov"
            continue
        if line.startswith("Valores em trânsito"):
            section = "transit"
            continue
        if line.startswith("Sumário - Distribuição"):
            section = "summary"
            continue
        if (
            re.search(r"- Posição - \w+$", line)
            or "Posição Consolidad" in line
            or re.search(r"corrente - Posição", line)
            or line.startswith(("Per l de Risco", "Disclaimers", "Perfil de Risco"))
        ):
            section = ""  # Posição de RF é lida pelo Detalhamento (que tem valor investido)
            continue

        # --- linhas de dados -----------------------------------------------------------------
        if section == "rv_pos" and (m := _RV_POSITION.match(line)):
            ticker, name, qty, _close, avg, balance = m.groups()
            fund_type = name.split()[-1]
            asset_class = _FUND_TYPES.get(fund_type) or _RV_CLASSES.get(detail)
            if asset_class is None:
                result.warnings.append(
                    f"Seção de renda variável não suportada: {detail} ({ticker})"
                )
                continue
            result.positions.append(
                ParsedPosition(
                    code=ticker,
                    name=name,
                    asset_class=asset_class,
                    quantity=parse_number(qty) or Decimal("0"),
                    gross_balance=parse_number(balance) or Decimal("0"),
                    avg_price=parse_number(avg),
                )
            )
        elif section == "rv_mov" and (m := _RV_MOVEMENT.match(line)):
            when, desc, ticker, _type, qty, _price, gross, _fees, net = m.groups()
            result.movements.append(
                ParsedMovement(
                    date=parse_date(when),
                    type=_movement_type(desc),
                    description=desc,
                    code=ticker,
                    quantity=parse_number(qty),
                    gross_value=parse_number(gross),
                    net_value=parse_number(net),
                )
            )
        elif section == "rf_det" and (m := _RF_DETAIL.match(line)):
            asset_class = _RF_CLASSES.get(detail)
            code = lines[index + 1] if index + 1 < len(lines) else ""
            if asset_class is None or not re.fullmatch(r"[A-Z0-9]+", code):
                result.warnings.append(f"Título de renda fixa não reconhecido: {detail} {code}")
                continue
            (
                issue,
                maturity,
                _acq,
                _liq,
                idx,
                qty,
                _buy_price,
                invested,
                _price,
                gross,
                _ir,
                _iof,
                net,
            ) = m.groups()
            result.positions.append(
                ParsedPosition(
                    code=code,
                    name=f"{detail} {issuer}"[:120],
                    asset_class=asset_class,
                    quantity=parse_number(qty) or Decimal("0"),
                    gross_balance=parse_number(gross) or Decimal("0"),
                    net_balance=parse_number(net),
                    invested=parse_number(invested),
                    issue_date=parse_date(issue),
                    maturity_date=parse_date(maturity),
                    index_name=idx,
                )
            )
        elif section == "cash_mov" and (m := _CASH_MOVEMENT.match(line)):
            when, desc, value, _balance = m.groups()
            amount = parse_number(value) or Decimal("0")
            result.movements.append(
                ParsedMovement(
                    date=parse_date(when),
                    description=desc,
                    gross_value=amount,
                    net_value=amount,
                    type=MovementType.CREDITO_CONTA if amount >= 0 else MovementType.DEBITO_CONTA,
                )
            )
        elif section == "transit" and (m := _TRANSIT.match(line)) and not line.startswith("Total"):
            result.in_transit.append(
                (parse_date(m.group(1)), m.group(2), parse_number(m.group(3)) or Decimal("0"))
            )
        elif section == "summary" and (m := _SUMMARY.match(line)):
            key = _summary_key(m.group(1))
            if key:
                # grupo 4 = Saldo Bruto no fim do período (3º número da linha)
                result.summary_gross[key] = parse_number(m.group(4)) or Decimal("0")
    return result
