-- Mappa database schema
-- Requires: PostgreSQL 16+, PostGIS extension, pgvector extension
-- Run via: psql "$DATABASE_URL" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------
-- documents: one row per source document (a PDF, DOCX, or web page)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL PRIMARY KEY,
    source_id       TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    doc_type        TEXT,
    jurisdiction    TEXT,
    year            INTEGER,
    url             TEXT,
    language        TEXT DEFAULT 'es',
    tags            TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- document_chunks: chunked text from documents, with embeddings
-- Embedding dimension = 384 for paraphrase-multilingual-MiniLM-L12-v2
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    page_number     INTEGER,
    text            TEXT NOT NULL,
    embedding       vector(384),
    location_tags   TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_document_chunks_location_tags
    ON document_chunks USING gin (location_tags);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks (document_id);

-- ---------------------------------------------------------------
-- spatial_layers: one row per ingested GeoPackage/shapefile layer
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spatial_layers (
    id                  SERIAL PRIMARY KEY,
    layer_name          TEXT UNIQUE NOT NULL,
    source_file         TEXT,
    source_srid         INTEGER,
    geometry_type       TEXT,
    feature_count       INTEGER,
    year                INTEGER,
    theme               TEXT,
    description         TEXT,
    ingested_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- reference_units: canonical location identifiers
-- (municipios, barrios, or whatever the partner decides on).
-- Each row has a canonical id, name, type, and geometry (WGS84).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reference_units (
    id              SERIAL PRIMARY KEY,
    unit_code       TEXT UNIQUE NOT NULL,
    unit_type       TEXT NOT NULL,
    name            TEXT NOT NULL,
    parent_code     TEXT,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_units_geom
    ON reference_units USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_reference_units_unit_type
    ON reference_units (unit_type);

-- ---------------------------------------------------------------
-- Note on per-layer feature tables:
-- Each ingested spatial layer gets its own table named layer_<layer_name>
-- (populated by ogr2ogr in pipelines/ingest_spatial.py). This keeps
-- attribute schemas layer-specific without forcing a superset schema.
-- ---------------------------------------------------------------
