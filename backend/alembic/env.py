import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from app.database import Base
from app.models import *  # noqa: F401,F403 -- registers all models on Base.metadata

load_dotenv()

# Read DATABASE_URL directly from the environment rather than routing it
# through alembic's Config/ConfigParser (config.set_main_option / get_section):
# ConfigParser's %-interpolation rejects any literal "%" (e.g. a correctly
# percent-encoded password like samiksha%40eduopsai) unless doubled to "%%",
# which in turn silently corrupts the value for anything that DOESN'T go
# through ConfigParser (i.e. the real app in app/database.py).
DATABASE_URL = os.environ["DATABASE_URL"]

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
