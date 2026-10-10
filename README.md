# Consolidador de Investimentos

Importe o extrato mensal da sua corretora (por enquanto: BTG, PDF) e veja a carteira consolidada.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload   # http://127.0.0.1:8000
.venv/bin/pytest
```

Banco: SQLite por padrão; para PostgreSQL defina `DATABASE_URL`.
Veja `CLAUDE.md` para as regras do projeto.
