"""Start each application under the offscreen Qt platform, wait for its ZMQ server port
to accept connections, and exercise the runmanager remote API. Time
`zprocess.port_in_use` on the port and on a free port. Start a second copy
of the application, check that it reports the port in use, and for BLACS that it does so
before it creates device tabs. Stop both copies."""

import os
import socket
import time

from _common import (APP_STARTUP_TIMEOUT, WORK, app_output, attempt, check, finish, listening,
                     load_state, port, profile_dir, start_app, stop_app, wait_for_port,
                     wait_for_port_release)

try:
    from zprocess import port_in_use
except ImportError:
    port_in_use = None

state = load_state()
HOLD = 5
PROBES = 20
BLACS_LOG = profile_dir() / 'logs' / 'BLACS.log'

# Each app with the labconfig port that it serves.
APPS = [
    ('runmanager', 'runmanager'),
    ('runviewer', 'runviewer'),
    ('lyse', 'lyse'),
    ('blacs', 'BLACS'),
]

# The pull request with which each app reports that its port is in use.
PORT_IN_USE_FIX = {
    'runmanager': 'runmanager #146',
    'runviewer': 'runviewer #80',
    'lyse': 'lyse #159',
    'blacs': 'blacs #138',
}


def runmanager_remote():
    from runmanager.remote import Client
    client = Client(host='localhost', port=port('runmanager'), timeout=30)
    for _ in range(60):
        try:
            client.say_hello()
            break
        except Exception:
            time.sleep(1)
    check(client.say_hello() == 'hello', 'runmanager remote say_hello')
    version = client.get_version()
    check(isinstance(version, str) and version, f'runmanager remote get_version {version}')
    client.set_labscript_file(state['example_script'])
    check(client.get_labscript_file() == state['example_script'] or
          os.path.normcase(client.get_labscript_file()) == os.path.normcase(state['example_script']),
          f'set_labscript_file and get_labscript_file: {client.get_labscript_file()}')
    check(client.error_in_globals() is False, 'error_in_globals is False with no globals')
    n = client.n_shots()
    check(n is None or isinstance(n, int), f'n_shots returns {n!r} with no globals file loaded')
    check(client.get_shuffle() is False, 'get_shuffle')
    client.set_shuffle(True)
    check(client.get_shuffle() is True, 'set_shuffle')
    client.set_shuffle(False)
    check(client.is_output_folder_default() is True, 'is_output_folder_default')
    folder = client.get_shot_output_folder()
    check(isinstance(folder, str) and folder, f'get_shot_output_folder {folder}')
    custom = str(WORK / 'custom_out')
    client.set_shot_output_folder(custom)
    check(client.is_output_folder_default() is False, 'set_shot_output_folder')
    client.reset_shot_output_folder()
    check(client.is_output_folder_default() is True, 'reset_shot_output_folder')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def time_port_in_use(p, in_use, description):
    results = []
    for _ in range(PROBES):
        t0 = time.perf_counter()
        results.append((port_in_use(p), 1e3 * (time.perf_counter() - t0)))
    correct = sum(r == in_use for r, _ in results)
    times = sorted(t for _, t in results)
    check(correct == PROBES,
          f'{correct} of {PROBES} calls of port_in_use on {description} returned {in_use}; '
          f'median {times[PROBES // 2]:.2f} ms, maximum {times[-1]:.2f} ms')


def blacs_log():
    if not BLACS_LOG.exists():
        return ''
    return BLACS_LOG.read_text(encoding='utf8', errors='replace')


def check_second_copy(app):
    """Start a second copy of the app and check that it reports its port in use. Return
    whether it did."""
    name = f'{app}-second'
    message = 'Another copy of %s is probably running' % ('BLACS' if app == 'blacs' else app)
    blacs_log_start = len(blacs_log())
    proc, log = start_app(app, name)
    try:
        t0 = time.time()
        while time.time() - t0 < APP_STARTUP_TIMEOUT:
            if message in app_output(name) or proc.poll() is not None:
                break
            time.sleep(0.5)
        seconds = time.time() - t0
    finally:
        stop_app(proc)
        log.close()
    reported = message in app_output(name)
    check(reported, f'a second {app} reported that the port is in use after {seconds:.0f} s',
          known=None if reported else PORT_IN_USE_FIX[app])
    if app == 'blacs':
        check('Instantiating devices' not in blacs_log()[blacs_log_start:],
              'the second BLACS did not create device tabs')
    tracebacks = app_output(name).count('Traceback (most recent call last)')
    check(tracebacks == 0, f'no traceback in the {name} output ({tracebacks} found)',
          known=None if reported else PORT_IN_USE_FIX[app])
    return reported


if port_in_use is None:
    print('zprocess has no port_in_use; it is not timed')
else:
    time_port_in_use(free_port(), False, 'a free port')

for app, port_name in APPS:
    p = port(port_name)
    print(f'\n--- {app} on port {p}')
    if listening(p):
        check(False, f'port {p} is already in use before starting {app}')
        continue
    proc, log = start_app(app)
    try:
        up, seconds = wait_for_port(proc, p)
        check(up, f'{app} started and is listening on port {p} after {seconds:.0f} s')
        if up:
            if app == 'runmanager':
                attempt('runmanager remote API', runmanager_remote)
            time.sleep(HOLD)
            check(proc.poll() is None, f'{app} still running {HOLD} s after start')
            if port_in_use is not None:
                time_port_in_use(p, True, f'the {app} port')
            check_second_copy(app)
    finally:
        stop_app(proc)
        log.close()
    output = app_output(app)
    tracebacks = output.count('Traceback (most recent call last)')
    check(tracebacks == 0, f'no traceback in the {app} output ({tracebacks} found)')
    tail = output.strip().splitlines()[-15:]
    if tail:
        print(f'last lines of {app} output:')
        print('    ' + '\n    '.join(tail))
    wait_for_port_release(p)

finish()
