from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    ACCESS_COOKIE,
    LoginFailed,
    NotAuthenticated,
    User,
    current_user,
    password_login,
    revoke_session,
)
from app.config import get_auth_settings, normalize_email
from app.db import get_session
from app.importer import ImportRejected, import_btg_pdf
from app.models import Position, Statement

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="Consolidador de Investimentos", docs_url=None, redoc_url=None, openapi_url=None
)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    if get_auth_settings().cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def same_origin_only(request: Request) -> None:
    """Defesa extra ao SameSite=Lax: POST vindo de outro site é recusado."""
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Origem não permitida.")


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


@app.post("/login", response_class=HTMLResponse, dependencies=[Depends(same_origin_only)])
def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
    settings = get_auth_settings()
    failure = templates.TemplateResponse(
        request, "login.html", {"error": "E-mail ou senha inválidos."}, status_code=401
    )
    if normalize_email(email) not in settings.allowed_emails:
        # Mesma mensagem de credencial errada. Limitação conhecida: responde mais rápido que um
        # e-mail permitido (que chama o Supabase), então o tempo ainda distingue os dois casos.
        return failure
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
        path="/",
    )
    return response


@app.post("/logout", dependencies=[Depends(same_origin_only)])
def logout(request: Request) -> Response:
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        revoke_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(ACCESS_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    return _home(request, session, user, None)


@app.post("/import", response_class=HTMLResponse, dependencies=[Depends(same_origin_only)])
async def import_file(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    # O corpo só é lido DEPOIS da autenticação (sem parâmetro File na assinatura): um anônimo
    # não consegue fazer o servidor processar um upload.
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD_BYTES + 64 * 1024:  # folga para o envelope multipart
        return _home(request, session, user, "Arquivo maior que 10 MB.", status=413)
    form = await request.form()
    upload = form.get("file")
    content = b""
    if upload is not None and hasattr(upload, "read"):
        content = await upload.read(MAX_UPLOAD_BYTES + 1)
    error = None
    if len(content) > MAX_UPLOAD_BYTES:
        error = "Arquivo maior que 10 MB."
    elif not content.startswith(b"%PDF"):
        error = "Envie um PDF (por enquanto só o Extrato Mensal do BTG é suportado)."
    else:
        filename = getattr(upload, "filename", None) or "extrato.pdf"
        try:
            # pdfplumber é síncrono e pesado: fora do event loop
            await run_in_threadpool(import_btg_pdf, session, user.id, filename, content)
        except ImportRejected as exc:
            error = str(exc)
        except IntegrityError:  # duas importações simultâneas do mesmo arquivo
            session.rollback()
            error = "Este arquivo já foi importado."
    return _home(request, session, user, error, status=400 if error else 200)
