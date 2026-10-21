# Daily workspace — version 1.1.0

The home screen now starts with personal priorities and favourite apps. Dedicated
workspaces organise Weddings By Mark, Ivory Digital, Marketing, Accounts and
Systems, with All apps retaining the complete editable shortcut collection.

- Tasks are stored in SQLite with due dates, priority, workspace, optional related
  page, editing, completion, reopening and deletion. Export includes tasks.
- Search finds apps and personal tasks. Ctrl/Cmd K opens global search.
- A couples' planner shortcut is added once during upgrade. Existing shortcuts,
  names, colours, categories, visibility, favourites, order and settings survive.
  Each shortcut has an editable workspace separate from its original category.
- Systems offers manual HTTP availability checks, timestamps and stale-result
  labels. Redirects and restricted pages are identified separately. A response is
  not proof of service health or successful backups. Checks are cached for one
  minute, use four workers, send no login cookies and do not follow redirects.
- Only exact starter addresses plus optional DASHBOARD_CHECK_URLS addresses are
  checked. New or edited addresses outside this allowlist remain unchecked.
- Light and dark themes, compact app cards, readable text, mobile navigation,
  keyboard focus management and recent dashboard activity.
- Database connections now close at the end of each operation.

## Business connections

Booking, accounts, planner, diary, outreach and marketing panels explicitly show
**Not connected** and **Live figures unavailable**. They provide app shortcuts,
not live totals. No external business data is imported in this release. Personal
tasks are not synchronised with other apps. This dashboard does not grant access
to couples' private planner content or replace the apps' own sign-ins.

## Upgrade and rollback

Back up the existing SQLite database before deploying. The upgrade adds a
workspace column and task/check tables, and records the planner migration once.
It does not mount or modify another application's dataset. Use the existing
Dockge stack, port 30046, .env and /mnt/apps/newdashboard data mount.

For a safe rollback, stop the dashboard, restore the saved pre-upgrade database
and deploy the previous image. Preserve any tasks created after the upgrade by
exporting first. See UPDATE-V1.1.0.md for deployment steps.

Validation: automated authentication, shortcut editing, export, task lifecycle,
old-database migration, approved-target checks, caching and redirect tests.
