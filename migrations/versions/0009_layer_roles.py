"""Which layer does which job, recorded in the database instead of the code.

The code named 32 layer tables directly - "the flood layer is
layer_g23_riesgo_inundacion_fema_firms_2009" - in three separate hand-written
lists that did overlapping jobs. Changing which layer answers a flood question,
or adding one, meant editing code and deploying.

A role is a job a layer does for the assistant: 'flood' is the layer a flood
question is answered from, 'schools' the one schools are counted in. The words
that call it, whether its features can be counted, and whether a map click
checks it, are all data. The roles themselves come from data/layer_roles.csv.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS layer_roles (
            role             text PRIMARY KEY,
            layer_id         text NOT NULL REFERENCES layer_registry(id) ON UPDATE CASCADE,
            words            text[] NOT NULL DEFAULT '{}',
            countable        boolean NOT NULL DEFAULT false,
            checked_on_click boolean NOT NULL DEFAULT false,
            name_col         text,
            muni_col         text,
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS layer_roles")
