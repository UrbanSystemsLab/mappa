"""Baseline: the schema as it stood before migrations existed.

Eleven ALTER TABLE statements were scattered through pipeline scripts and applied
to whatever database happened to be connected. There was no history and no way to
rebuild - which mattered beyond tidiness, because La Maraña has to be able to
stand this up themselves after handover.

This captures the core schema. The 600-odd layer_* tables are deliberately not
here: they are created by the loading pipeline from the GeoPackages La Maraña
supply, and their shape follows the source data rather than a fixed definition.

Revision ID: 0001
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Accent-insensitive comparison without requiring the unaccent extension,
    # which is not available on every managed Postgres.
    op.execute("""
        CREATE OR REPLACE FUNCTION unaccent_fallback(t text) RETURNS text AS $$
          SELECT translate($1, 'áéíóúñüÁÉÍÓÚÑÜ', 'aeiounuAEIOUNU')
        $$ LANGUAGE sql IMMUTABLE
    """)

    # ── La Maraña's own inventories, held verbatim ──────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_registry (
            doc_id text PRIMARY KEY,
            title text, year integer, author text, doc_type text,
            jurisdiction text, region text, municipio text, community text,
            category text, subcategory text, source_link text, file_location text,
            file_format text, available text, accessibility text, currency text,
            identified_gap text, action_required text, related_layer text,
            status text, comments text, source_inventory text,
            load_state text NOT NULL DEFAULT 'not_attempted',
            load_note text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT document_registry_load_state_check CHECK (load_state IN
                ('not_attempted','staged','loaded','failed_link','no_text_layer','excluded'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS layer_inventory (
            gis_id text PRIMARY KEY,
            layer_name text, platform_name text, gdb_name text, original_name text,
            feature_dataset text, geometry_type text, category text, subcategory text,
            file_format text, description text, data_source text,
            publication_date text, revision_date text, coverage text, crs text,
            attribute_defs text, usage_restrictions text, related_document text,
            identified_gap text, quality_level text, priority text, status text,
            source_inventory text, served_layer_id text,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    # ── The catalogue the product reads: one row per layer ──────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS layer_registry (
            id text PRIMARY KEY,
            gis_id text,
            table_name text,
            name_es text NOT NULL, name_en text,
            description_es text, description_en text,
            category text NOT NULL, subcategory text, theme text,
            keywords text[],
            source_agency text, source_inventory text, source_url text,
            vintage_year integer, license text,
            metadata_status text NOT NULL DEFAULT 'unknown',
            geometry_type text, srid integer NOT NULL DEFAULT 4326,
            feature_count bigint,
            min_zoom integer DEFAULT 0, max_zoom integer DEFAULT 14,
            label_column text, sublabel_column text,
            style jsonb DEFAULT '{}'::jsonb,
            dataset_version text NOT NULL DEFAULT '1',
            status text NOT NULL DEFAULT 'published',
            tile_properties text[], simplified boolean NOT NULL DEFAULT false,
            property_labels jsonb DEFAULT '{}'::jsonb,
            value_labels jsonb DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT layer_registry_metadata_status_check CHECK (metadata_status IN
                ('confirmed','inferred','reconstructed','unknown')),
            CONSTRAINT layer_registry_status_check CHECK (status IN
                ('published','loaded','catalogued','draft','hidden'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_layer_registry_status ON layer_registry (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_layer_registry_category ON layer_registry (category, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_layer_registry_gis ON layer_registry (gis_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_layer_registry_keywords ON layer_registry USING gin (keywords)")

    # ── Documents and their searchable passages ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id bigserial PRIMARY KEY,
            source_id text UNIQUE NOT NULL,
            title text, doc_type text, jurisdiction text,
            year integer, url text, language text, tags text[],
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id bigserial PRIMARY KEY,
            document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            page_number integer,
            text text NOT NULL,
            embedding vector(384),
            location_tags text[],
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (document_id, chunk_index)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks (document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_location_tags ON document_chunks USING gin (location_tags)")
    # HNSW finds the nearest meaning without comparing against all 110,784.
    op.execute("""CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
                  ON document_chunks USING hnsw (embedding vector_cosine_ops)""")

    # ── Named geography: the places a question can be about ────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reference_units (
            id bigserial PRIMARY KEY,
            unit_type text NOT NULL,
            unit_code text UNIQUE,
            name text NOT NULL,
            geom geometry(MultiPolygon, 4326)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reference_units_geom ON reference_units USING gist (geom)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reference_units_unit_type ON reference_units (unit_type)")


def downgrade() -> None:
    for table in ("document_chunks", "documents", "reference_units",
                  "layer_registry", "layer_inventory", "document_registry"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS unaccent_fallback(text)")
