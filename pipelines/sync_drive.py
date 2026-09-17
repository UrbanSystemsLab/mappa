"""Sync a Google Drive folder into the Mappa GCS raw zone.

Mirrors a Drive folder tree into gs://<RAW_BUCKET>/, **preserving the folder
hierarchy 1:1**. Faithful mirroring (rather than flattening) is required because
the partner GIS data is full of multi-file datasets that MUST stay together:

    - shapefiles        (.shp + .shx + .dbf + .prj + .cpg + .qmd sidecars)
    - Esri geodatabases (foo.gdb/ is a *folder* of files)
    - ArcGIS packages   (foo.lpkx)
    - GeoPackages        (.gpkg)

Flattening to prefix/filename would collide (every shapefile folder has a
`.prj`, every .gdb has an `a00000001.gdbtable`, etc.) and silently corrupt the
dataset. So we keep the tree.

Behavior:
    - Recurses the folder tree, resolving Drive **shortcuts** to their targets.
    - Native Google files (Docs/Sheets) are exported to Office formats.
    - A per-file `zone` (documents/spatial/tabular/eval/other) is derived from the
      extension and printed in the run summary, but does NOT change the object
      path — it feeds the catalog, not the layout.
    - Idempotent: a file is re-uploaded only when its Drive md5 differs from the
      stored object (exports have no md5, so they upload each run).

Auth: a service account with Viewer on the shared Drive folder and objectAdmin
on the bucket. Point GOOGLE_APPLICATION_CREDENTIALS at its key, or run on a GCP
resource whose attached SA has those roles.

Run:
    python -m pipelines.sync_drive --folder-id <DRIVE_FOLDER_ID> --commit
    python -m pipelines.sync_drive --folder-id <ID> --prefix capas_gis/   # scope

Env:
    RAW_BUCKET                     Target GCS bucket (e.g. mappa-pr-mappa-raw)
    GOOGLE_APPLICATION_CREDENTIALS Service-account key path (or use ADC)
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path

# Google client imports are done lazily in main() so --help / import work without them.

# Native Google Workspace types must be *exported*; (export MIME, extension).
EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# Zone tagging for the run summary / catalog (does not affect the object path).
ZONE_BY_EXT = {
    ".pdf": "documents", ".docx": "documents", ".doc": "documents", ".txt": "documents",
    ".gpkg": "spatial", ".shp": "spatial", ".shx": "spatial", ".dbf": "spatial",
    ".prj": "spatial", ".cpg": "spatial", ".qmd": "spatial", ".geojson": "spatial",
    ".tif": "spatial", ".tiff": "spatial", ".kml": "spatial", ".lpkx": "spatial",
    ".csv": "tabular", ".xlsx": "tabular", ".xls": "tabular", ".parquet": "tabular",
    ".json": "eval", ".jsonl": "eval",
}


def zone_for(name: str) -> str:
    return ZONE_BY_EXT.get(os.path.splitext(name)[1].lower(), "other")


def walk(service, folder_id: str, rel_prefix: str = "") -> list[dict]:
    """Recursively list files under folder_id, resolving shortcuts, carrying the
    relative path of each file as `rel_path`. `.gdb`/`.lpkx` folders are walked
    like any other folder so their contents mirror intact under the same subpath.
    """
    out: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=("nextPageToken, files(id, name, mimeType, md5Checksum, size, "
                        "shortcutDetails(targetId, targetMimeType))"),
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            name = f["name"]
            mime = f["mimeType"]

            # Resolve shortcuts to their target, then treat by the target's type.
            if mime == SHORTCUT_MIME:
                details = f.get("shortcutDetails") or {}
                target_id = details.get("targetId")
                target_mime = details.get("targetMimeType")
                if not target_id:
                    print(f"[sync-drive] WARN unresolved shortcut: {rel_prefix}{name}")
                    continue
                mime = target_mime or FOLDER_MIME
                f = {"id": target_id, "name": name, "mimeType": mime}

            child_rel = f"{rel_prefix}{name}"
            if mime == FOLDER_MIME:
                out.extend(walk(service, f["id"], child_rel + "/"))
            else:
                out.append({**f, "rel_path": child_rel})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def download_bytes(service, file_id: str, mime: str) -> tuple[bytes, str]:
    """Return (data, extra_extension). Native Google files are exported."""
    from googleapiclient.http import MediaIoBaseDownload

    if mime in EXPORT_MAP:
        export_mime, ext = EXPORT_MAP[mime]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        ext = ""
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue(), ext


def _md5_matches(gcs_b64_md5: str | None, drive_hex_md5: str) -> bool:
    if not gcs_b64_md5:
        return False
    try:
        return base64.b64decode(gcs_b64_md5).hex() == drive_hex_md5
    except Exception:
        return False


def sync_folder(drive, bucket, bucket_name: str, folder_id: str, prefix: str, commit: bool) -> tuple[int, int]:
    """Mirror one Drive folder into bucket/prefix. Returns (uploaded, skipped)."""
    print(f"[sync-drive] walking folder {folder_id} -> gs://{bucket_name}/{prefix}")
    files = walk(drive, folder_id)
    print(f"[sync-drive]   found {len(files)} files")
    uploaded = skipped = 0
    for f in files:
        ext = EXPORT_MAP[f["mimeType"]][1] if f["mimeType"] in EXPORT_MAP else ""
        blob_path = prefix + f["rel_path"] + ext
        blob = bucket.blob(blob_path)

        drive_md5 = f.get("md5Checksum")
        if drive_md5 and blob.exists():
            blob.reload()
            if _md5_matches(blob.md5_hash, drive_md5):
                skipped += 1
                continue

        if not commit:
            print(f"[sync-drive]   DRY would upload gs://{bucket_name}/{blob_path}")
            continue

        data, _ = download_bytes(drive, f["id"], f["mimeType"])
        blob.upload_from_string(data)
        uploaded += 1
        print(f"[sync-drive]   uploaded gs://{bucket_name}/{blob_path} ({len(data)} bytes)")
    return uploaded, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror Drive folder(s) into the GCS raw zone.")
    parser.add_argument("--config", type=str, help="Path to sources.json (syncs every source listed).")
    parser.add_argument("--folder-id", help="Single Drive folder ID (alternative to --config).")
    parser.add_argument("--bucket", default=os.environ.get("RAW_BUCKET"), help="Target GCS bucket.")
    parser.add_argument("--prefix", default="", help="Object key prefix for --folder-id mode.")
    parser.add_argument("--commit", action="store_true", help="Actually download + upload. Else dry run.")
    args = parser.parse_args()

    # Build the list of (folder_id, prefix) jobs from either the config or a single folder.
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        bucket_name = args.bucket or cfg.get("raw_bucket")
        jobs = [(s["drive_folder_id"], s.get("prefix", ""), s["name"]) for s in cfg["sources"]]
    elif args.folder_id:
        bucket_name = args.bucket
        jobs = [(args.folder_id, args.prefix, "folder")]
    else:
        raise SystemExit("Provide --config <sources.json> or --folder-id <id>.")
    if not bucket_name:
        raise SystemExit("No target bucket (set raw_bucket in config, --bucket, or RAW_BUCKET).")

    from google.cloud import storage
    from googleapiclient.discovery import build

    drive = build("drive", "v3")  # uses ADC / GOOGLE_APPLICATION_CREDENTIALS
    bucket = storage.Client().bucket(bucket_name)

    total_up = total_skip = 0
    for folder_id, prefix, name in jobs:
        print(f"[sync-drive] === source: {name} ===")
        up, skip = sync_folder(drive, bucket, bucket_name, folder_id, prefix, args.commit)
        total_up += up
        total_skip += skip

    verb = "done" if args.commit else "dry run"
    print(f"[sync-drive] {verb}. uploaded={total_up} skipped(unchanged)={total_skip}"
          + ("" if args.commit else "  — use --commit to write."))


if __name__ == "__main__":
    main()
