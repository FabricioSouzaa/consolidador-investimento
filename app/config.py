import os

# SQLite em dev/testes; em produção basta apontar para PostgreSQL:
# DATABASE_URL=postgresql+psycopg://user:pass@host/db
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./consolidador.db")
