"""Work out once what each standard layer holds in each place.

"What should I know about Toa Baja?" needs flood zone types, landslide levels and
land use classes there, each a measurement of a few seconds. Measured once here
and kept in place_profiles, an answer reads them at once, and every answer about
a place starts from the same figures.

The layers are the standard ones (layer_roles, from data/layer_roles.csv); the
places are the 78 municipios, and the barrios with --barrios. The measurement is
the one the assistant's what_is_in tool makes (api/repositories/spatial.kinds),
so a stored profile and a fresh one cannot differ.

A profile is only measured again when its layer's data changes.

Run:
    python -m pipelines.profile_places                    # dry run: counts only
    python -m pipelines.profile_places --commit
    python -m pipelines.profile_places --commit --barrios
"""

from __future__ import annotations

import argparse
import json
import os
import time

import psycopg2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--barrios", action="store_true", help="barrios as well as municipios")
    ap.add_argument("--all", action="store_true", help="measure again, changed or not")
    args = ap.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL not set")

    # Measured once, so given time an answer could not wait for. Set before
    # the imports: they read the settings when first used.
    os.environ["DB_STATEMENT_TIMEOUT_MS"] = "180000"
    from api.repositories import layers, places, spatial

    spatial.KINDS_AREA_MS = 180_000

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('place_profiles')")
    if cur.fetchone()[0] is None:
        raise SystemExit("place_profiles does not exist: run alembic upgrade head first")
    kinds_of_unit = ("municipio", "barrio") if args.barrios else ("municipio",)
    cur.execute(
        "SELECT unit_code FROM reference_units WHERE unit_type = ANY(%s) ORDER BY unit_code",
        (list(kinds_of_unit),),
    )
    units = [r[0] for r in cur.fetchall()]
    standard = sorted(
        {r.layer.id: r.layer for r in layers.roles().values()}.values(), key=lambda x: x.id
    )
    cur.execute(
        "SELECT id, %s || ':' || table_name || ':' || feature_count || ':' || "
        "coalesce(array_to_string(tile_properties, ','), '') FROM layer_registry WHERE id = ANY(%s)",
        (str(spatial.KINDS_VERSION), [x.id for x in standard]),
    )
    signature = dict(cur.fetchall())
    cur.execute("SELECT unit_code, layer_id, signature FROM place_profiles")
    done = {(u, lid): sig for u, lid, sig in cur.fetchall()}
    todo = [
        (u, layer)
        for u in units
        for layer in standard
        if args.all or done.get((u, layer.id)) != signature[layer.id]
    ]
    print(
        f"[place profiles] {len(units)} places x {len(standard)} standard layers; "
        f"{len(todo)} to measure"
    )
    if not args.commit:
        print("[place profiles] dry run - nothing written. Use --commit to measure and write.")
        return

    started, failed = time.monotonic(), 0
    for i, (unit, layer) in enumerate(todo, 1):
        place = places.by_code(unit)
        try:
            features = spatial.count(layer, place)
            found = spatial.kinds(layer, layers.fields(layer, "en").columns, place)
        except psycopg2.Error as exc:  # too slow, or a broken shape: left for the live tool
            failed += 1
            print(f"[place profiles] {unit} {layer.id}: {str(exc).splitlines()[0]}")
            continue
        column, rows = next(iter(found.items()), (None, []))
        cur.execute(
            """INSERT INTO place_profiles
                   (unit_code, layer_id, features, column_name, kinds, signature)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (unit_code, layer_id) DO UPDATE SET
                   features = EXCLUDED.features, column_name = EXCLUDED.column_name,
                   kinds = EXCLUDED.kinds, signature = EXCLUDED.signature, computed_at = now()""",
            (
                unit,
                layer.id,
                features,
                column,
                json.dumps([[k, n, km2] for k, n, km2 in rows], ensure_ascii=False),
                signature[layer.id],
            ),
        )
        conn.commit()
        if i % 50 == 0 or i == len(todo):
            print(f"[place profiles] {i}/{len(todo)}, {time.monotonic() - started:.0f}s")
    if failed:
        print(f"[place profiles] {failed} not measured; answers measure those when asked")


if __name__ == "__main__":
    main()
