from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    ACCESS_COOKIE,
    LoginFailed,
    NotAuthenticated,
    User,
    current_user,
    password_login,
)
from app.config import get_auth_settings
from app.db import get_session
from app.importer import ImportRejected, import_btg_pdf
from app.models import Position, Statement

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="Consolidador de Investimentos", docs_url=None, redoc_url=None, openapi_url=None
)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.exception_handler(NotAuthenticated)
def _redirect_to_login(request: Request, exc: NotAuthenticated) -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(ACCESS_COOKIE)
    return response


def _latest_portfolio(session: Session, user: User) -> Dict[str, object]:
    statement = session.scalar(
        select(Statement)
        .where(Statement.user_id == user.id)  # isolamento: nunca consultar sem o dono
        .order_by(Statement.period_end.desc())
    )
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


def _home(
    request: Request, session: Session, user: User, error: Optional[str], status: int = 200
) -> Response:
    context = {"portfolio": _latest_portfolio(session, user), "error": error, "user": user}
    return templates.TemplateResponse(request, "index.html", context, status_code=status)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
    settings = get_auth_settings()
    failure = templates.TemplateResponse(
        request, "login.html", {"error": "E-mail ou senha inválidos."}, status_code=401
    )
    if email.strip().lower() not in settings.allowed_emails:
        return failure  # mesma resposta de credencial errada: não revela quem é permitido
    try:
        tokens = password_login(email.strip(), password)
    except LoginFailed:
        return failure
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        ACCESS_COOKIE,
        tokens["access_token"],
        max_age=tokens["expires_in"],
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(ACCESS_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    return _home(request, session, user, None)


@app.post("/import", response_class=HTMLResponse)
async def import_file(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    error = None
    if len(content) > MAX_UPLOAD_BYTES:
        error = "Arquivo maior que 10 MB."
    elif not content.startswith(b"%PDF"):
        error = "Envie um PDF (por enquanto só o Extrato Mensal do BTG é suportado)."
    else:
        try:
            import_btg_pdf(session, user.id, file.filename or "extrato.pdf", content)
        except ImportRejected as exc:
            error = str(exc)
    return _home(request, session, user, error, status=400 if error else 200)
