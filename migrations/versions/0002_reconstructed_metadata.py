"""Fields for the metadata La Maraña reconstructed, and layer embeddings.

Their team spent months working out where each layer came from and wrote it up
one workbook per theme. The registry had nowhere to put most of it. Separately,
layers gained an embedding so a question can find any of the 601 by meaning
rather than the fifteen listed in a hand-written dictionary.

These were applied as ad-hoc ALTER statements inside pipeline scripts. This is
the same change, recorded.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

COLUMNS = {
    # From their reconstructed metadata workbooks.
    "purpose": "text",
    "limitation": "text",
    "federal_agency": "text",
    "original_metadata": "text",
    "metadata_reference": "text",
    "metadata_source": "text",
    # So a layer can be found the way a document is.
    "embedding": "vector(384)",
    "embed_text": "text",
}


def upgrade() -> None:
    for name, kind in COLUMNS.items():
        op.execute(f"ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS {name} {kind}")


def downgrade() -> None:
    for name in COLUMNS:
        op.execute(f"ALTER TABLE layer_registry DROP COLUMN IF EXISTS {name}")
