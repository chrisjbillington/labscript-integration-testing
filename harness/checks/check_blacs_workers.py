"""Run a BLACS device tab in this process under the offscreen platform, with a worker
process from fixtures/blacs_workers, and check how the tab ends its worker. A restart
while the worker is idle, in time.sleep() or in a Python loop ends the worker promptly
with exit status 0; a worker with a job that ignores KeyboardInterrupt exits once the
interrupt has gone unanswered for the abort timeout, or once its HDF5 file is closed, and
the file is readable; outside Windows, a worker stopped with SIGSTOP is killed after the
quit timeout. The timeouts are shortened for the check. After each restart the new worker
runs a job. A fatal error ends the worker without calling its shutdown() method. The stop
button runs shutdown() and ends the worker, the tab then runs no states and has a message
that cannot be dismissed, and the button starts the tab again. The checks of the exit
status and of the stop button are reported as KNOWN when the installed BLACS does not
have the feature."""

import os
import sys
import tempfile
import threading
import time
import traceback

from _common import FIXTURES, WORK, check, finish

os.environ['PYTHONPATH'] = os.pathsep.join(
    [str(FIXTURES / 'blacs_workers')] + [p for p in [os.environ.get('PYTHONPATH')] if p]
)
RECORD_FILE = WORK / 'blacs_workers_record.txt'
os.environ['BLACS_WORKERS_RECORD'] = str(RECORD_FILE)

import labscript_utils.h5_lock  # noqa: F401
import h5py
from qtutils.qt.QtWidgets import QApplication, QWidget, QVBoxLayout
from qtutils import inmain
import blacs.tab_base_classes
from blacs.tab_base_classes import (
    Tab,
    define_state,
    MODE_MANUAL,
    MODE_BUFFERED,
    MODE_TRANSITION_TO_BUFFERED,
    MODE_TRANSITION_TO_MANUAL,
)
from labscript_utils.qtwidgets.dragdroptab import DragDropTabWidget

ALL = MODE_MANUAL | MODE_BUFFERED | MODE_TRANSITION_TO_BUFFERED | MODE_TRANSITION_TO_MANUAL
QUIT_FEATURE = 'blacs #145'
STOP_FEATURE = 'blacs #146'
HAS_QUIT = hasattr(blacs.tab_base_classes, 'WORKER_QUIT_TIMEOUT')
HAS_STOP = hasattr(Tab, 'stop')
# Slack in the upper bound of each duration, for slow runners:
SLACK = 3

REC = []


class CheckTab(Tab):
    def __init__(self, notebook, settings, restart=False):
        Tab.__init__(self, notebook, settings, restart)
        self.create_worker('w', 'workers_fixture.TestWorker')

    @define_state(ALL, True)
    def s_job(self, funcname, *args):
        REC.append(('start', funcname))
        result = yield (self.queue_work('w', funcname, *args))
        REC.append(('result', funcname, result))

    @define_state(ALL, True)
    def s_raise(self):
        raise RuntimeError('deliberate state failure')


class FakeConnection:
    BLACS_connection = 'None'
    properties = {}


class FakeConnectionTable:
    def find_by_name(self, device_name):
        return FakeConnection()


def wait_for(condition, timeout=30):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if inmain(condition):
            return True
        time.sleep(0.02)
    return False


def idle(tab):
    return tab.state == 'idle' and not tab.event_queue.list_of_states


def run_job(tab, funcname, *args, timeout=30):
    n = len(REC)
    tab.s_job(funcname, *args)
    if not wait_for(lambda: any(r[:2] == ('result', funcname) for r in REC[n:]), timeout):
        raise RuntimeError('job %s did not complete; tab state %s' % (funcname, tab.state))


def start_job(tab, funcname, *args):
    n = len(REC)
    tab.s_job(funcname, *args)
    wait_for(lambda: ('start', funcname) in REC[n:])
    time.sleep(0.5)


def worker_child(tab):
    return inmain(lambda: tab.workers['w'][0].child)


def wait_exit(child, timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if child.poll() is not None:
            return time.monotonic() - t0, child.returncode
        time.sleep(0.02)
    return None, None


def records():
    try:
        return RECORD_FILE.read_text().split('\n')
    except FileNotFoundError:
        return []


def restart_check(tab, name, job, exit_range, returncode, setup=None, end=None, known=None):
    """Start a job, end the worker with end (default: restart the tab), and check that the
    worker exits after a time in exit_range with the given return code."""
    if setup is not None:
        setup()
    child = worker_child(tab)
    if job is not None:
        start_job(tab, *job)
    inmain(end or tab.restart)
    dt, code = wait_exit(child, exit_range[1] + SLACK + 70)
    check(dt is not None and exit_range[0] <= dt <= exit_range[1] + SLACK and code == returncode,
          f'{name}: the worker exits after {exit_range[0]} to {exit_range[1]} s with status '
          f'{returncode} ({dt if dt is None else round(dt, 2)} s, status {code})', known=known)
    return child


def check_runs_jobs(tab, name, old_child):
    def started():
        worker = tab.workers.get('w')
        return worker is not None and worker[0].child not in (None, old_child)

    ok = wait_for(started) and wait_for(lambda: idle(tab))
    if ok:
        try:
            run_job(tab, 'sleep', 0)
        except RuntimeError:
            ok = False
    check(ok, f'{name}: the new worker runs a job')
    check(inmain(lambda: tab.error_message) == '', f'{name}: the tab has no error')


def run_checks(tab, directory):
    run_job(tab, 'sleep', 0)
    quit_known = None if HAS_QUIT else QUIT_FEATURE
    # A restart waits for this long for a busy worker's shutdown() before ending it:
    w = getattr(Tab, 'SHUTDOWN_TIMEOUT', 0)
    # QTimer is accurate to 5%:
    w0 = 0.9 * w

    def short_timeouts(abort, kill_lock):
        return lambda: run_job(tab, 'set_timeouts', abort, kill_lock)

    child = restart_check(tab, 'restart when idle', None, (0, 1), 0, known=quit_known)
    check_runs_jobs(tab, 'restart when idle', child)
    child = restart_check(tab, 'restart during time.sleep', ('sleep', 100), (w0, w + 1), 0,
                          known=quit_known)
    check_runs_jobs(tab, 'restart during time.sleep', child)
    child = restart_check(tab, 'restart during a Python loop', ('spin', 100), (w0, w + 1), 0,
                          known=quit_known)
    check_runs_jobs(tab, 'restart during a Python loop', child)
    child = restart_check(tab, 'restart during a job that ignores the interrupt',
                          ('ignore_interrupt', 100), (w0 + 1, w + 2), 0,
                          setup=short_timeouts(1, 30), known=quit_known)
    check_runs_jobs(tab, 'restart during a job that ignores the interrupt', child)
    path = os.path.join(directory, 'held.h5')
    child = restart_check(tab, 'restart during a job that ignores the interrupt and writes '
                          'an HDF5 file for 6 s', ('hold_file', path, 6), (5, 7), 0,
                          setup=short_timeouts(1, 30), known=quit_known)
    try:
        with h5py.File(path, 'r') as f:
            readable = list(f['x'][:]) == list(range(10))
    except Exception:
        traceback.print_exc()
        readable = False
    # Without the feature, the worker is terminated with the file open on Windows only:
    check(readable, 'the HDF5 file written by the job is readable',
          known=quit_known if sys.platform == 'win32' else None)
    check_runs_jobs(tab, 'restart during a job that writes an HDF5 file', child)
    if sys.platform != 'win32' and HAS_QUIT:
        blacs.tab_base_classes.WORKER_QUIT_TIMEOUT = 3
        child = restart_check(tab, 'restart of a worker stopped with SIGSTOP', ('freeze',),
                              (w0 + 3, w + 3), -9)
        check_runs_jobs(tab, 'restart of a worker stopped with SIGSTOP', child)

    run_job(tab, 'sleep', 0)
    RECORD_FILE.write_text('')
    child = worker_child(tab)
    tab.s_raise()
    wait_for(lambda: tab.state == 'fatal error')
    dt, code = wait_exit(child, 10 + SLACK)
    stop_known = None if HAS_STOP else STOP_FEATURE
    check(code == 0, 'a fatal error ends the worker with status 0', known=stop_known)
    check(not any(r.startswith('shutdown') for r in records()),
          'a fatal error does not call the worker\'s shutdown()')
    inmain(tab.restart)
    check_runs_jobs(tab, 'restart after a fatal error', child)

    if not check(HAS_STOP, 'the tab has a stop button', known=stop_known):
        return
    RECORD_FILE.write_text('')
    child = restart_check(tab, 'stop when idle', None, (0, 1), 0, end=tab._ui.button_stop.click)
    check('shutdown %d' % child.pid in records(), 'stop when idle: shutdown() runs in the worker')
    check(wait_for(lambda: tab.state == 'stopped', 10), 'stop when idle: the tab is stopped')
    check(inmain(lambda: tab.error_message) != '',
          'stop when idle: the tab has a message, so that the queue does not run shots')
    check(not inmain(tab._ui.button_close.isEnabled),
          'stop when idle: the message cannot be dismissed')
    check(inmain(tab._ui.button_stop.toolTip).startswith('Start'),
          'stop when idle: the stop button is a start button')
    n = len(REC)
    tab.s_job('sleep', 0)
    time.sleep(1)
    check(REC[n:] == [], 'stop when idle: the tab runs no states')
    inmain(tab._ui.button_stop.click)
    check_runs_jobs(tab, 'start after stop', child)
    check(inmain(tab._ui.button_stop.toolTip).startswith('Stop'),
          'start after stop: the button is a stop button again')
    RECORD_FILE.write_text('')
    child = restart_check(tab, 'stop during time.sleep', ('sleep', 100), (w0, w + 1), 0,
                          end=tab._ui.button_stop.click)
    check(not any(r.startswith('shutdown') for r in records()),
          'stop during time.sleep: shutdown() does not run, since the worker is busy')
    check(wait_for(lambda: tab.state == 'stopped', 10), 'stop during time.sleep: the tab is stopped')
    inmain(tab.restart)
    check_runs_jobs(tab, 'restart after stop', child)


def main():
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout(window)
    notebook = DragDropTabWidget()
    layout.addWidget(notebook)
    tab = CheckTab(notebook, settings={'device_name': 'tab', 'connection_table': FakeConnectionTable()})
    window.show()
    directory = tempfile.mkdtemp(prefix='blacs-workers-', dir=WORK)

    def run():
        try:
            run_checks(tab, directory)
        except Exception:
            traceback.print_exc()
            check(False, 'the checks ran without an exception')
        inmain(app.quit)

    threading.Thread(target=run, daemon=True).start()
    app.exec()
    inmain(tab.close_tab)
    finish()


if __name__ == '__main__':
    main()
