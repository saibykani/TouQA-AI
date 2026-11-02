"""Alembic environment. The database URL comes from DATABASE_URL (app settings)."""
from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (register models)
from app.config import get_settings
from app.db import Base, configure_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    engine = configure_engine(config.attributes.get("database_url") or get_settings().database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_offline() if context.is_offline_mode() else run_online()
