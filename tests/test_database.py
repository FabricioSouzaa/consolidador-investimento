from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from app.config import normalize_database_url
from app.db import Base, make_engine


def _alembic_config(connection) -> Config:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    return config


def test_migracoes_criam_o_schema_e_batem_com_os_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")
        tables = set(inspect(connection).get_table_names())
        assert {"statement", "position", "movement"} <= tables
        # Se alguém mudar um model sem criar migration, este teste falha.
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == []


def test_migracao_pode_ser_desfeita(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert "statement" not in inspect(connection).get_table_names()


def test_url_do_supabase_vira_driver_psycopg():
    assert normalize_database_url("postgresql://u:p@h:6543/db") == (
        "postgresql+psycopg://u:p@h:6543/db"
    )
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_engine_postgres_usa_nullpool_e_sem_prepared_statements():
    engine = make_engine("postgresql+psycopg://u:p@localhost:6543/db")  # não conecta
    assert isinstance(engine.pool, NullPool)
    assert engine.dialect.name == "postgresql"
