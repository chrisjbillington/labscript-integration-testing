"""Create a labscript profile with `labscript-profile-create`, point its shared drive at
the work directory, add a FunctionRunner to its example connection table and experiment
and add the runmanager test fixtures to its labscriptlib."""

import configparser
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from _common import FIXTURES, PROFILE_MARKER, WORK, check, fail, finish, profile_dir, save_state

profile = profile_dir()
print('profile directory:', profile)

from labscript_profile import default_labconfig_path
from labscript_profile.create import create_profile


def stop_servers():
    """Stop the zlock and zlog servers that were started with the profile's labconfig,
    which are the processes with a command line that runs zprocess.zlock or zprocess.zlog
    and names a file in the profile. Windows only."""
    query = ("Get-CimInstance Win32_Process | Where-Object CommandLine -like '*zprocess.zl*' "
             "| Select-Object ProcessId, CommandLine | ConvertTo-Json")
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', query],
                            capture_output=True, text=True, errors='replace', timeout=120)
    processes = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(processes, dict):
        processes = [processes]
    prefix = os.path.normcase(str(profile) + os.sep)
    for process in processes:
        command = process['CommandLine']
        normalised = os.path.normcase(command)
        if prefix in normalised and ('zprocess.zlock' in normalised or 'zprocess.zlog' in normalised):
            print(f'stopping process {process["ProcessId"]}: {command}')
            try:
                os.kill(process['ProcessId'], signal.SIGTERM)
            except OSError as e:
                print(f'could not stop process {process["ProcessId"]}: {e}')


# On Windows the zlock and zlog servers that a previous run started hold their log files
# in the profile open, so they are stopped. A server that is left running keeps that run's
# shared secret, so the secret is carried over to the new profile.
old_secret = None
if profile.exists():
    if (profile / PROFILE_MARKER).exists():
        print('removing the profile left by a previous harness run')
        keys = list((profile / 'labconfig').glob('zpsecret-*.key'))
        if keys:
            old_secret = keys[0].read_text()
        if os.name == 'nt':
            stop_servers()
        # The files of a stopped process can stay open for a short time:
        deadline = time.monotonic() + 10
        shutil.rmtree(profile, ignore_errors=True)
        while profile.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
            shutil.rmtree(profile, ignore_errors=True)
        if profile.exists():
            left = [str(p) for p in profile.rglob('*') if p.is_file()]
            fail(f'could not remove the old profile; files still present: {left}')
            finish()
    else:
        fail(f'{profile} exists and was not created by the harness; move it away first')
        finish()

create_profile()
(profile / PROFILE_MARKER).write_text('')
check(default_labconfig_path().exists(), f'labconfig written to {default_labconfig_path()}')
if old_secret is not None:
    for key in (profile / 'labconfig').glob('zpsecret-*.key'):
        key.write_text(old_secret)
    print('kept the shared secret of the previous profile')

# Shots and the compiled connection table go under the work directory.
shared_drive = WORK / 'shared_drive'
shared_drive.mkdir(parents=True, exist_ok=True)
config = configparser.ConfigParser(interpolation=None)
config.read(default_labconfig_path())
config.set('DEFAULT', 'shared_drive', str(shared_drive))
with open(default_labconfig_path(), 'w') as f:
    config.write(f)

from labscript_utils.labconfig import LabConfig

labconfig = LabConfig()
storage = labconfig.get('DEFAULT', 'experiment_shot_storage')
check(storage.startswith(str(shared_drive)), f'experiment_shot_storage is {storage}')
check(labconfig.get('paths', 'connection_table_py').endswith('connection_table.py'),
      'labconfig names the example connection table')

# The FunctionRunner fixtures go after the device definitions of the example connection
# table and experiment.
example_dir = Path(os.path.expandvars(labconfig.get('paths', 'connection_table_py'))).parent
for name, fixture, marker in [
    ('connection_table.py', 'connection_table_addition.py', "\n\nif __name__ == '__main__':"),
    ('example_experiment.py', 'example_experiment_addition.py', '\n# Begin issuing labscript primitives'),
]:
    path = example_dir / name
    text = path.read_text()
    found = text.count(marker) == 1
    check(found, f'{name} has one {marker.strip()!r} line, before which the FunctionRunner goes')
    if found:
        addition = (FIXTURES / 'function_runner' / fixture).read_text()
        path.write_text(text.replace(marker, '\n' + addition + marker))

fixtures = FIXTURES / 'runmanager_test'
dest = profile / 'userlib' / 'labscriptlib' / 'runmanager_test'
shutil.copytree(fixtures, dest)
check((dest / 'experiment.py').exists(), f'runmanager test fixtures copied to {dest}')

save_state(profile=str(profile), labconfig=str(default_labconfig_path()))
finish()
