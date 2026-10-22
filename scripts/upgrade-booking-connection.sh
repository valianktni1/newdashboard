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
# Do not silently rebuild an old local source checkout or a different application.
"${booking[@]}" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); b=c["services"]["app"]["build"]; u=b["context"] if isinstance(b,dict) else b; assert u in ("https://github.com/valianktni1/bookingsystem2026.git","https://github.com/valianktni1/bookingsystem2026.git#main"), "Booking build must use the existing GitHub main source"'
"${dashboard[@]}" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); b=c["services"]["dashboard"]["build"]; u=b["context"] if isinstance(b,dict) else b; assert u in ("https://github.com/valianktni1/newdashboard.git","https://github.com/valianktni1/newdashboard.git#main"), "Dashboard build must use the existing GitHub main source"'
# An uploaded source bundle avoids unauthenticated GitHub fetches for private repos.
# The live Compose files stay unchanged. Only this invocation overrides build context.
booking_build=("${booking[@]}")
dashboard_build=("${dashboard[@]}")
temporary_files=()
cleanup() { for file in "${temporary_files[@]}"; do rm -f "$file"; done; }
trap cleanup EXIT
if [[ -n "${WBM_BOOKING_SOURCE:-}" || -n "${WBM_DASHBOARD_SOURCE:-}" ]]; then
  [[ -n "${WBM_BOOKING_SOURCE:-}" && -n "${WBM_DASHBOARD_SOURCE:-}" ]] || {
    echo 'STOP: both local source directories must be supplied. No apps changed.'; exit 1;
  }
  for source in "${WBM_BOOKING_SOURCE:-}" "${WBM_DASHBOARD_SOURCE:-}"; do
    test -f "$source/Dockerfile" && test -f "$source/app/main.py" || {
      echo 'STOP: both source directories must contain Dockerfile and app/main.py. No apps changed.'; exit 1;
    }
  done
  booking_override=$(mktemp "$booking_dir/compose.private-source.XXXXXX.yaml")
  dashboard_override=$(mktemp "$dashboard_dir/compose.private-source.XXXXXX.yaml")
  temporary_files+=("$booking_override" "$dashboard_override")
  python3 - "$booking_override" "$WBM_BOOKING_SOURCE" "$dashboard_override" "$WBM_DASHBOARD_SOURCE" <<'PY'
import json,sys
from pathlib import Path
for destination,source,service in ((sys.argv[1],sys.argv[2],'app'),(sys.argv[3],sys.argv[4],'dashboard')):
    # JSON is valid YAML and quotes paths without interpolation into shell code.
    Path(destination).write_text(json.dumps({'services':{service:{'build':{'context':str(Path(source).resolve())}}}}))
PY
  booking_build+=( -f "$booking_override" )
  dashboard_build+=( -f "$dashboard_override" )
  echo 'Using the uploaded private source bundle. No GitHub login is needed for these builds.'
fi
helper="${WBM_CONNECT_HELPER:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/connect-booking.py}"
if [[ ! -f "$helper" ]]; then
  command -v curl >/dev/null
  helper=$(mktemp /tmp/wbm-connect-booking.XXXXXX.py)
  temporary_files+=("$helper")
  curl -fL https://raw.githubusercontent.com/valianktni1/newdashboard/main/scripts/connect-booking.py -o "$helper"
fi
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
"${booking_build[@]}" build --no-cache app
"${dashboard_build[@]}" build --no-cache dashboard
echo '3/6 Checking that the new images contain both sides of the connection...'
"${booking_build[@]}" run --rm --no-deps --entrypoint python app -c 'from app.main import app; assert any(r.path=="/api/integrations/control-centre/overview" for r in app.routes); print("Booking feed present")'
"${dashboard_build[@]}" run --rm --no-deps --entrypoint python dashboard -c 'from app.main import app; assert any(r.path=="/api/booking/overview" for r in app.routes); print("Dashboard connection present")'
echo '4/6 Configuring a private shared key without displaying it...'
python3 "$helper" --booking-stack "$booking_dir" --dashboard-stack "$dashboard_dir"
# Hand-written Dockge stacks may omit env_file. Wire only these two new settings
# into the dashboard service, preserving all other resolved Compose settings.
repair_helper="$(dirname -- "$helper")/repair-dashboard-connection.py"
if [[ ! -f "$repair_helper" ]]; then
  repair_helper=$(mktemp /tmp/wbm-dashboard-key-loading.XXXXXX.py)
  temporary_files+=("$repair_helper")
  curl -fL https://raw.githubusercontent.com/valianktni1/newdashboard/main/scripts/repair-dashboard-connection.py -o "$repair_helper"
fi
python3 "$repair_helper" --stack "$dashboard_dir" --configure-only
echo '5/6 Starting both updated apps...'
"${booking_build[@]}" up -d --no-deps --no-build app
"${dashboard_build[@]}" up -d --no-deps --no-build dashboard
echo '6/6 Checking the live read-only connection...'
ready=0
for attempt in {1..20}; do
  if "${dashboard[@]}" exec -T dashboard python -c 'import json,urllib.request; h=json.load(urllib.request.urlopen("http://127.0.0.1:8080/api/health",timeout=4)); assert h["status"]=="ok"; from app.booking_connection import booking_snapshot; s=booking_snapshot(); assert s["status"]=="connected",s["message"]; print("Dashboard is responding and the read-only booking connection is working")'; then
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
