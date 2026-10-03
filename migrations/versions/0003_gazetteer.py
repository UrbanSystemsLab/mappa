"""The gazetteer: every named place, not only the 78 municipalities.

reference_units was built for municipalities, so it had no room for the fact
that a barrio belongs to one, and no way to record that a name is also an
ordinary Spanish word. Both are needed before anything smaller than a
municipality can be resolved from a question: there is a Barrio Pueblo in 74 of
the 78, and a barrio called Playa.

The rows themselves come from pipelines/build_gazetteer.py, which reads the
barrio and comunidad especial layers. This only makes the columns exist.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS parent_name text")
    op.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS source_table text")
    op.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS common_word boolean")
    # Resolution looks every place up by name, and scopes every query by code.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reference_units_name ON reference_units (lower(name))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reference_units_name")
    for column in ("common_word", "source_table", "parent_name"):
        op.execute(f"ALTER TABLE reference_units DROP COLUMN IF EXISTS {column}")
