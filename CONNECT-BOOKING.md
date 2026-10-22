# Connect Booking to the dashboard — version 1.2.0

This release needs **both** the BookingSystem2026 read-only feed and the dashboard
consumer. Existing app accounts, sign-ins, booking workflow and payments remain
in their original applications. No new database mount or shared admin session is
used. This is a server-to-server connection, not a ChatGPT connector.

## What appears

- WBM enquiries to review and quotes awaiting a decision.
- Overdue invoices and invoices due within 60 days.
- Accepted quotes awaiting their first payment.
- Booking forms and agreements outstanding, using Booking's existing rules.
- Next five confirmed or in-progress WBM weddings, including date and venue.
- Direct links to each booking's Journey, Payments or Overview page.

Test, archived and cancelled bookings, Ivory Digital projects and private contact
details, notes, form answers and documents are excluded. Queue counts include the
full matching list; only five examples are returned per queue. Figures are GBP.
Invoice amounts mean the **full outstanding invoice balance**, which can include
future instalments. They are not a statement of the instalment amount due today.

The key grants access to this summary endpoint only. It cannot change a booking,
record a payment, send a message or sign into either application. Keys are stored
in the two server `.env` files, never in browser code, exports or application logs.
The booking feed is disabled until explicitly configured. HTTPS is used for the
public booking origin; redirects are not followed when sending the key.

## Install on the existing TrueNAS stacks

### Private booking repository

Docker cannot fetch a private GitHub build context without credentials. A failed
build at step 2 leaves the old apps running and does not pair or change their
settings. Do not make the repository public just to run the installer.

Use a source bundle containing the exact tested `bookingsystem2026` and
`newdashboard` source trees and an `install.sh` wrapper. Copy it to the NAS,
extract it into a new temporary directory and run its wrapper. The wrapper sets
`WBM_BOOKING_SOURCE`, `WBM_DASHBOARD_SOURCE` and `WBM_CONNECT_HELPER` to the bundled
files. Temporary Compose overrides select these local build contexts for the
build, image verification and startup. The live Compose files are preserved,
and startup uses `--no-build` so it cannot retry the private GitHub fetch.

The source package contains application code only, with no `.env`, database,
runtime storage or Git credentials. Keep the package on your private NAS share.
Public base images and Python dependencies still need normal internet access.
Future source updates need a new bundle or properly configured GitHub build
authentication; this does not change the repository's visibility or grant it
public access.

### Existing authenticated GitHub builds

After both repository updates are merged, run in the TrueNAS root shell:

```bash
curl -fL https://raw.githubusercontent.com/valianktni1/newdashboard/main/scripts/upgrade-booking-connection.sh -o /tmp/wbm-booking-connection.sh && bash /tmp/wbm-booking-connection.sh
```

The script expects the existing stack directories:

- `/mnt/apps/dockge/data/bookingsystem2026` (services `app` and `database`).
- `/mnt/apps/dockge/data/newdashboard` (service `dashboard`).

It verifies the current build sources, backs up PostgreSQL and the dashboard's
SQLite database, saves both `.env` files and retains rollback images. It builds
both apps while the old ones keep running, checks the new routes, generates or
reuses one private shared key, starts both updated containers and checks the
connection. It does not recreate the booking database service. Existing GitHub
build access is required. No API key needs to be pasted into this chat.

The printed backup files include private settings: keep them private and save a
copy of the database backups separately from the NAS. Rollback commands are
printed at the end. No booking database migration is added by this feature.

## Manual configuration / different stack locations

Set `WBM_BOOKING_STACK` and `WBM_DASHBOARD_STACK` before running the shell script
if the current directories differ. The script stops if either stack is missing
or uses a local build checkout; do not guess a new directory or create a new stack.

Alternatively use `scripts/connect-booking.py` on the NAS with `--booking-stack`
and `--dashboard-stack`, then rebuild/recreate both existing app services yourself.
The helper backs up and updates only the `.env` files. It is not a database backup
or an application update by itself.

Environment variables:

- Booking: `CONTROL_CENTRE_ENABLED=true`, `CONTROL_CENTRE_KEY=<random private key>`.
- Dashboard: `DASHBOARD_BOOKING_KEY=<same key>`,
  `DASHBOARD_BOOKING_URL=https://booking.weddingsbymark.uk`.

Recreate the apps after environment changes. To disable access, set
`CONTROL_CENTRE_ENABLED=false` in Booking and recreate its app service. Use a new
random key in both apps to revoke an old key. Do not reuse an admin password.

## Freshness and failure behaviour

The browser checks once a minute while visible. The server caches attempts for
60 seconds; manual refresh has a 15-second minimum interval. Requests have a
five-second network timeout and response size/schema validation. A failed refresh
keeps the last successful summary in server memory and labels it as saved/stale.
Information more than five minutes old is also marked stale. A server restart
clears that memory. Missing configuration or a failed first request shows no
figures, rather than invented zeros. A proxy access screen or login redirect
cannot be used as the feed; the server must be able to reach the JSON endpoint.

## Validation

11 dashboard tests and 3 feed tests, including secret handling, read-only scope,
real WBM filtering, bounded lists, GBP amounts, the UK date boundary, cached
refresh, invalid schema/links and setup backup/reuse behaviour. Local end-to-end
browser checks use synthetic example bookings, not the live database.
Five existing booking behaviour tests passed. Two older asset-version assertions
fail identically on unchanged main; their expected cache string is outdated.
