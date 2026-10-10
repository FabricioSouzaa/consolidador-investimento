import hashlib
from dataclasses import dataclass, field
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Movement, Position, Statement
from app.parsers.btg_extrato import extract_text, parse_extrato


class ImportRejected(Exception):
    """Arquivo recusado (duplicado, inválido ou que não bate com o sumário)."""


@dataclass
class ImportResult:
    statement_id: int
    positions: int
    movements: int
    warnings: List[str] = field(default_factory=list)


def import_btg_pdf(session: Session, filename: str, content: bytes) -> ImportResult:
    digest = hashlib.sha256(content).hexdigest()
    if session.scalar(select(Statement).where(Statement.sha256 == digest)):
        raise ImportRejected("Este arquivo já foi importado.")

    try:
        parsed = parse_extrato(extract_text(content))
    except ValueError as exc:
        raise ImportRejected(str(exc)) from exc

    problems = parsed.reconcile()
    if problems:  # guardrail: nunca gravar números que não fecham com o extrato
        raise ImportRejected(
            "Os valores lidos não batem com o sumário do extrato: " + "; ".join(problems)
        )

    statement = Statement(
        sha256=digest,
        filename=filename[:255],
        period_start=parsed.period_start,
        period_end=parsed.period_end,
    )
    statement.positions = [Position(**vars(p)) for p in parsed.positions]
    statement.movements = [
        Movement(
            occurred_on=m.date,
            type=m.type,
            description=m.description[:200],
            code=m.code,
            quantity=m.quantity,
            gross_value=m.gross_value,
            net_value=m.net_value,
        )
        for m in parsed.movements
    ]
    session.add(statement)
    session.commit()
    return ImportResult(
        statement.id, len(statement.positions), len(statement.movements), parsed.warnings
    )
