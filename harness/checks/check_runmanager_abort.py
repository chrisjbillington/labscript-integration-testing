"""Run the runmanager GUI in this process under the offscreen platform and compile the
experiment in fixtures/runmanager_abort, which sleeps, loops in Python, ignores
KeyboardInterrupt or, outside Windows, stops itself with SIGSTOP, as a global sets. The
Abort button interrupts a compilation in time.sleep() or in a Python loop within 1 s, the
next shot is not compiled, and the compiler keeps running. The Restart subprocess button
ends a compiler in a Python loop promptly with exit status 0 and one that ignores the
interrupt after its abort timeout, and kills a stopped compiler after its quit timeout;
the timeouts are shortened for the check. After each of these the compiler compiles
three shots. The checks are reported as KNOWN when the installed runmanager does not have
the feature."""

import os
import runpy
import sys
import time
import traceback
from pathlib import Path

from _common import FIXTURES, WORK, check, finish

sys.argv = ['runmanager']
out = WORK / 'runmanager_abort'
out.mkdir(exist_ok=True)
EXPERIMENT = str(FIXTURES / 'runmanager_abort' / 'experiment.py')

import runmanager  # noqa: E402
from qtutils.qt import QtCore, QtWidgets  # noqa: E402

FEATURE = 'runmanager #152'
HAS_FEATURE = 'ABORT_TIMEOUT' in (Path(runmanager.__file__).parent / 'batch_compiler.py').read_text()
KNOWN = None if HAS_FEATURE else FEATURE
# Slack in the upper bound of each duration, for slow runners:
SLACK = 3

BaseQApplication = QtWidgets.QApplication


def wait(seconds, condition=lambda: True, limit=120):
    qapp = QtWidgets.QApplication.instance()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds or not condition():
        qapp.processEvents()
        time.sleep(0.02)
        if time.monotonic() - t0 > limit:
            return False
    return True


def run():
    rm = sys.modules['__main__']
    app = rm.app
    from runmanager import group_manager as gm
    wait(1)

    globals_file = str(out / 'globals.h5')
    if os.path.exists(globals_file):
        os.remove(globals_file)
    gm.new_globals_file(globals_file)
    gm.new_group(globals_file, 'g')
    for name, value in [('mode', "'ok'"), ('n', '[1, 2, 3]'), ('abort_timeout', '1'),
                        ('kill_lock_timeout', '2')]:
        gm.new_global(globals_file, 'g', name)
        gm.set_value(globals_file, 'g', name, value)
    app.ui.lineEdit_labscript_file.setText(EXPERIMENT)
    app.ui.checkBox_run_shots.setChecked(False)
    app.ui.checkBox_view_shots.setChecked(False)
    app.open_globals_file(globals_file)
    app.open_group(globals_file, 'g')
    app.get_group_item_by_name(globals_file, 'g', app.GROUPS_COL_ACTIVE).setCheckState(QtCore.Qt.Checked)
    tab = app.currently_open_groups[globals_file, 'g']

    def parsed():
        """Whether runmanager has no pre-parse of the globals pending and has set the
        automatic expansion of n, which gives three shots"""
        return (app.preparse_globals_required.unfinished_tasks == 0
                and app.ui.pushButton_engage.isEnabled()
                and app.ui.pushButton_engage.text() == 'Engage (3 shots)')

    check(wait(0, parsed, limit=60),
          f'start-up: the globals are parsed with n expanded ({app.ui.pushButton_engage.text()!r})')

    def output():
        return app.output_box.output_textedit.toPlainText()

    def set_mode(mode):
        tab.change_global_value('mode', tab.get_global_item_by_name('mode', tab.GLOBALS_COL_VALUE).text(),
                                repr(mode), interactive=False)
        wait(0, parsed, limit=60)

    def idle():
        return app.compile_queue.empty() and not app.ui.pushButton_abort.isEnabled()

    def engage_and_wait_for_start(mode):
        """Engage with the given mode and wait until the first shot has started"""
        set_mode(mode)
        start = len(output())
        app.on_engage_clicked()
        if mode == 'freeze':
            # The compiler stops before its output is sent:
            ok = wait(0, lambda: 'shot 1 of 3' in output()[start:], limit=60)
            wait(2)
        else:
            ok = wait(0, lambda: 'started shot 1 with mode %s' % mode in output()[start:], limit=60)
        return start, ok

    def check_ok_compile(name):
        start, ok = engage_and_wait_for_start('ok')
        finished = wait(0.5, idle, limit=60)
        text = output()[start:]
        if not check(ok and finished and 'shot 3 of 3' in text and 'Ready.' in text,
                     f'{name}: the compiler then compiles three shots'):
            print(text[-2000:], flush=True)

    def restart_subprocess():
        """Click Restart subprocess and wait for the new compiler"""
        start = len(output())
        app.ui.pushButton_restart_subprocess.click()
        wait(0, lambda: 'Spawning new compiler subprocess...done.' in output()[start:], limit=90)
        wait(0.5, idle, limit=10)

    check_ok_compile('start-up')

    for mode in ['sleep', 'loop']:
        name = f'abort during {mode}'
        pid = app.child.pid
        start, ok = engage_and_wait_for_start(mode)
        check(ok, f'{name}: the shot starts')
        t0 = time.monotonic()
        app.ui.pushButton_abort.click()
        stopped = wait(0, idle, limit=1 + SLACK)
        dt = time.monotonic() - t0
        # Text written to the output box is displayed by its thread, which can be after the
        # Abort button is disabled:
        wait(0, lambda: all(s in output()[start:] for s in ['Compilation interrupted', 'Compilation aborted']),
             limit=5)
        text = output()[start:]
        check(stopped, f'{name}: the compilation stops within {1 + SLACK} s ({dt:.2f} s)', known=KNOWN)
        check('Compilation interrupted' in text and 'Compilation aborted' in text,
              f'{name}: the output says that the compilation was interrupted and aborted',
              known=KNOWN)
        if not stopped:
            restart_subprocess()
            continue
        check('shot 2 of 3' not in text, f'{name}: the next shot is not compiled')
        check(app.child.pid == pid and app.child.poll() is None,
              f'{name}: the compiler process keeps running')
        check_ok_compile(name)

    def restart_check(name, mode, exit_range, returncode):
        child = app.child
        start, ok = engage_and_wait_for_start(mode)
        check(ok, f'{name}: the shot starts')
        t0 = time.monotonic()
        app.ui.pushButton_restart_subprocess.click()
        exited = wait(0, lambda: child.poll() is not None, limit=exit_range[1] + SLACK + 70)
        dt = time.monotonic() - t0
        check(exited and exit_range[0] <= dt <= exit_range[1] + SLACK and child.returncode == returncode,
              f'{name}: the compiler exits after {exit_range[0]} to {exit_range[1]} s with status '
              f'{returncode} ({dt:.2f} s, status {child.returncode})', known=KNOWN)
        wait(0, lambda: 'Spawning new compiler subprocess...done.' in output()[start:], limit=10)
        wait(0.5, idle, limit=10)
        check_ok_compile(name)

    restart_check('restart subprocess during a Python loop', 'loop', (0, 1), 0)
    restart_check('restart subprocess during a compilation that ignores the interrupt',
                  'ignore', (1, 2), 0)
    if sys.platform != 'win32' and HAS_FEATURE:
        app.QUIT_TIMEOUT = 3
        restart_check('restart subprocess with the compiler stopped by SIGSTOP', 'freeze', (3, 4), -9)

    app.to_child.put(['quit', None])
    QtWidgets.QApplication.instance().exit(0)


def start():
    try:
        run()
    except Exception:
        traceback.print_exc()
        check(False, 'the checks ran without an exception')
        QtWidgets.QApplication.instance().exit(1)


class QApplication(BaseQApplication):
    def exec(self):
        # The checks start in the event loop. runmanager processes events before it calls
        # exec(), and exit() called from those has no effect.
        QtCore.QTimer.singleShot(0, start)
        return super().exec()


QtWidgets.QApplication = QApplication
runpy.run_module('runmanager', run_name='__main__', alter_sys=True)
finish()
