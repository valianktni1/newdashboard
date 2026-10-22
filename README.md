# Weddings By Mark Control Centre

Version 1.2.0 connects the Booking app through a separate read-only summary feed.
See `CONNECT-BOOKING.md` for the two-app update, private key setup, backups and
rollback. Other business connections remain unconfigured.

Version 1.1.0 adds a Today page, saved tasks, business workspaces, the couples'
planner shortcut, light/dark themes and explicit HTTP availability checks.
Business data panels show “Not connected” until real integrations are added.
See `RELEASE-NOTES-V1.1.0.md` and `UPDATE-V1.1.0.md`.

A private, self-hosted launchpad for Mark's business applications and server
services. It is designed for TrueNAS SCALE, Dockge and Nginx Proxy Manager.

## What it does

- Opens every regularly used service from one modern screen.
- Allows every shortcut name, URL, description, category, icon, colour,
  visibility, pin and browser-tab preference to be changed in the interface.
- Adds, deletes and rearranges shortcuts without editing YAML or source code.
- Searches and filters services on desktop, tablet and mobile.
- Exports the current non-sensitive configuration as JSON.
- Records a private activity history ready for future update/task widgets.

The starter tiles are only defaults. Changing or deleting one affects the
shortcut only; it never changes the service, container or data behind it.

## Security

- One private administrator account.
- Passwords are hashed with Argon2 and never stored in plaintext.
- Session identifiers are random and only their SHA-256 hashes are stored.
- Cookies are HttpOnly, Secure and SameSite Strict in production.
- Login attempts are rate-limited.
- A password change revokes every existing session.
- Mutation requests enforce same-origin protection.
- Host headers are restricted to the configured domain and local server.
- The public page tells search engines not to index or archive it.
- The container runs as an unprivileged user with every Linux capability
  dropped, a read-only root filesystem and no-new-privileges enabled.

## Persistent data

Only `/mnt/apps/newdashboard` is mounted into the container. The SQLite database
contains the dashboard settings, shortcuts, administrator password hash,
sessions and activity history. No other Weddings By Mark application dataset is
mounted, read or modified.

## Updating the starter URLs

Open **Edit dashboard**, select any card and change the complete address. The
initial local server ports are editable suggestions based on the existing
Weddings By Mark server. They can be corrected from the screen if a service is
currently on a different address.

## Future-ready foundation

The existing activity data and modular card layout allow later additions such
as the latest three client updates, things to do, service health, payment totals
or backup status without rebuilding the basic control centre.

See `DEPLOY-TRUENAS-DOCKGE.txt` for the exact safe deployment sequence.

## Planner dashboard connection (v1.3.0)

The Today, Weddings By Mark and Ivory Digital pages show a read-only Planner
summary: accounts with current access, invitations awaiting couples, invitation
email problems, access ending within 14 days and the worker heartbeat. Each
queue shows at most five records; open Planner admin to review the full list or
make changes. Counts cover all planner accounts, excluding cancelled invitations.
Current access includes trials and complimentary accounts; it is not a sales count.

Planner v1.3.2 supplies `/api/integrations/control-centre/overview` using a separate
`PLANNER_CONTROL_CENTRE_KEY`, with `PLANNER_CONTROL_CENTRE_ENABLED=true`. Set the
same value as `DASHBOARD_PLANNER_KEY`, with `DASHBOARD_PLANNER_URL` defaulting to
`https://planner.ivorydigital.uk`. Keep the key separate from Booking credentials.
Keys stay on the server. No couple checklists, budgets, guest details, email
addresses, invitation links or private notes are returned.

The local source bundle runs `scripts/install-planner-connection.py --bundle
/path/to/extracted/bundle`. It builds both private repositories from bundled
sources, creates a new independent env file for each integration endpoint, and
compares resolved Compose settings before making changes. Existing env files,
ports, volumes, service commands and Booking credentials remain unchanged.
The release source directories and Compose build contexts persist on the NAS.

Before restarting, the installer backs up the planner, rehearses its full archive
restore without network or live data mounts, and backs up the dashboard database.
It preserves both previous images and Compose files and prints a rollback command.
Only Planner web/worker and Dashboard are recreated. Startup checks require a
healthy worker, both app versions, a successful real Planner feed read from
Dashboard, and an unchanged digest of the existing Booking invitation settings.
A failed check triggers image/configuration rollback while preserving live data.

Validation: 26 dashboard/installer tests; real Flask feed validated against the
dashboard consumer schema; JavaScript syntax checked. Planner regression run:
167 passed, with two Linux filesystem backup tests failing identically in the
unchanged release on Windows (`O_NOFOLLOW` and symlink privileges). The new feed,
Booking invitation and timing tests pass. Docker builds and isolated restore are
performed by the NAS installer; they were not run locally. Automated visual
browser access was unavailable during this change.
