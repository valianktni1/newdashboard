#!/usr/bin/env bash
# Update the two existing stacks, preserve rollback images and pair a read-only feed.
set -Eeuo pipefail
umask 077
booking_dir="${WBM_BOOKING_STACK:-/mnt/apps/dockge/data/bookingsystem2026}"
dashboard_dir="${WBM_DASHBOARD_STACK:-/mnt/apps/dockge/data/newdashboard}"
booking=(docker compose --project-directory "$booking_dir" -f "$booking_dir/compose.yaml")
dashboard=(docker compose --project-directory "$dashboard_dir" -f "$dashboard_dir/compose.yaml")
for directory in "$booking_dir" "$dashboard_dir"; do
  test -f "$directory/.env" && test -f "$directory/compose.yaml" || {
    echo "STOP: existing .env or compose.yaml missing in $directory"; exit 1;
  }
done
command -v python3 >/dev/null
command -v curl >/dev/null
# Do not silently rebuild an old local source checkout or a different application.
"${booking[@]}" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); b=c["services"]["app"]["build"]; u=b["context"] if isinstance(b,dict) else b; assert u in ("https://github.com/valianktni1/bookingsystem2026.git","https://github.com/valianktni1/bookingsystem2026.git#main"), "Booking build must use the existing GitHub main source"'
"${dashboard[@]}" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); b=c["services"]["dashboard"]["build"]; u=b["context"] if isinstance(b,dict) else b; assert u in ("https://github.com/valianktni1/newdashboard.git","https://github.com/valianktni1/newdashboard.git#main"), "Dashboard build must use the existing GitHub main source"'
stamp=$(date +%Y%m%d-%H%M%S)
booking_backup="$booking_dir/deployment-backups/control-centre-$stamp"
dashboard_backup="$dashboard_dir/deployment-backups/control-centre-$stamp"
mkdir -p "$booking_backup" "$dashboard_backup"
cp "$booking_dir/.env" "$booking_backup/app.env"
cp "$dashboard_dir/.env" "$dashboard_backup/app.env"
cp "$booking_dir/compose.yaml" "$booking_backup/compose.yaml"
cp "$dashboard_dir/compose.yaml" "$dashboard_backup/compose.yaml"
echo '1/6 Backing up both databases and preserving the current images...'
"${booking[@]}" exec -T database sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$booking_backup/bookingapp.dump"
test -s "$booking_backup/bookingapp.dump"
"${booking[@]}" exec -T database pg_restore --list < "$booking_backup/bookingapp.dump" >/dev/null
"${dashboard[@]}" exec -T dashboard python -c 'import sqlite3,datetime; p="/data/control-centre-before-v120-"+datetime.datetime.now().strftime("%Y%m%d-%H%M%S")+".db"; s=sqlite3.connect("/data/control-centre.db"); d=sqlite3.connect(p); s.backup(d); d.close(); s.close(); print("Dashboard backup:",p)'
for target in booking dashboard; do
  if [[ "$target" == booking ]]; then
    container=$("${booking[@]}" ps -q app); service=app; backup="$booking_backup"
  else
    container=$("${dashboard[@]}" ps -q dashboard); service=dashboard; backup="$dashboard_backup"
  fi
  test -n "$container"
  old_image=$(docker inspect --format '{{.Image}}' "$container")
  rollback_image="wbm-$target-connection-rollback:$stamp"
  docker image tag "$old_image" "$rollback_image"
  printf 'services:\n  %s:\n    image: %s\n    pull_policy: never\n' "$service" "$rollback_image" > "$backup/rollback.yaml"
done
echo "Booking backup and rollback files: $booking_backup"
echo "Dashboard settings and rollback files: $dashboard_backup"
echo '2/6 Building both updates while the old containers keep running...'
"${booking[@]}" build --no-cache app
"${dashboard[@]}" build --no-cache dashboard
echo '3/6 Checking that the new images contain both sides of the connection...'
"${booking[@]}" run --rm --no-deps --entrypoint python app -c 'from app.main import app; assert any(r.path=="/api/integrations/control-centre/overview" for r in app.routes); print("Booking feed present")'
"${dashboard[@]}" run --rm --no-deps --entrypoint python dashboard -c 'from app.main import app; assert any(r.path=="/api/booking/overview" for r in app.routes); print("Dashboard connection present")'
echo '4/6 Configuring a private shared key without displaying it...'
helper=$(mktemp /tmp/wbm-connect-booking.XXXXXX.py)
trap 'rm -f "$helper"' EXIT
curl -fL https://raw.githubusercontent.com/valianktni1/newdashboard/main/scripts/connect-booking.py -o "$helper"
python3 "$helper" --booking-stack "$booking_dir" --dashboard-stack "$dashboard_dir"
echo '5/6 Starting both updated apps...'
"${booking[@]}" up -d --no-deps app
"${dashboard[@]}" up -d --no-deps dashboard
echo '6/6 Checking the live read-only connection...'
ready=0
for attempt in {1..20}; do
  if "${dashboard[@]}" exec -T dashboard python -c 'from app.booking_connection import booking_snapshot; s=booking_snapshot(); assert s["status"]=="connected",s["message"]; print("Read-only booking connection is working")'; then
    ready=1; break
  fi
  sleep 3
done
printf '\nRollback commands (restore the previous settings and images):\n'
printf 'cp %q %q && docker compose --project-directory %q -f %q -f %q up -d --no-deps --no-build app\n' "$booking_backup/app.env" "$booking_dir/.env" "$booking_dir" "$booking_dir/compose.yaml" "$booking_backup/rollback.yaml"
printf 'cp %q %q && docker compose --project-directory %q -f %q -f %q up -d --no-deps --no-build dashboard\n' "$dashboard_backup/app.env" "$dashboard_dir/.env" "$dashboard_dir" "$dashboard_dir/compose.yaml" "$dashboard_backup/rollback.yaml"
if [[ "$ready" != 1 ]]; then
  echo 'Connection check did not pass. The apps are running; use the rollback commands if needed and share this output.'
  exit 1
fi
echo 'Finished. Refresh the dashboard with Ctrl F5. Your real WBM queues and next five weddings should appear.'
