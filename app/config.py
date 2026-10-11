import os
import unicodedata
from dataclasses import dataclass
from typing import FrozenSet


def normalize_database_url(url: str) -> str:
    """Aceita as URLs que Supabase/Vercel fornecem e força o driver psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


# SQLite em dev/testes; em produção aponte para o PostgreSQL (Supabase, pooler em modo
# transaction): DATABASE_URL=postgresql://user:pass@host:6543/postgres
DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL", "sqlite:///./consolidador.db"))


def normalize_email(email: str) -> str:
    """NFKC + casefold: 'K' (Kelvin) e variantes Unicode não podem imitar um e-mail permitido."""
    return unicodedata.normalize("NFKC", email).strip().casefold()


@dataclass(frozen=True)
class AuthSettings:
    supabase_url: str  # https://<ref>.supabase.co
    supabase_anon_key: str  # chave pública (publishable/anon): só chama o endpoint de login
    jwt_secret: str  # só para projetos com o segredo HS256 legado; vazio = usa JWKS
    allowed_emails: FrozenSet[str]
    cookie_secure: bool


def get_auth_settings() -> AuthSettings:
    env = os.environ
    emails = {normalize_email(e) for e in env.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
    return AuthSettings(
        supabase_url=env.get("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=env.get("SUPABASE_ANON_KEY", ""),
        jwt_secret=env.get("SUPABASE_JWT_SECRET", ""),
        allowed_emails=frozenset(emails),
        # "false" só para rodar em http://localhost no Safari; em produção fica ligado.
        cookie_secure=env.get("COOKIE_SECURE", "true").lower() != "false",
    )
