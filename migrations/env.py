"""Alembic environment: uses DATABASE_URL and the shared SQLAlchemy models."""
from alembic import context
from vp_shared import db, models  # noqa: F401  (registers tables)

target_metadata = db.Base.metadata


def run_offline() -> None:
    context.configure(url=db._normalise(db.get_settings().database_url), target_metadata=target_metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    with db.engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
