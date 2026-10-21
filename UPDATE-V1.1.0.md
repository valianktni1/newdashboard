# Update the existing TrueNAS dashboard

Use the existing **newdashboard** Dockge stack. Keep its current `.env`, port and
data mount. Do not create a new stack or replace your database.

Run in the TrueNAS root shell after this release has been merged into `main`:

```bash
cd /mnt/apps/dockge/data/newdashboard
docker exec newdashboard python -c 'import sqlite3,datetime; from pathlib import Path; p=Path("/data")/("control-centre-before-v110-"+datetime.datetime.now().strftime("%Y%m%d-%H%M%S")+".db"); source=sqlite3.connect("/data/control-centre.db"); target=sqlite3.connect(p); source.backup(target); target.close(); source.close(); print("Backup saved:",p)'
```

Wait for the backup confirmation. Download that backup from
`/mnt/apps/newdashboard/` to somewhere separate from the NAS.

Then run:

```bash
cd /mnt/apps/dockge/data/newdashboard
docker compose -f compose.yaml build --no-cache dashboard && docker compose -f compose.yaml up -d dashboard
curl --fail --silent --show-error http://127.0.0.1:30046/api/health
```

The health response should show version `1.1.0`. Allow a few seconds for startup
if the first check fails, then check again. Refresh your dashboard with Ctrl F5.
Your existing account, shortcuts and settings should still be present. Visit
**Systems → Check services** to run the first checks from the NAS.

Do not use the rebuild command while the release only exists in a review branch:
the existing Compose file builds the GitHub `main` branch.

## Additional availability checks

Starter URLs are permitted automatically. To check an additional app, add its
exact URL to a JSON list in the existing `.env`, for example:

```dotenv
DASHBOARD_CHECK_URLS=["https://your-app.example/api/health"]
```

Recreate the container after changing `.env`. Do not put passwords or API keys in
these addresses. A changed shortcut will not inherit an old address's result.

## Rollback

Keep the previous image until you have checked the update. If rollback is needed,
export any new tasks, stop the container, restore the saved database (and remove
the stopped database's `-wal` and `-shm` companions if present), then start the
previous image. Restoring the older database loses changes made after its backup.
