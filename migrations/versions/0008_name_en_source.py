"""Record where each English layer name came from.

English names are machine translations of La Maraña's own names, reviewed in
data/layer_names_en.csv. The source is stored beside each one, so a translation
can always be told apart from a name La Maraña wrote, and replaced by theirs.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS name_en_source text")


def downgrade() -> None:
    op.execute("ALTER TABLE layer_registry DROP COLUMN IF EXISTS name_en_source")
