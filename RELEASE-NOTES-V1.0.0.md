# Weddings By Mark Control Centre V1.0.0

## Included

- A polished, private starting page for Mark's business and server services.
- Twelve editable starter shortcuts covering the Booking System, Accounts,
  Client Galleries, Studio Ninja, Google Calendar, Weddings By Mark website,
  Nginx Proxy Manager, Dockge, TrueNAS, Ivory Digital, Outreach and StudioApp.
- Search, category filters, pinned shortcuts and responsive mobile navigation.
- An editing mode for adding, changing, hiding, deleting and rearranging tiles.
- Editable shortcut icons or initials and individual accent colours.
- Editable dashboard title, welcome text and greeting name.
- Secure single-administrator login, Argon2 password hashing, rate limiting,
  HttpOnly SameSite cookies, session expiry and password-change session revocation.
- Configuration export and an activity history API ready for a future
  “last three updates” panel.

## Deployment

- Dockge stack/project name: `newdashboard`
- Public address: `https://dashboard.weddingsbymark.uk`
- TrueNAS port: `30046`
- Persistent dataset: `/mnt/apps/newdashboard`
- No existing booking, account, gallery or server dataset is mounted or changed.
