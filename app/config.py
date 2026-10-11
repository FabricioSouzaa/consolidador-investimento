import os


def normalize_database_url(url: str) -> str:
    """Aceita as URLs que Supabase/Vercel fornecem e força o driver psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


# SQLite em dev/testes; em produção aponte para o PostgreSQL (Supabase, pooler em modo
# transaction): DATABASE_URL=postgresql://user:pass@host:6543/postgres
DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL", "sqlite:///./consolidador.db"))
