from pathlib import Path
import subprocess
import sys

SCRIPT=Path(__file__).parents[1]/'scripts/connect-booking.py'


def test_pairing_preserves_settings_backs_up_and_keeps_key_private(tmp_path):
    booking=tmp_path/'booking'
    dashboard=tmp_path/'dashboard'
    booking.mkdir();dashboard.mkdir()
    (booking/'.env').write_text('DATABASE_URL=original\nADMIN_PASSWORD=leave-this-alone\n',encoding='utf-8')
    (dashboard/'.env').write_text('DASHBOARD_ADMIN_EMAIL=unchanged@example.com\n',encoding='utf-8')
    command=[sys.executable,str(SCRIPT),'--booking-stack',str(booking),'--dashboard-stack',str(dashboard)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0
    content=(booking/'.env').read_text(encoding='utf-8')
    key=next(line.split('=',1)[1] for line in content.splitlines() if line.startswith('CONTROL_CENTRE_KEY='))
    assert len(key)>=32
    assert key not in result.stdout and key not in result.stderr
    assert 'DATABASE_URL=original' in content and 'ADMIN_PASSWORD=leave-this-alone' in content
    assert 'CONTROL_CENTRE_ENABLED=true' in content
    assert 'DASHBOARD_BOOKING_KEY='+key in (dashboard/'.env').read_text(encoding='utf-8')
    backups=list(booking.glob('deployment-backups/*/app.env'))
    assert len(backups)==1 and 'CONTROL_CENTRE_KEY' not in backups[0].read_text(encoding='utf-8')
    rerun=subprocess.run(command,capture_output=True,text=True)
    assert rerun.returncode==0 and 'CONTROL_CENTRE_KEY='+key in (booking/'.env').read_text(encoding='utf-8')


def test_pairing_refuses_conflicting_existing_keys_without_changes(tmp_path):
    booking=tmp_path/'booking';dashboard=tmp_path/'dashboard'
    booking.mkdir();dashboard.mkdir()
    one='CONTROL_CENTRE_KEY='+'x'*48+'\n'
    two='DASHBOARD_BOOKING_KEY='+'y'*48+'\n'
    (booking/'.env').write_text(one,encoding='utf-8')
    (dashboard/'.env').write_text(two,encoding='utf-8')
    result=subprocess.run([sys.executable,str(SCRIPT),'--booking-stack',str(booking),'--dashboard-stack',str(dashboard)],capture_output=True,text=True)
    assert result.returncode!=0
    assert (booking/'.env').read_text(encoding='utf-8')==one
    assert (dashboard/'.env').read_text(encoding='utf-8')==two
