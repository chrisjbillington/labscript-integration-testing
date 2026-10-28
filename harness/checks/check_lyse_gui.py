"""Run the lyse GUI in this process under the offscreen platform. Check that a shot file
that has not been run is not loaded; that the results of single-shot routines appear in
the dataframe and the shots table when the shot is analysed, analysed again, and analysed
with a routine that fails after saving a result; that a failing multishot routine
does not pause analysis or stop the next multishot routine; that lyse code issues no
DeprecationWarning when the results add columns to the dataframe; and exercise the Abort
button: a routine that loops in Python and a routine that is blocked in a long sleep are
interrupted and their workers survive; a routine that ignores the interrupt with an HDF5
file open has its worker restarted once it closes the file, and the file is readable;
analysis is paused in each case, and an interrupted worker then runs a routine to
completion; Abort of a multishot routine pauses analysis, the next multishot routine
does not run, and resuming runs the multishot routines again. In a subprocess, check that the
Edit columns dialog survives being updated as 200 columns are added one at a time. The Abort checks are reported as KNOWN when
lyse has no Abort button."""

import faulthandler
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import time
import warnings
from pathlib import Path

from _common import SHOTS, WORK, check, finish, load_state

# Print the Python stack of every thread if this process or a Python process that it
# starts crashes:
faulthandler.enable(all_threads=True)
os.environ['PYTHONFAULTHANDLER'] = '1'

state = load_state()
shot = state['example_shot']

# Importing the lyse entry module creates the QApplication and shows the splash, as
# starting lyse does; the application itself is created below.
import lyse.__main__ as lyse_main
import h5py
from qtutils.qt import QtCore, QtWidgets

qapplication = QtWidgets.QApplication.instance()

ABORT_FEATURE = 'lyse #153'
routines_dir = WORK / 'routines'
routines_dir.mkdir(exist_ok=True)
loop_script = routines_dir / 'loop_routine.py'
loop_marker = routines_dir / 'loop_routine.running'
sleep_script = routines_dir / 'sleep_routine.py'
sleep_marker = routines_dir / 'sleep_routine.running'
stubborn_script = routines_dir / 'stubborn_routine.py'
stubborn_marker = routines_dir / 'stubborn_routine.running'
stubborn_h5 = routines_dir / 'stubborn_routine.h5'
multishot_sleep_script = routines_dir / 'multishot_sleep.py'
multishot_sleep_marker = routines_dir / 'multishot_sleep.running'
# Duration for which the stubborn routine keeps its HDF5 file open after the second
# interrupt, which is sent when lyse tells the worker to quit:
STUBBORN_HOLD = 8
for path in [loop_marker, sleep_marker, stubborn_marker, stubborn_h5, multishot_sleep_marker]:
    path.unlink(missing_ok=True)
loop_script.write_text(
    'import time\n'
    'from pathlib import Path\n'
    f'Path({str(loop_marker)!r}).touch()\n'
    'while True:\n'
    '    time.sleep(0.01)\n'
)
sleep_script.write_text(
    'import time\n'
    'from pathlib import Path\n'
    f'Path({str(sleep_marker)!r}).touch()\n'
    'time.sleep(600)\n'
)
multishot_sleep_script.write_text(
    'import time\n'
    'from pathlib import Path\n'
    f'Path({str(multishot_sleep_marker)!r}).touch()\n'
    'time.sleep(600)\n'
)
stubborn_script.write_text(
    'import time\n'
    'from pathlib import Path\n'
    'import h5py\n'
    'interrupts = 0\n'
    'close_time = None\n'
    f'with h5py.File({str(stubborn_h5)!r}, "w") as f:\n'
    '    f.create_dataset("data", data=list(range(1000)))\n'
    f'    Path({str(stubborn_marker)!r}).touch()\n'
    '    while close_time is None or time.monotonic() < close_time:\n'
    '        try:\n'
    '            time.sleep(0.1)\n'
    '        except KeyboardInterrupt:\n'
    '            interrupts += 1\n'
    '            if interrupts == 2:\n'
    f'                close_time = time.monotonic() + {STUBBORN_HOLD}\n'
    'while True:\n'
    '    try:\n'
    '        time.sleep(0.1)\n'
    '    except KeyboardInterrupt:\n'
    '        pass\n'
)


def wait_until(cond, timeout):
    """Process Qt events until cond() is true or timeout seconds have passed."""
    t0 = time.monotonic()
    while True:
        qapplication.processEvents()
        if cond():
            return True
        if time.monotonic() - t0 > timeout:
            return False
        time.sleep(0.05)


class LogCounter(logging.Handler):
    """Counts the records with a given message."""

    def __init__(self, message):
        super().__init__()
        self.message = message
        self.count = 0

    def emit(self, record):
        if record.getMessage() == self.message:
            self.count += 1


# The analysis thread logs this once it has paused after a routine error and has nothing
# more to do. Resuming before then is undone by the pause that the error causes.
paused_log = LogCounter('analysis is paused')
logging.getLogger('lyse.FileBox.analysis_loop').addHandler(paused_log)
# The multishot routine box logs this after each pass, which the analysis thread starts
# once it has finished with the last shot that needed analysis.
multishot_log = LogCounter('completed analysis of None')
logging.getLogger('lyse.RoutineBox.multishot').addHandler(multishot_log)


def copy_shot(name, run):
    """Copy the example shot, without its run time if run is False"""
    path = SHOTS / name
    shutil.copy(shot, path)
    if not run:
        with h5py.File(path, 'r+') as f:
            del f.attrs['run time']
    return str(path)


def set_enabled(box, routine, enabled):
    item = box.model.item(routine.get_row_index(), box.COL_ACTIVE)
    item.setCheckState(QtCore.Qt.Checked if enabled else QtCore.Qt.Unchecked)


def report_unconnected_children(process_tree):
    """Print the exit code of each child process of process_tree that does not connect
    within its startup timeout. Outside Windows, a child that is still running is first
    sent SIGABRT, on which it prints the Python stack of each of its threads."""
    start_child = process_tree.subprocess

    def subprocess_reporting_timeout(path, *args, **kwargs):
        startup_queue = kwargs.setdefault('startup_queue', queue.Queue())
        try:
            return start_child(path, *args, **kwargs)
        except RuntimeError:
            child = startup_queue.get_nowait()
            if child.poll() is None and sys.platform != 'win32':
                print(f'{Path(path).name} (pid {child.pid}) did not connect and is '
                      'running; sending SIGABRT', flush=True)
                child.send_signal(signal.SIGABRT)
                try:
                    child.wait(10)
                except subprocess.TimeoutExpired:
                    pass
            print(f'{Path(path).name} (pid {child.pid}) did not connect; '
                  f'exit code {child.poll()}', flush=True)
            raise

    process_tree.subprocess = subprocess_reporting_timeout


def resume():
    app.filebox.ui.pushButton_analysis_running.setChecked(False)


def output_text():
    return app.output_box.output_textedit.toPlainText()


app = lyse_main.Lyse(qapplication)
report_unconnected_children(app.process_tree)
lyse_main.splash.hide()
filebox = app.filebox
box = app.singleshot_routinebox
try:
    # Shots are loaded with analysis paused, and removed before the Abort checks:
    filebox.ui.pushButton_analysis_running.setChecked(True)
    unrun_shot = copy_shot('not_run.h5', run=False)
    run_shot = copy_shot('run.h5', run=True)
    filebox.incoming_queue.put(unrun_shot)
    filebox.incoming_queue.put(run_shot)
    def loaded(path):
        return path in filebox.shots_model.row_number_by_filepath

    check(wait_until(lambda: loaded(run_shot), 60), 'a shot file that has been run is loaded')
    check(not loaded(unrun_shot) and 'has not been run' in output_text(),
          'a shot file that has not been run is not loaded')

    shots_model = filebox.shots_model
    results_scripts = {}
    for name in ['results_a', 'results_b', 'results_c']:
        results_scripts[name] = routines_dir / f'{name}.py'

    def write_results_script(name, value, fail=False):
        results_scripts[name].write_text(
            'import lyse\n'
            f'lyse.Run(lyse.path).save_result("value", {value!r})\n'
            + ('raise RuntimeError("routine failed")\n' if fail else '')
        )

    def result(name):
        column = (name, 'value') + ('',) * (shots_model.nlevels - 2)
        row = shots_model.row_number_by_filepath[run_shot]
        if column not in shots_model.dataframe.columns:
            return None, None
        index = shots_model._model.index(row, shots_model.column_indices[column])
        return shots_model.dataframe.at[row, column], index.data()

    def analyse(mark_not_done, until_paused=False):
        n_multishot = multishot_log.count
        n_paused = paused_log.count
        if mark_not_done:
            shots_model._view.selectAll()
            filebox.on_mark_selection_not_done_clicked()
        resume()
        if until_paused:
            return wait_until(lambda: paused_log.count > n_paused, 60)
        return wait_until(lambda: multishot_log.count > n_multishot, 60)

    write_results_script('results_a', 1.5)
    write_results_script('results_b', 'x')
    write_results_script('results_c', 3.5)
    box.add_routines([(str(path), QtCore.Qt.Checked) for path in results_scripts.values()])
    if not check(len(box.routines) == 3, 'the workers of all three routines started'):
        finish()
    results_routines = dict(zip(results_scripts, box.routines))
    set_enabled(box, results_routines['results_c'], False)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter('always', DeprecationWarning)
        check(analyse(mark_not_done=False), 'the shot is analysed by two of three routines')
    lyse_deprecations = [
        f'{Path(w.filename).name}:{w.lineno}: {w.message}' for w in caught_warnings
        if issubclass(w.category, DeprecationWarning) and 'lyse' in Path(w.filename).parts
    ]
    check(not lyse_deprecations,
          f'adding the result columns issues no DeprecationWarning in lyse: {lyse_deprecations}')
    check(result('results_a') == (1.5, '1.5') and result('results_b') == ('x', 'x'),
          'the results of both enabled routines are in the dataframe and the shots table: '
          f'{result("results_a")}, {result("results_b")}')
    check(result('results_c') == (None, None), 'the disabled routine did not run')
    check(results_routines['results_a'].done and results_routines['results_b'].done
          and not results_routines['results_c'].done, 'the routine statuses are done, done, clear')

    write_results_script('results_a', 4.5)
    write_results_script('results_b', 'y')
    check(analyse(mark_not_done=True), 'the shot is analysed again')
    check(result('results_a') == (4.5, '4.5') and result('results_b') == ('y', 'y'),
          'the new results replace the old in the dataframe and the shots table: '
          f'{result("results_a")}, {result("results_b")}')

    write_results_script('results_a', 6.5)
    write_results_script('results_b', 'z', fail=True)
    check(analyse(mark_not_done=True, until_paused=True) and filebox.analysis_paused,
          'analysis is paused after a routine error')
    check(results_routines['results_b'].error, 'the failed routine has the error status')
    check(result('results_a') == (6.5, '6.5') and result('results_b') == ('z', 'z'),
          'the results saved before the error are in the dataframe and the shots table: '
          f'{result("results_a")}, {result("results_b")}')

    box.ui.treeView.selectAll()
    box.remove_selection(confirm=False)
    shots_model._view.selectAll()
    shots_model.remove_selection(confirm=False)

    multishot_box = app.multishot_routinebox
    multishot_scripts = [routines_dir / 'multishot_fails.py', routines_dir / 'multishot_ok.py']
    multishot_scripts[0].write_text('raise RuntimeError("multishot routine failed")\n')
    multishot_scripts[1].write_text('import lyse\nlyse.data()\n')
    multishot_box.add_routines([(str(path), QtCore.Qt.Checked) for path in multishot_scripts])
    if not check(len(multishot_box.routines) == 2, 'the workers of both multishot routines started'):
        finish()
    # Requested while paused, so that resuming runs the multishot routines once:
    filebox.on_run_multishot_analysis_clicked()
    n_multishot = multishot_log.count
    resume()
    check(wait_until(lambda: multishot_log.count > n_multishot, 60),
          'the multishot routines run when analysis is resumed')
    wait_until(lambda: False, 2)
    failed_routine, ok_routine = multishot_box.routines
    check(failed_routine.error and ok_routine.done,
          'after a multishot routine error, the next multishot routine runs: statuses '
          f'error {failed_routine.error}, done {ok_routine.done}')
    check(not filebox.analysis_paused, 'analysis is not paused after a multishot routine error')
    check(multishot_log.count == n_multishot + 1,
          f'the multishot routines ran once ({multishot_log.count - n_multishot} times)')
    multishot_box.ui.treeView.selectAll()
    multishot_box.remove_selection(confirm=False)

    # In a subprocess, since the failure is a crash:
    edit_columns_script = (
        'from qtutils.qt import QtWidgets\n'
        'app = QtWidgets.QApplication([])\n'
        'from lyse.filebox import EditColumns\n'
        'class Filebox:\n'
        '    def set_columns_visible(self, columns_visible): pass\n'
        'names = {0: "status", 1: "filepath"}\n'
        'visible = {0: True, 1: True}\n'
        'dialog = EditColumns(Filebox(), names, visible)\n'
        'for i in range(200):\n'
        '    names[i + 2] = ("routine", f"value_{i}", "")\n'
        '    visible[i + 2] = True\n'
        '    dialog.update_columns(names, visible)\n'
        '    app.processEvents()\n'
    )
    edit_columns = subprocess.run([sys.executable, '-c', edit_columns_script],
                                  capture_output=True, text=True, timeout=300)
    if edit_columns.returncode != 0:
        print(edit_columns.stderr[-2000:], end='')
    check(edit_columns.returncode == 0,
          'the Edit columns dialog is updated 200 times as columns are added '
          f'(exit code {edit_columns.returncode})')

    if not check(hasattr(filebox.ui, 'pushButton_abort'), 'the filebox has an Abort button',
                 known=ABORT_FEATURE):
        finish()
    import lyse.utils.worker
    ABORT_TIMEOUT = lyse.utils.worker._ABORT_TIMEOUT
    KILL_LOCK_TIMEOUT = lyse.utils.worker._KILL_LOCK_TIMEOUT
    resume()

    box.add_routines([(str(loop_script), QtCore.Qt.Checked)])
    loop_routine = box.routines[0]
    filebox.incoming_queue.put(shot)
    check(wait_until(loop_marker.exists, 120), 'the looping routine started on the shot')
    check(wait_until(lambda: loop_routine.working, 10), 'the routine is marked as working')
    worker = loop_routine.worker
    n_paused = paused_log.count
    t0 = time.monotonic()
    filebox.ui.pushButton_abort.click()
    stopped = wait_until(lambda: loop_routine.error, ABORT_TIMEOUT + 30)
    elapsed = time.monotonic() - t0
    check(stopped, f'the looping routine stopped {elapsed:.1f} s after Abort')
    check(elapsed < ABORT_TIMEOUT, 'the routine stopped before the worker restart timeout')
    check(loop_routine.worker is worker and worker.poll() is None,
          'the worker survived the interrupt')
    check(filebox.analysis_paused, 'analysis is paused after Abort')
    check(wait_until(lambda: 'Interrupted' in output_text(), 10),
          'the output box reports the interrupt')
    check(wait_until(lambda: paused_log.count > n_paused, 10), 'the analysis thread is idle')

    box.add_routines([(str(sleep_script), QtCore.Qt.Checked)])
    sleep_routine = box.routines[1]
    set_enabled(box, loop_routine, False)
    resume()
    check(wait_until(sleep_marker.exists, 120), 'the sleeping routine started on the shot')
    check(wait_until(lambda: sleep_routine.working, 10), 'the sleeping routine is marked as working')
    worker = sleep_routine.worker
    n_paused = paused_log.count
    t0 = time.monotonic()
    filebox.ui.pushButton_abort.click()
    stopped = wait_until(lambda: sleep_routine.error, ABORT_TIMEOUT + 30)
    elapsed = time.monotonic() - t0
    check(stopped, f'the sleeping routine stopped {elapsed:.1f} s after Abort')
    check(elapsed < ABORT_TIMEOUT, 'the routine stopped before the worker restart timeout')
    check(sleep_routine.worker is worker and worker.poll() is None,
          'the worker survived the interrupt')
    check(filebox.analysis_paused, 'analysis is paused after Abort')
    check(wait_until(lambda: paused_log.count > n_paused, 10), 'the analysis thread is idle')

    box.add_routines([(str(stubborn_script), QtCore.Qt.Checked)])
    stubborn_routine = box.routines[2]
    set_enabled(box, sleep_routine, False)
    resume()
    check(wait_until(stubborn_marker.exists, 120), 'the stubborn routine started on the shot')
    check(wait_until(lambda: stubborn_routine.working, 10),
          'the stubborn routine is marked as working')
    worker = stubborn_routine.worker
    n_paused = paused_log.count
    t0 = time.monotonic()
    filebox.ui.pushButton_abort.click()
    stopped = wait_until(lambda: stubborn_routine.error,
                         2 * ABORT_TIMEOUT + KILL_LOCK_TIMEOUT + 30)
    elapsed = time.monotonic() - t0
    # The worker is told to quit ABORT_TIMEOUT after Abort, waits ABORT_TIMEOUT for the
    # routine to stop, then exits when the routine closes its file, STUBBORN_HOLD after
    # the quit:
    check(stopped, f'the stubborn routine stopped {elapsed:.1f} s after Abort')
    check(ABORT_TIMEOUT + STUBBORN_HOLD - 1 < elapsed < 2 * ABORT_TIMEOUT + KILL_LOCK_TIMEOUT,
          'the worker exited when the routine closed its HDF5 file')
    check(stubborn_routine.worker is not worker and worker.poll() not in (None, 0),
          'the unresponsive worker was replaced')
    check(stubborn_routine.worker.poll() is None, 'the new worker is running')
    check('did not stop after' in output_text() and 'worker killed' not in output_text(),
          'the output box reports that the worker exited, and it was not killed')
    with h5py.File(stubborn_h5, 'r') as f:
        check(list(f['data'][:]) == list(range(1000)), 'the routine\'s HDF5 file is readable')
    check(filebox.analysis_paused, 'analysis is paused after the worker restart')
    check(wait_until(lambda: paused_log.count > n_paused, 10), 'the analysis thread is idle')

    loop_script.write_text('print("completed")\n')
    set_enabled(box, loop_routine, True)
    set_enabled(box, stubborn_routine, False)
    resume()
    check(wait_until(lambda: loop_routine.done, 60), 'the interrupted worker ran the routine to completion')
    check(wait_until(lambda: filebox.shots_model.get_first_incomplete() is None, 10),
          'the shot is marked as analysed')
    check(not filebox.analysis_paused, 'analysis is still running')

    multishot_box.add_routines([(str(multishot_sleep_script), QtCore.Qt.Checked),
                                (str(multishot_scripts[1]), QtCore.Qt.Checked)])
    sleep_multishot_routine, ok_routine = multishot_box.routines
    n_multishot = multishot_log.count
    filebox.on_run_multishot_analysis_clicked()
    check(wait_until(multishot_sleep_marker.exists, 120), 'the sleeping multishot routine started')
    check(wait_until(lambda: sleep_multishot_routine.working, 10),
          'the sleeping multishot routine is marked as working')
    filebox.ui.pushButton_abort.click()
    check(wait_until(lambda: multishot_log.count > n_multishot, ABORT_TIMEOUT + 30)
          and sleep_multishot_routine.error, 'the sleeping multishot routine stopped after Abort')
    check(filebox.analysis_paused and not ok_routine.done,
          'after Abort, analysis is paused and the next multishot routine did not run')
    multishot_sleep_script.write_text('print("completed")\n')
    n_multishot = multishot_log.count
    resume()
    check(wait_until(lambda: multishot_log.count > n_multishot, 60)
          and sleep_multishot_routine.done and ok_routine.done,
          'resuming runs the multishot routines again')
finally:
    app.terminate_all_workers()
    wait_until(lambda: all(app.workers_terminated().values()), 15)
    app.server.shutdown()
    # As lyse does when it exits: stop the output box's thread and delete the windows
    # now, rather than in PyQt's QObject cleanup at exit, during which Python code that
    # creates or destroys wrapped Qt objects can crash the interpreter
    # (https://github.com/Python-SIP/sip/pull/121).
    app.output_box.shutdown()
    for widget in QtWidgets.QApplication.topLevelWidgets():
        widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
finish()
