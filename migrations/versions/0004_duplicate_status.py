"""A catalogue row can be a duplicate of a layer that is already live.

Their inventory lists some layers more than once under different GIS IDs -
Agroturismo 2021 three times. The extra rows have no data behind them and never
will, because the data is already loaded under the first ID. Until now they sat
as 'catalogued', which meant "data not yet received", so they were counted as
missing and the gap was quoted to La Maraña as larger than it is.

'duplicate' says what they are. superseded_by records which row holds the data,
so the duplication stays traceable rather than being deleted away.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STATUSES = ("published", "loaded", "catalogued", "draft", "hidden")


def _constraint(statuses: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE layer_registry DROP CONSTRAINT IF EXISTS layer_registry_status_check")
    allowed = ", ".join(f"'{s}'" for s in statuses)
    op.execute(
        f"ALTER TABLE layer_registry ADD CONSTRAINT layer_registry_status_check "
        f"CHECK (status IN ({allowed}))"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS superseded_by text")
    _constraint((*STATUSES, "duplicate"))


def downgrade() -> None:
    # A duplicate goes back to catalogued, which is what it was before.
    op.execute("UPDATE layer_registry SET status = 'catalogued' WHERE status = 'duplicate'")
    _constraint(STATUSES)
    op.execute("ALTER TABLE layer_registry DROP COLUMN IF EXISTS superseded_by")
