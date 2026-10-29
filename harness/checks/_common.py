"""Shared helpers for the check scripts. Each script runs in the harness venv with the
working directory set to the work directory."""

import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

WORK = Path(os.environ['HARNESS_WORK'])
REPOS = Path(os.environ['HARNESS_REPOS'])
FIXTURES = Path(os.environ['HARNESS_FIXTURES'])
SHOTS = WORK / 'shots'
STATE = WORK / 'state.json'

# Written into a profile directory that the harness created, so that a later run may
# delete it. A profile without this file is never touched.
PROFILE_MARKER = '.created-by-labscript-test-harness'

_failures = 0


def check(cond, msg, known=None):
    """Record a check. `known` names an open bug that makes the check fail; the failure
    is then reported as KNOWN and not counted, and a pass is reported as FIXED so that the
    marker can be removed."""
    global _failures
    if known is not None:
        print(('FIXED ' if cond else 'KNOWN ') + msg + f' [{known}]', flush=True)
        return bool(cond)
    print(('PASS ' if cond else 'FAIL ') + msg, flush=True)
    if not cond:
        _failures += 1
    return bool(cond)


def fail(msg):
    return check(False, msg)


def attempt(msg, func, *args, **kwargs):
    """Run func and record PASS or FAIL with the exception text."""
    try:
        result = func(*args, **kwargs)
    except Exception:
        check(False, f'{msg}: {traceback.format_exc().strip().splitlines()[-1]}')
        traceback.print_exc()
        return None, False
    check(True, msg)
    return result, True


def finish():
    print(f'\n{_failures} failure(s)', flush=True)
    sys.exit(1 if _failures else 0)


def sphinx_configuration(repo):
    """The path of conf.py, relative to the repository, in the Read the Docs configuration of
    the repository, or None."""
    for name in ['readthedocs.yaml', '.readthedocs.yaml', 'readthedocs.yml', '.readthedocs.yml']:
        path = repo / name
        if path.exists():
            match = re.search(r'^\s*configuration:\s*(\S+)', path.read_text(), re.MULTILINE)
            if match:
                return match.group(1)
    return None


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {}


def save_state(**kwargs):
    state = load_state()
    state.update(kwargs)
    STATE.write_text(json.dumps(state, indent=1))


def profile_dir():
    from labscript_profile import LABSCRIPT_SUITE_PROFILE
    return Path(LABSCRIPT_SUITE_PROFILE)


def labconfig():
    from labscript_utils.labconfig import LabConfig
    return LabConfig()


def port(name):
    return int(labconfig().get('ports', name))


APP_STARTUP_TIMEOUT = 120


def listening(p):
    try:
        with socket.create_connection(('127.0.0.1', p), timeout=1):
            return True
    except OSError:
        return False


def start_app(app, name=None):
    """Start a suite application with its output in logs/app-<name>.log, where name
    defaults to the application name. Return the process and the open log file."""
    log = open(WORK / 'logs' / f'app-{name or app}.log', 'w', encoding='utf8', errors='replace')
    proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', app], stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def stop_app(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def app_output(app):
    return (WORK / 'logs' / f'app-{app}.log').read_text(encoding='utf8', errors='replace')


def wait_for_port(proc, p):
    """Wait for the process to listen on port p. Return whether it does, and the time
    taken."""
    t0 = time.time()
    while time.time() - t0 < APP_STARTUP_TIMEOUT:
        if proc.poll() is not None:
            return False, time.time() - t0
        if listening(p):
            return True, time.time() - t0
        time.sleep(0.5)
    return False, time.time() - t0


def wait_for_port_release(p):
    """Give a port time to be released before an application uses it again."""
    for _ in range(20):
        if not listening(p):
            break
        time.sleep(0.5)
