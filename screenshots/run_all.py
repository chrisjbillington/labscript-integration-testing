"""Take screenshots of the four suite applications for each Qt binding, style and colour
scheme, by running shoot.py once per combination.

    python run_all.py --data SCREENSHOTS.json --out DIR --venv PySide6=PATH --venv PyQt6=PATH ...

SCREENSHOTS.json is the file that prepare.py writes. Each venv is a harness venv with
the named binding installed. Images are written to
DIR/<app>-<binding>-<style>-<scheme>.png, each with a JSON file beside it.

With --offscreen the applications use Qt's offscreen platform with a 1920 by 1080
screen, and no windows are shown. The offscreen platform has no platform theme, so the
default font is Qt's fallback font, and it has no colour scheme, so only light images
are taken."""

import argparse
import concurrent.futures
import itertools
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPS = ['blacs', 'runmanager', 'lyse', 'runviewer']
STYLES = ['default', 'fusion']
SCHEMES = ['light', 'dark']
TIMEOUT = 240

parser = argparse.ArgumentParser()
parser.add_argument('--data', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--venv', action='append', required=True, metavar='BINDING=PATH')
parser.add_argument('--app', action='append', choices=APPS)
parser.add_argument('--style', action='append', choices=STYLES)
parser.add_argument('--scheme', action='append', choices=SCHEMES)
parser.add_argument('--offscreen', action='store_true')
args = parser.parse_args()
if args.offscreen and 'dark' in (args.scheme or []):
    parser.error('the offscreen platform has no dark colour scheme')
schemes = args.scheme or (['light'] if args.offscreen else SCHEMES)

out = Path(args.out).resolve()
out.mkdir(parents=True, exist_ok=True)
(out / 'activation.lock').unlink(missing_ok=True)
data_file = Path(args.data).resolve()


def python(venv):
    if sys.platform == 'win32':
        return str(Path(venv) / 'Scripts' / 'python.exe')
    return str(Path(venv) / 'bin' / 'python')


def kill_tree(proc):
    """Kill the process and its children, and return once they have exited, so that the
    application's server port is free for the next one."""
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
        proc.wait()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
    t0 = time.monotonic()
    while group_running(proc.pid) and time.monotonic() - t0 < 10:
        time.sleep(0.02)


def group_running(pgid):
    """Whether a process of the process group is running. A process that has exited but
    has not been reaped by its parent does not count."""
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
        except (OSError, IndexError):
            continue
        state, pgrp = fields[0], int(fields[2])
        if pgrp == pgid and state != 'Z':
            return True
    return False


def shoot(app, binding, venv, style, scheme):
    name = f'{app}-{binding}-{style}-{scheme}'
    image = out / f'{name}.png'
    info = image.with_suffix('.json')
    info.unlink(missing_ok=True)
    log = open(out / f'{name}.log', 'w', encoding='utf8', errors='replace')
    cmd = [
        python(venv), '-X', 'utf8', str(HERE / 'shoot.py'), app, '--style', style,
        '--scheme', scheme, '--data', str(data_file), '--out', str(image),
    ]
    env = dict(os.environ, QT_ENV=binding, LABSCRIPT_DISABLE_GRAPHICAL_EXCEPTHOOK='1',
               PYTHONPATH=str(HERE / 'fixture'))
    if args.offscreen:
        env['QT_QPA_PLATFORM'] = f"offscreen:configfile={HERE / 'offscreen.json'}"
    if sys.platform == 'win32':
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    t0 = time.monotonic()
    while not info.exists() and proc.poll() is None and time.monotonic() - t0 < TIMEOUT:
        time.sleep(0.05)
    if info.exists():
        print(f'{name}: {json.loads(info.read_text())}', flush=True)
    elif proc.poll() is not None:
        print(f'{name}: exited with code {proc.returncode}, see {name}.log', flush=True)
    else:
        print(f'{name}: no image after {TIMEOUT} s, see {name}.log', flush=True)
    kill_tree(proc)
    log.close()


def shoot_all(app):
    for (binding, venv), style, scheme in itertools.product(
        venvs.items(), args.style or STYLES, schemes
    ):
        if binding == 'PyQt5' and scheme == 'dark' and sys.platform != 'win32':
            # Qt 5 has no colour scheme API, and its dark palette option is Windows-only.
            continue
        shoot(app, binding, venv, style, scheme)


venvs = dict(v.split('=', 1) for v in args.venv)
# The applications use different server ports, so the images of different applications
# are taken at the same time, and those of one application one after another.
with concurrent.futures.ThreadPoolExecutor() as executor:
    for future in [executor.submit(shoot_all, app) for app in args.app or APPS]:
        future.result()
