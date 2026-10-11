from decimal import Decimal
from pathlib import Path
from typing import Dict

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.importer import ImportRejected, import_btg_pdf
from app.models import Position, Statement

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Consolidador de Investimentos")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _latest_portfolio(session: Session) -> Dict[str, object]:
    statement = session.scalar(select(Statement).order_by(Statement.period_end.desc()))
    if statement is None:
        return {"statement": None, "positions": [], "by_class": {}, "total": Decimal("0")}
    positions = list(
        session.scalars(
            select(Position).where(Position.statement_id == statement.id).order_by(Position.code)
        )
    )
    by_class: Dict[str, Decimal] = {}
    for position in positions:
        key = position.asset_class.value
        by_class[key] = by_class.get(key, Decimal("0")) + position.gross_balance
    return {
        "statement": statement,
        "positions": positions,
        "by_class": by_class,
        "total": sum(by_class.values(), Decimal("0")),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "index.html", {"portfolio": _latest_portfolio(session), "error": None}
    )


@app.post("/import", response_class=HTMLResponse)
async def import_file(
    request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)
) -> HTMLResponse:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    error = None
    if len(content) > MAX_UPLOAD_BYTES:
        error = "Arquivo maior que 10 MB."
    elif not content.startswith(b"%PDF"):
        error = "Envie um PDF (por enquanto só o Extrato Mensal do BTG é suportado)."
    else:
        try:
            import_btg_pdf(session, file.filename or "extrato.pdf", content)
        except ImportRejected as exc:
            error = str(exc)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"portfolio": _latest_portfolio(session), "error": error},
        status_code=400 if error else 200,
    )
