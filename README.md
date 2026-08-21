# Weddings By Mark Control Centre

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
