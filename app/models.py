"""Modelo de dados. Valores monetários SEMPRE em Numeric/Decimal, nunca float."""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(18, 2)
Quantity = Numeric(24, 8)


class AssetClass(str, enum.Enum):
    ACAO = "ACAO"
    FII = "FII"
    FIAGRO = "FIAGRO"
    FIINFRA = "FIINFRA"
    ETF = "ETF"
    BDR = "BDR"
    OPCAO = "OPCAO"
    CDB = "CDB"
    LCI = "LCI"
    LCA = "LCA"
    CRI = "CRI"
    CRA = "CRA"
    DEBENTURE = "DEBENTURE"
    TESOURO = "TESOURO"
    FUNDO = "FUNDO"
    OUTRO = "OUTRO"


class MovementType(str, enum.Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"
    RENDIMENTO = "RENDIMENTO"  # dividendos, JCP, rendimentos de FII/Fiagro
    EVENTO = "EVENTO"  # desdobramento, subscrição, bonificação etc.
    CREDITO_CONTA = "CREDITO_CONTA"
    DEBITO_CONTA = "DEBITO_CONTA"


class Statement(Base):
    """Um arquivo importado. O hash garante que reimportar o mesmo arquivo não duplica dados."""

    __tablename__ = "statement"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    positions: Mapped[list["Position"]] = relationship(cascade="all, delete-orphan")
    movements: Mapped[list["Movement"]] = relationship(cascade="all, delete-orphan")


class Position(Base):
    """Foto da posição de um ativo no fim do período do extrato."""

    __tablename__ = "position"
    __table_args__ = (UniqueConstraint("statement_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statement.id"))
    code: Mapped[str] = mapped_column(String(40))  # ticker ou código do título
    name: Mapped[str] = mapped_column(String(120))
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    gross_balance: Mapped[Decimal] = mapped_column(Money)
    net_balance: Mapped[Optional[Decimal]] = mapped_column(Money)
    avg_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    invested: Mapped[Optional[Decimal]] = mapped_column(Money)  # só renda fixa
    issue_date: Mapped[Optional[date]] = mapped_column(Date)
    maturity_date: Mapped[Optional[date]] = mapped_column(Date)
    index_name: Mapped[Optional[str]] = mapped_column(String(20))  # CDI, IPCA...


class Movement(Base):
    __tablename__ = "movement"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statement.id"))
    occurred_on: Mapped[date] = mapped_column(Date)
    type: Mapped[MovementType] = mapped_column(Enum(MovementType))
    description: Mapped[str] = mapped_column(String(200))
    code: Mapped[Optional[str]] = mapped_column(String(40))
    quantity: Mapped[Optional[Decimal]] = mapped_column(Quantity)
    gross_value: Mapped[Optional[Decimal]] = mapped_column(Money)
    net_value: Mapped[Optional[Decimal]] = mapped_column(Money)
