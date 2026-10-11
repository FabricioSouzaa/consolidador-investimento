"""user_id no statement (isolamento por usuário)

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Nome do UNIQUE(sha256) criado na 0001: o Postgres gera `statement_sha256_key`; o SQLite não
# nomeia, então o batch precisa de uma convenção para conseguir referenciá-lo.
_SQLITE_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.drop_constraint("statement_sha256_key", "statement", type_="unique")
    # Linhas pré-existentes ficam com user_id "" (não pertencem a ninguém => invisíveis).
    with op.batch_alter_table("statement", naming_convention=_SQLITE_NAMING) as batch:
        batch.add_column(
            sa.Column("user_id", sa.String(length=36), nullable=False, server_default="")
        )
        batch.alter_column("user_id", server_default=None)
        if not postgres:
            batch.drop_constraint("uq_statement_sha256", type_="unique")
        batch.create_index("ix_statement_user_id", ["user_id"])
        batch.create_unique_constraint("uq_statement_user_sha256", ["user_id", "sha256"])


def downgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    with op.batch_alter_table("statement", naming_convention=_SQLITE_NAMING) as batch:
        batch.drop_constraint("uq_statement_user_sha256", type_="unique")
        batch.drop_index("ix_statement_user_id")
        batch.drop_column("user_id")
        # Mantém os nomes que a 0001 produz, para um novo upgrade encontrar a constraint.
        batch.create_unique_constraint(
            "statement_sha256_key" if postgres else "uq_statement_sha256", ["sha256"]
        )
