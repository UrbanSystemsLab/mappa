"""Join map layers, documents and places in the database.

Layers, documents and places were three separate collections: an answer found a
flood layer and a mitigation plan each on its own and hoped they matched. Only
18 of 507 documents named a layer at all.

layer_documents  which documents discuss each layer, and how much: the number of
                 a document's passages close in meaning to the layer, and the
                 closest. Written by pipelines/link_layer_documents.
place_profiles   what each standard layer holds in each place, by kind - land use
                 classes with km², flood zone types, how many shelters - worked
                 out once by pipelines/profile_places, so an answer about a place
                 does not measure it again.

Each row keeps a signature of what it was computed from, so a release only
recomputes what changed.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS layer_documents (
            layer_id    text    NOT NULL REFERENCES layer_registry(id) ON DELETE CASCADE,
            document_id integer NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            passages    integer NOT NULL,
            best        real    NOT NULL,
            PRIMARY KEY (layer_id, document_id)
        );
        CREATE INDEX IF NOT EXISTS idx_layer_documents_document ON layer_documents (document_id);
        CREATE TABLE IF NOT EXISTS layer_document_runs (
            layer_id    text PRIMARY KEY REFERENCES layer_registry(id) ON DELETE CASCADE,
            signature   text NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS place_profiles (
            unit_code   text    NOT NULL,
            layer_id    text    NOT NULL REFERENCES layer_registry(id) ON DELETE CASCADE,
            features    integer NOT NULL,
            column_name text,
            kinds       jsonb   NOT NULL DEFAULT '[]',
            signature   text    NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (unit_code, layer_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS place_profiles; DROP TABLE IF EXISTS layer_document_runs; "
        "DROP TABLE IF EXISTS layer_documents;"
    )
