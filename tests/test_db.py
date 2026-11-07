from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.models import Base, in_the_models
from app.db.session import make_engine, upgrade_db


def test_migrations_match_models(tmp_path):
    db = tmp_path / "x.db"
    upgrade_db(db)
    with make_engine(db).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"include_name": in_the_models}), Base.metadata)
    assert diff == []
