# Consolidador de Investimentos

App web (FastAPI + Jinja + SQLAlchemy) que consolida investimentos da B3 a partir de extratos
do BTG (PDF/CSV). Dados são pessoais e financeiros: trate como sensíveis.

## Comandos
- Rodar (1ª vez: `.venv/bin/alembic upgrade head`): `.venv/bin/uvicorn app.main:app --reload`
- Tudo de uma vez (o mesmo que o CI): `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest`

## Regras (guardrails)
- NUNCA versionar documentos reais (`BTG Docs/`, `*.pdf`) nem CPF/endereço/saldos. Testes usam
  fixtures sintéticas em `tests/fixtures/`.
- Dinheiro e quantidade: sempre `Decimal`/`Numeric`, nunca `float`.
- Importação só grava se o que foi lido fechar com o Sumário do extrato (`reconcile()`).
- Reimportar o mesmo arquivo não pode duplicar (hash SHA-256).
- Seção/ativo desconhecido vira `warning`, nunca é ignorado em silêncio nem derruba a importação.
- O texto do PDF do BTG perde letras ("Rend  Fix "): detectar seções por trechos estáveis e
  linhas de dados por estrutura, não por rótulo completo.
- Movimentos de conta corrente duplicam proventos de renda variável: análises de proventos usam
  só `MovementType.RENDIMENTO`.
- Python 3.9 local: sem `X | Y` em tipos; use `Optional`.

- Mudou `app/models.py`? Crie a migration (`alembic revision --autogenerate`). Um teste falha se
  models e migrations divergirem. O app nunca cria tabelas sozinho.
- Segredos (`DATABASE_URL`, chaves do Supabase) só em variáveis de ambiente, nunca no código.

- Toda rota (exceto /login) depende de `current_user`. Toda consulta parte de
  `Statement.user_id == user.id`: a conexão com o Postgres ignora o RLS, a autorização é do app.
- Auth falha fechado: sem `ALLOWED_EMAILS` ou com token inválido, ninguém entra. Nunca logar
  token, senha ou `DATABASE_URL`. Nunca usar a `service_role key` no app.
- Rota nova = teste de "sem login", "outro usuário" e "caminho feliz".

## Fluxo de trabalho (pós-v1)
Antes de dar push, reproduzir o CI num venv limpo (`pip install -e ".[dev]"` + ruff, mypy, pytest).
Branch -> PR -> CR por outro agente -> revisão final -> aprovação do dono no GitHub. Nada vai
direto para `main`. Todo PR precisa de teste e CI verde.
