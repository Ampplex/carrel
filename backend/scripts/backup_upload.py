"""Read a database dump on stdin, put it in S3, prune old ones.

Runs inside the API container because that is where boto3 and the AWS
credentials already are. Installing the AWS CLI on the host would mean ~100MB
on a volume shared with a production MCP server, and a second copy of the
credentials to keep in step.

    docker exec carrel-db pg_dump -U carrel -d carrel --clean --if-exists \
      | gzip -9 \
      | docker exec -i carrel-api python /app/scripts/backup_upload.py
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

# Python puts the *script's* directory on sys.path, not the working directory,
# so running this as /app/scripts/backup_upload.py cannot see /app/app however
# the caller sets -w. Fixing it here rather than requiring PYTHONPATH on the
# command line: a script that only works when invoked exactly one way is a
# script that fails in cron at three in the morning.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402

from app.config import settings  # noqa: E402

KEEP_DAYS = 30
PREFIX = "carrel/backups"

# A dump smaller than this means pg_dump failed and wrote almost nothing.
# Uploading it would replace good backups with an empty file — the failure mode
# you only discover on the day you need the backup.
MIN_PLAUSIBLE_BYTES = 1000


def main() -> int:
    body = sys.stdin.buffer.read()
    if len(body) < MIN_PLAUSIBLE_BYTES:
        print(f"FAILED: dump is only {len(body)} bytes, refusing to upload", file=sys.stderr)
        return 1

    if not settings.s3_bucket:
        print("FAILED: CARREL_S3_BUCKET is not set", file=sys.stderr)
        return 1

    s3 = boto3.client("s3", region_name=settings.s3_region)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    key = f"{PREFIX}/carrel-{stamp}.sql.gz"

    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=body)
    print(f"ok: {len(body)} bytes -> s3://{settings.s3_bucket}/{key}")

    # Age out old dumps here rather than with a bucket lifecycle rule: the
    # bucket is shared with Reeve's image store, and a lifecycle rule scoped
    # slightly too wide would start deleting photographs.
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    listing = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=f"{PREFIX}/")
    for obj in listing.get("Contents", []):
        if obj["LastModified"] < cutoff:
            s3.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
            print(f"pruned {obj['Key']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
