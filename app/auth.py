"""Autenticação via Supabase Auth.

O backend faz o login (e-mail/senha) no Supabase, guarda o JWT num cookie HttpOnly e valida o
token em TODA rota protegida. Autorização é responsabilidade do app: a conexão com o Postgres
ignora o RLS, então toda consulta precisa filtrar por `user_id`.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Request
from jwt import PyJWKClient

from app.config import AuthSettings, get_auth_settings

ACCESS_COOKIE = "sb_access"
_JWKS_ALGORITHMS = ["ES256", "RS256"]
_jwks_clients: Dict[str, PyJWKClient] = {}


class NotAuthenticated(Exception):
    """Sem sessão válida: as rotas HTML respondem redirecionando para /login."""


class LoginFailed(Exception):
    """Credenciais recusadas (mensagem genérica, sem revelar se o e-mail existe)."""


@dataclass(frozen=True)
class User:
    id: str
    email: str


def _signing_key(token: str, settings: AuthSettings) -> Any:
    client = _jwks_clients.setdefault(
        settings.supabase_url,
        PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True),
    )
    return client.get_signing_key_from_jwt(token).key


def verify_token(token: str, settings: Optional[AuthSettings] = None) -> User:
    """Valida assinatura, expiração, emissor e audiência. Levanta NotAuthenticated se falhar."""
    settings = settings or get_auth_settings()
    if not settings.allowed_emails:  # falha fechado: sem allowlist ninguém entra
        raise NotAuthenticated("ALLOWED_EMAILS não configurado")
    try:
        algorithm = jwt.get_unverified_header(token).get("alg", "")
        options = {"require": ["exp", "sub"]}
        common: Dict[str, Any] = {"audience": "authenticated", "options": options}
        if settings.supabase_url:
            common["issuer"] = f"{settings.supabase_url}/auth/v1"
        if algorithm == "HS256" and settings.jwt_secret:
            claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], **common)
        elif algorithm in _JWKS_ALGORITHMS and settings.supabase_url:
            key = _signing_key(token, settings)
            claims = jwt.decode(token, key, algorithms=_JWKS_ALGORITHMS, **common)
        else:
            raise NotAuthenticated("algoritmo não aceito")
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        raise NotAuthenticated(type(exc).__name__) from None

    email = str(claims.get("email", "")).lower()
    if email not in settings.allowed_emails:
        raise NotAuthenticated("e-mail fora da allowlist")
    return User(id=str(claims["sub"]), email=email)


def current_user(request: Request) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise NotAuthenticated("sem cookie")
    return verify_token(token)


def password_login(email: str, password: str) -> Dict[str, Any]:
    """Troca e-mail/senha por tokens no Supabase. Devolve {"access_token", "expires_in"}."""
    settings = get_auth_settings()
    if not (settings.supabase_url and settings.supabase_anon_key):
        raise LoginFailed("Supabase não configurado")
    try:
        response = httpx.post(
            f"{settings.supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": settings.supabase_anon_key},
            json={"email": email, "password": password},
            timeout=10,
        )
    except httpx.HTTPError:
        raise LoginFailed("Supabase indisponível") from None
    if response.status_code != 200:
        raise LoginFailed("credenciais recusadas")
    data = response.json()
    if "access_token" not in data:
        raise LoginFailed("resposta inesperada")
    return {"access_token": data["access_token"], "expires_in": int(data.get("expires_in", 3600))}
