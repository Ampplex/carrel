#!/usr/bin/env bash
# Nightly database dump to S3.
#
# Photos already live in S3 and Reeve holds the memories themselves, so this is
# the only copy of accounts, sessions, conversations and photo metadata. Losing
# the EC2's volume without this means every account and every transcript is
# gone — the photographs would still be in the bucket, with nothing left that
# knows whose they are.
#
# Install on the box:
#   chmod +x ~/carrel/deploy/backup.sh
#   ( crontab -l 2>/dev/null; echo "17 3 * * * $HOME/carrel/deploy/backup.sh >> $HOME/carrel/backup.log 2>&1" ) | crontab -
#
# 03:17 rather than 03:00 because everyone schedules things on the hour.

set -euo pipefail

BUCKET="${CARREL_S3_BUCKET:-reeve-images-prod-147010141808}"
PREFIX="${CARREL_BACKUP_PREFIX:-carrel/backups}"
KEEP_DAYS=30

# Credentials come from the same env file the API uses. Sourced rather than
# duplicated: two copies of a secret drift, and the stale one is always the one
# still in use somewhere.
ENV_FILE="$(dirname "$0")/carrel.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
DUMP="/tmp/carrel-${STAMP}.sql.gz"

# --clean --if-exists so the dump can be restored over an existing database
# without hand-editing it at the worst possible moment.
docker exec carrel-db pg_dump -U carrel -d carrel --clean --if-exists \
    | gzip -9 > "$DUMP"

SIZE=$(stat -c%s "$DUMP" 2>/dev/null || stat -f%z "$DUMP")
if [ "$SIZE" -lt 1000 ]; then
    # A dump this small means pg_dump failed and wrote almost nothing. Uploading
    # it would quietly replace good backups with an empty file — the failure
    # mode where you discover the problem only when you need the backup.
    echo "$(date -uIs) FAILED: dump is only ${SIZE} bytes, refusing to upload"
    rm -f "$DUMP"
    exit 1
fi

aws s3 cp "$DUMP" "s3://${BUCKET}/${PREFIX}/carrel-${STAMP}.sql.gz" --only-show-errors
rm -f "$DUMP"
echo "$(date -uIs) ok: ${SIZE} bytes -> s3://${BUCKET}/${PREFIX}/carrel-${STAMP}.sql.gz"

# Age out old dumps. Done here rather than with a bucket lifecycle rule because
# the bucket is shared with Reeve's image store, and a lifecycle rule scoped
# slightly too wide would start deleting photographs.
CUTOFF=$(date -u -d "${KEEP_DAYS} days ago" +%Y-%m-%d 2>/dev/null || date -u -v-${KEEP_DAYS}d +%Y-%m-%d)
aws s3 ls "s3://${BUCKET}/${PREFIX}/" | while read -r _ _ _ key; do
    [ -z "${key:-}" ] && continue
    stamp="${key#carrel-}"; stamp="${stamp%%T*}"
    if [[ "$stamp" < "$CUTOFF" ]]; then
        aws s3 rm "s3://${BUCKET}/${PREFIX}/${key}" --only-show-errors
        echo "$(date -uIs) pruned ${key}"
    fi
done
