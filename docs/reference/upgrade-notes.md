# Upgrade notes

## What happens when you upgrade

1. **Back up first.** The update script backs the database up to `runtime/data/backups/` before it pulls
   the new version. For more, use Settings › The app › Your data › **Export everything**.
2. **Update**: stop KOLONİ, then run `./scripts/update.ps1` (Windows) or `./scripts/update.sh`. See
   [Backup and update](../backup-and-update.md).
3. **Start KOLONİ again.** If the new version changes the database, KOLONİ copies it to
   `runtime/data/backups/` and then upgrades it. It keeps the last five copies there, the update
   script's included.

If something goes wrong, the copies in `runtime/data/backups/` are whole databases. Stop KOLONİ before you
put one back in place of `runtime/data/koloni.db`.

## Version by version

No version has been released yet. Changes that need your attention will be listed here, and in the
[Changelog](../changelog.md).
