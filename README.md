# Consolidador de Investimentos

Importe o extrato mensal da sua corretora (por enquanto: BTG, PDF) e veja a carteira consolidada.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head           # cria as tabelas (também no SQLite local)
.venv/bin/uvicorn app.main:app --reload   # http://127.0.0.1:8000
.venv/bin/pytest
```

Banco: SQLite por padrão; para PostgreSQL (Supabase) defina `DATABASE_URL` com a URL do *pooler*
(modo transaction), terminada em `?sslmode=require`. Para as migrations dá para definir
`MIGRATIONS_DATABASE_URL` com a conexão direta (porta 5432), mais segura para DDL. O schema é gerenciado por migrations:

```bash
.venv/bin/alembic upgrade head                                  # aplica
.venv/bin/alembic revision --autogenerate -m "o que mudou"     # após alterar app/models.py
```

Veja `CLAUDE.md` para as regras do projeto.

## Login (Supabase Auth)

O app exige login. Variáveis de ambiente (nunca no código):

| Variável | O que é |
|---|---|
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | chave pública (publishable/anon). **Nunca** use a `service_role` |
| `ALLOWED_EMAILS` | e-mails autorizados, separados por vírgula. Vazio = ninguém entra |
| `SUPABASE_JWT_SECRET` | só se o projeto usar o segredo HS256 legado; vazio = valida pelo JWKS |
| `COOKIE_SECURE` | `false` só para testar em `http://localhost` no Safari |

No painel do Supabase: crie seu usuário em *Authentication → Users* e **desligue o cadastro
público** (*Sign In / Providers → Email → Allow new users to sign up*).
