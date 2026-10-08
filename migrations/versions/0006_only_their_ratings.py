"""A layer's trust rating is shown only where La Maraña gave one.

The registry derived a rating for every layer by counting how many of four
fields their inventory row filled in - four meant 'confirmed', two or three meant
'inferred'. Nobody asked for that, and it used their own words for something
else: to their team 'inferido' means they investigated and worked it out from
evidence. 698 layers carried a rating of that kind. Their team has rated 24, in
the reconstructed metadata workbooks.

Those 24 keep their rating. Every other layer now has none, and the app shows
nothing rather than a word nobody on their side chose.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE layer_registry ALTER COLUMN metadata_status DROP NOT NULL")
    op.execute("ALTER TABLE layer_registry ALTER COLUMN metadata_status DROP DEFAULT")
    op.execute("UPDATE layer_registry SET metadata_status = NULL WHERE metadata_source IS NULL")


def downgrade() -> None:
    # The derived ratings are not recreated - they were the problem.
    op.execute(
        "UPDATE layer_registry SET metadata_status = 'unknown' WHERE metadata_status IS NULL"
    )
    op.execute("ALTER TABLE layer_registry ALTER COLUMN metadata_status SET DEFAULT 'unknown'")
    op.execute("ALTER TABLE layer_registry ALTER COLUMN metadata_status SET NOT NULL")
