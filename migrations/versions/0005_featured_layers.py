"""La Maraña's prioritised layers, and their reliability rating.

They sent a Data Quality Prioritization Matrix on 28 July 2026: the layers they
consider reliable enough to show first, judged on publication date and available
metadata. It went unused for ten weeks while the map was chosen by us.

featured marks a layer as on their list. featured_note keeps what they wrote
beside it ("Needs verification"). reliability holds their colour rating -
reliable, needs review, outdated - which lives in cell colour on their sheet and
so is recorded separately once read.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS featured boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS featured_note text")
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS reliability text")
    op.execute(
        "ALTER TABLE layer_registry ADD CONSTRAINT layer_registry_reliability_check "
        "CHECK (reliability IS NULL OR reliability IN ('reliable', 'needs_review', 'outdated'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE layer_registry DROP CONSTRAINT IF EXISTS layer_registry_reliability_check"
    )
    for column in ("reliability", "featured_note", "featured"):
        op.execute(f"ALTER TABLE layer_registry DROP COLUMN IF EXISTS {column}")
