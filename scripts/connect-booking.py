#!/usr/bin/env python3
"""Run on TrueNAS to pair the existing stacks without displaying credentials."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile


def value(text, key):
    found=re.search(r'^'+re.escape(key)+r'=(.*)$',text,re.M)
    return found.group(1).strip().strip('"\'') if found else ''


def update(path, original, changes):
    text=original
    for key,val in changes.items():
        pattern=r'^'+re.escape(key)+r'=.*$'
        line=key+'='+val
        text=re.sub(pattern,lambda match:line,text,flags=re.M) if re.search(pattern,text,re.M) else text.rstrip()+'\n'+line+'\n'
    descriptor,name=tempfile.mkstemp(prefix='.env-control-centre-',dir=path.parent)
    try:
        os.fchmod(descriptor,0o600) if hasattr(os,'fchmod') else None
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as handle:handle.write(text)
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--booking-stack',default='/mnt/apps/dockge/data/bookingsystem2026')
    parser.add_argument('--dashboard-stack',default='/mnt/apps/dockge/data/newdashboard')
    args=parser.parse_args()
    booking=(Path(args.booking_stack)/'.env').resolve()
    dashboard=(Path(args.dashboard_stack)/'.env').resolve()
    if booking==dashboard or not booking.is_file() or not dashboard.is_file():
        raise SystemExit('STOP: both existing stack .env files must exist and be different. No changes made.')
    originals={path:path.read_text(encoding='utf-8') for path in (booking,dashboard)}
    old_b=value(originals[booking],'CONTROL_CENTRE_KEY')
    old_d=value(originals[dashboard],'DASHBOARD_BOOKING_KEY')
    if old_b and old_d and old_b!=old_d:
        raise SystemExit('STOP: the stacks already contain different connection keys. No changes made.')
    token=old_b or old_d
    if len(token)<32:token=secrets.token_urlsafe(48)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',token):
        raise SystemExit('STOP: existing key has an unsupported format. No changes made.')
    suffix=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for path in originals:
        backup=path.parent/'deployment-backups'/('control-centre-'+suffix)
        backup.mkdir(parents=True,mode=0o700)
        shutil.copy2(path,backup/'app.env')
        (backup/'app.env').chmod(0o600)
    try:
        update(booking,originals[booking],{'CONTROL_CENTRE_ENABLED':'true','CONTROL_CENTRE_KEY':token})
        update(dashboard,originals[dashboard],{'DASHBOARD_BOOKING_KEY':token,'DASHBOARD_BOOKING_URL':'https://booking.weddingsbymark.uk'})
    except Exception:
        for path,original in originals.items():update(path,original,{})
        raise
    print('Booking connection configured. Both previous .env files were backed up. No key was printed.')
    print('Rebuild/recreate the booking app and dashboard using the update guide.')


if __name__=='__main__':main()
