"""What a layer holds, in words, so a question can find it.

Most layers have no description, and many names say little ("Base Map CRIM OGP
Hydrography 2006"). content_summary is written by pipelines/profile_layers from
the layer's own data - its main categories and a sample of its feature names -
and is part of the text a layer is searched by.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS content_summary text")


def downgrade() -> None:
    op.execute("ALTER TABLE layer_registry DROP COLUMN IF EXISTS content_summary")
