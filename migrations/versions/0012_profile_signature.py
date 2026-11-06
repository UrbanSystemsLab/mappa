"""What each layer's profile was worked out from, so a release profiles only
the layers that changed.

pipelines/profile_layers read all 603 layer tables on every release, several
minutes, though almost none had changed. profile_signature records its inputs -
the layer's columns, feature count, La Maraña's dictionary entry for it and the
version of the profiling rules - and a layer whose signature still matches is
skipped.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS profile_signature text")


def downgrade() -> None:
    op.execute("ALTER TABLE layer_registry DROP COLUMN IF EXISTS profile_signature")
