#!/bin/bash
# ============================================================================
# gis database backup — runs ON THE SYNOLOGY via Task Scheduler
# ============================================================================
# Setup (once):
#   1. Control Panel -> Shared Folder -> Create: "gis_backups" (volume1)
#   2. Control Panel -> Task Scheduler -> Create -> Scheduled Task
#      -> User-defined script, User: root, Daily 03:00
#   3. Paste the contents of this file as the script (or:
#      bash /volume1/<share>/clean/backup/synology_backup_gis.sh)
#   4. Task Settings -> "Send run details by email" + "only when abnormal"
#
# What it does:
#   - Daily full dump of gis, rotating Mon..Sun  (gis_Mon.dump ... gis_Sun.dump)
#   - Extra dump of sp_geodata only (the irreplaceable curated data)
#   - Monthly keeper on the 1st of each month
#   - Fails loudly (non-zero exit) if the dump is missing or suspiciously small
# ============================================================================

set -u
CONTAINER=postgis
DB=gis
# Run pg_dump as OS user "postgres" with db superuser "postgres":
# the container's local socket uses peer auth, so OS user must match db user.
# (docker exec defaults to root -> "Peer authentication failed for user docker")
DBUSER=postgres
EXECUSER=postgres
BACKUP_DIR=/volume1/gis_backups/gis
MIN_BYTES=20000000          # fail if full dump < ~20 MB (expected ~100+ MB)

mkdir -p "$BACKUP_DIR"

DAY=$(date +%a)             # Mon, Tue, ...
STAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$STAMP] gis backup starting -> $BACKUP_DIR"

# --- 1. Full database dump (custom format, compressed) ----------------------
FULL="$BACKUP_DIR/gis_${DAY}.dump"
if ! docker exec -u "$EXECUSER" "$CONTAINER" pg_dump -U "$DBUSER" -Fc "$DB" > "$FULL.tmp"; then
    echo "ERROR: pg_dump failed (container down? auth?)" >&2
    rm -f "$FULL.tmp"
    exit 1
fi
mv "$FULL.tmp" "$FULL"

SIZE=$(stat -c%s "$FULL")
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
    echo "ERROR: dump suspiciously small ($SIZE bytes) — check database!" >&2
    exit 1
fi
echo "  full dump OK: $FULL ($((SIZE / 1024 / 1024)) MB)"

# --- 2. Curated sp_geodata only (small, irreplaceable) -----------------------
CURATED="$BACKUP_DIR/sp_geodata_latest.dump"
if docker exec -u "$EXECUSER" "$CONTAINER" pg_dump -U "$DBUSER" -Fc -n sp_geodata "$DB" > "$CURATED.tmp"; then
    mv "$CURATED.tmp" "$CURATED"
    echo "  sp_geodata dump OK: $CURATED"
else
    echo "WARNING: sp_geodata dump failed" >&2
    rm -f "$CURATED.tmp"
fi

# --- 3. Monthly keeper on the 1st --------------------------------------------
if [ "$(date +%d)" = "01" ]; then
    cp "$FULL" "$BACKUP_DIR/gis_monthly_$(date +%Y%m).dump"
    echo "  monthly keeper saved"
    # keep only the last 6 monthly keepers
    ls -1t "$BACKUP_DIR"/gis_monthly_*.dump 2>/dev/null | tail -n +7 | xargs -r rm -f
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] gis backup done."
exit 0
