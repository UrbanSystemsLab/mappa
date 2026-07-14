# Postgres 16 with PostGIS 3.4 AND pgvector.
# Base image already has PostGIS; we install pgvector on top.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
