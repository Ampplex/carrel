#!/usr/bin/env bash
# Nightly database dump to S3.
#
# Photos already live in S3 and the memories themselves are in Reeve, so this
# is the only copy of accounts, conversations and photo metadata. Losing the
# EC2's volume without this leaves the photographs sitting in the bucket with
# nothing left that knows whose they are.
#
# The dump is piped through the API container, which already holds boto3 and
# the AWS credentials. Installing the AWS CLI on the host would cost ~100MB on
# a volume shared with a production MCP server, and a second copy of the
# credentials to keep in step with the first.
#
# Install:
#   chmod +x ~/carrel/deploy/backup.sh
#   ( crontab -l 2>/dev/null; echo "17 3 * * * $HOME/carrel/deploy/backup.sh >> $HOME/carrel/backup.log 2>&1" ) | crontab -
#
# 03:17 rather than 03:00 because everything else in the world runs on the hour.

set -euo pipefail

# set -o pipefail matters more than usual here: without it a failing pg_dump
# would still exit 0 as long as the upload succeeded, and the upload would
# happily write whatever partial output it received.
docker exec carrel-db pg_dump -U carrel -d carrel --clean --if-exists \
    | gzip -9 \
    | docker exec -i carrel-api python /app/scripts/backup_upload.py

echo "$(date -uIs) backup finished"
