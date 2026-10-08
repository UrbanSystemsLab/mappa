"""Remove the English layer names our team wrote.

Ten layers carried an English name - "Public schools 2021", "Hospitals & CDTs" -
written by hand on our side. La Maraña's inventory has no English names at all,
so these were words nobody on their side chose. A layer now shows the name their
inventory gives it, in both languages, until they provide English names.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE layer_registry SET name_en = NULL, description_en = NULL")


def downgrade() -> None:
    # The names are not restored - they were the problem.
    pass
