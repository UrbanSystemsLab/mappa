"""Copy the live database (mappa) into staging (mappa_staging), on the server itself.

No Google Cloud permissions are needed and nothing passes through this laptop.
The staging database reads the live one over the database server's own address
and copies table by table; this script only sends the commands. The earlier way
- downloading 27 GB and uploading it again - would have taken most of a day, and
Google's own export needs a Cloud SQL role our accounts do not have.

The live database is only ever read. Staging is emptied and rebuilt each run.
While it runs, the live site shares the server's CPU with the copy and may be
somewhat slower.

    1. empty staging
    2. create every table, empty, exactly as in production   (pg_dump, structure only)
    3. copy the rows across, app tables and map layers first
    4. add the indexes and constraints                       (pg_dump, structure only)
    5. carry each counter's current value across
    6. remove the temporary link and check the result

Run:
    ./venv/bin/python scripts/copy_prod_to_staging.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import NOT_LAYER_TABLES

ROOT = Path(__file__).resolve().parents[1]
BIN = Path("/opt/homebrew/opt/libpq/bin")
PROJECT = os.environ.get("GCP_PROJECT", "mappa-lamarana-aecc")
INSTANCE = os.environ.get("CLOUDSQL_INSTANCE", "mappa-pg")
LIVE, STAGING = "mappa", "mappa_staging"


def password() -> str:
    return (ROOT / ".mappa_db_pw").read_text().strip()


def dsn(db: str) -> str:
    # Keepalives, because one table can take minutes during which the connection
    # carries nothing - and the link to the server dropped exactly then, at
    # table 609 of 636 on the first full run.
    return (
        f"postgresql://mappa:{password()}@127.0.0.1:5432/{db}"
        "?keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=6"
    )


def server_address() -> str:
    """The database server's own public address. The server refuses to connect
    to itself through 127.0.0.1, but accepts its public address."""
    out = subprocess.run(
        [
            "gcloud",
            "sql",
            "instances",
            "describe",
            INSTANCE,
            "--project",
            PROJECT,
            "--format=json(ipAddresses)",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return next(a["ipAddress"] for a in json.loads(out)["ipAddresses"] if a["type"] == "PRIMARY")


def structure(section: str) -> None:
    """Copy one part of the live structure into staging, through pg_dump. Small:
    it is table definitions, not rows."""
    env = {**os.environ, "PGPASSWORD": password()}
    dump = subprocess.run(
        [
            BIN / "pg_dump",
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            "mappa",
            "-d",
            LIVE,
            "--schema-only",
            f"--section={section}",
            "--no-owner",
            "--no-acl",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    res = subprocess.run(
        [BIN / "psql", "-h", "127.0.0.1", "-p", "5432", "-U", "mappa", "-d", STAGING, "-q"],
        input=dump,
        capture_output=True,
        text=True,
        env=env,
    )
    # Extensions already exist in staging; anything else that fails is reported.
    errors = [
        ln
        for ln in res.stderr.splitlines()
        if "ERROR" in ln and "already exists" not in ln and "extension" not in ln.lower()
    ]
    for e in errors[:10]:
        print(f"      ! {e}")
    print(f"      {section}: {'ok' if not errors else f'{len(errors)} errors'}", flush=True)


def main() -> None:
    # --resume carries on after an interrupted run: staging is not emptied, and
    # only tables that are still empty are copied.
    resume = "--resume" in sys.argv
    started = time.monotonic()
    host = server_address()
    live = psycopg2.connect(dsn(LIVE))
    live.set_session(readonly=True)
    staging = psycopg2.connect(dsn(STAGING))
    staging.autocommit = True
    s = staging.cursor()
    s.execute("SET statement_timeout = 0")  # one table can take minutes

    if resume:
        print("Resuming: keeping staging as it is and copying only empty tables", flush=True)
    else:
        reset_and_create(s)
    link(s, host)
    copy_tables(live, s)
    finish(live, s, host, started)


def reset_and_create(s) -> None:
    print("1/6  Emptying staging", flush=True)
    s.execute("DROP SCHEMA IF EXISTS prod_src CASCADE")
    s.execute("DROP SCHEMA IF EXISTS copy_tools CASCADE")
    s.execute("DROP SERVER IF EXISTS prod_src CASCADE")
    s.execute("DROP SCHEMA public CASCADE")
    s.execute("CREATE SCHEMA public")
    s.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    s.execute("CREATE EXTENSION IF NOT EXISTS vector")

    print("2/6  Creating the tables, empty", flush=True)
    structure("pre-data")


def link(s, host: str) -> None:
    """The temporary link: staging reads the live database as foreign tables."""
    s.execute("DROP SCHEMA IF EXISTS prod_src CASCADE")
    s.execute("DROP SERVER IF EXISTS prod_src CASCADE")
    s.execute("DROP SCHEMA IF EXISTS copy_tools CASCADE")
    s.execute("CREATE SCHEMA copy_tools")
    s.execute("CREATE EXTENSION postgres_fdw SCHEMA copy_tools")
    s.execute("CREATE EXTENSION dblink SCHEMA copy_tools")
    s.execute(
        "CREATE SERVER prod_src FOREIGN DATA WRAPPER postgres_fdw OPTIONS "
        "(host %s, dbname %s, sslmode 'require', fetch_size '20000')",
        (host, LIVE),
    )
    s.execute(
        "CREATE USER MAPPING FOR CURRENT_USER SERVER prod_src OPTIONS (user 'mappa', password %s)",
        (password(),),
    )
    s.execute("CREATE SCHEMA prod_src")
    s.execute("IMPORT FOREIGN SCHEMA public FROM SERVER prod_src INTO prod_src")


def copy_tables(live, s) -> None:
    # What the app needs first, so the useful part of staging is ready soonest:
    # its own tables, then the map layers, then the hidden ones.
    with live.cursor() as c:
        c.execute(
            """
            SELECT t.relname, pg_total_relation_size(t.oid),
                   CASE WHEN t.relname NOT LIKE 'layer\\_%%' OR t.relname = ANY(%s) THEN 0
                        WHEN r.status = 'published' THEN 1 WHEN r.status = 'loaded' THEN 2 ELSE 3 END
            FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace
            LEFT JOIN layer_registry r ON r.table_name = t.relname
            WHERE n.nspname = 'public' AND t.relkind = 'r'
              -- Tables that come with an extension (PostGIS's spatial_ref_sys)
              -- already exist in staging, filled by the extension itself.
              AND NOT EXISTS (SELECT 1 FROM pg_depend d
                              WHERE d.objid = t.oid AND d.deptype = 'e')
            ORDER BY 3, 2""",
            (list(NOT_LAYER_TABLES),),
        )
        tables = c.fetchall()
    total_bytes = sum(b for _, b, _ in tables)

    print(f"3/6  Copying {len(tables)} tables ({total_bytes / 1e9:.1f} GB)", flush=True)
    done_bytes = 0
    copied: dict[str, int] = {}
    for i, (name, size, _) in enumerate(tables, 1):
        t0 = time.monotonic()
        s.execute(f'SELECT EXISTS (SELECT 1 FROM public."{name}")')
        if s.fetchone()[0]:
            done_bytes += size  # copied by an earlier run
            continue
        s.execute(f'INSERT INTO public."{name}" SELECT * FROM prod_src."{name}"')
        copied[name] = s.rowcount
        done_bytes += size
        if size > 50e6 or i % 50 == 0 or i == len(tables):
            print(
                f"      {i:>4}/{len(tables)}  {done_bytes / total_bytes:5.1%}  "
                f"{name[:48]:<48} {s.rowcount:>9,} rows  {time.monotonic() - t0:5.0f}s",
                flush=True,
            )


def finish(live, s, host: str, started: float) -> None:
    print("4/6  Adding indexes and constraints", flush=True)
    structure("post-data")

    print("5/6  Carrying counters across", flush=True)
    s.execute(
        """SELECT name, last_value FROM copy_tools.dblink(
                   (SELECT 'host=' || %s || ' dbname=' || %s || ' user=mappa sslmode=require password=' || %s),
                   'SELECT schemaname || ''.'' || sequencename, last_value FROM pg_sequences
                    WHERE schemaname = ''public'' AND last_value IS NOT NULL')
                 AS t(name text, last_value bigint)""",
        (host, LIVE, password()),
    )
    for name, value in s.fetchall():
        s.execute("SELECT setval(%s, %s)", (name, value))

    print("6/6  Removing the temporary link and checking", flush=True)
    s.execute("DROP SCHEMA prod_src CASCADE")
    s.execute("DROP USER MAPPING FOR CURRENT_USER SERVER prod_src")
    s.execute("DROP SERVER prod_src CASCADE")
    s.execute("DROP SCHEMA copy_tools CASCADE")
    s.execute("ANALYZE")

    check = (
        "SELECT (SELECT count(*) FROM layer_registry), (SELECT count(*) FROM documents), "
        "(SELECT count(*) FROM document_chunks), (SELECT count(*) FROM reference_units)"
    )
    with live.cursor() as c:
        c.execute(check)
        a = c.fetchone()
    s.execute(check)
    b = s.fetchone()
    print(f"      live:    {a[0]} layers, {a[1]} documents, {a[2]:,} chunks, {a[3]:,} places")
    print(f"      staging: {b[0]} layers, {b[1]} documents, {b[2]:,} chunks, {b[3]:,} places")
    # Every table, against the live one - a resumed run cannot rely on its own
    # tally of what an earlier run copied.
    mismatched = []
    with live.cursor() as c:
        c.execute("""SELECT relname FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace
                     WHERE n.nspname = 'public' AND t.relkind = 'r'
                       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e')""")
        names = [r[0] for r in c.fetchall()]
        for name in names:
            c.execute(f'SELECT count(*) FROM public."{name}"')
            n = c.fetchone()[0]
            s.execute(f'SELECT count(*) FROM public."{name}"')
            if s.fetchone()[0] != n:
                mismatched.append(name)
    for name in mismatched[:10]:
        print(f"      ! {name} differs")
    ok = a == b and not mismatched
    print(f"      every table's row count matches what was copied: {not mismatched}")
    print(
        f"\n{'Done' if ok else 'FINISHED WITH DIFFERENCES'} in {(time.monotonic() - started) / 60:.0f} min. "
        f"Staging is a copy of production as of {time.strftime('%Y-%m-%d %H:%M')}."
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
