"""Experiment for the runmanager-abort step. The global `mode` sets what the script does
after start(): 'ok' returns, 'sleep' sleeps for 100 s, 'loop' loops in Python for 100 s,
'ignore' loops for 100 s ignoring KeyboardInterrupt, and 'freeze' stops the compiler
with SIGSTOP. The globals `abort_timeout` and `kill_lock_timeout` set the compiler's
timeouts."""
import os
import signal
import sys
import time

from labscript import start, stop
from labscript_devices.DummyPseudoclock.labscript_devices import DummyPseudoclock

compiler = sys.modules.get('_runmanager_batch_compiler')
if compiler is not None and hasattr(compiler, 'ABORT_TIMEOUT'):
    compiler.ABORT_TIMEOUT = abort_timeout
    compiler.KILL_LOCK_TIMEOUT = kill_lock_timeout

DummyPseudoclock('pseudoclock')
start()
print('started shot %d with mode %s' % (n, mode), flush=True)
t0 = time.monotonic()
if mode == 'sleep':
    time.sleep(100)
elif mode == 'loop':
    while time.monotonic() - t0 < 100:
        pass
elif mode == 'ignore':
    while time.monotonic() - t0 < 100:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            pass
elif mode == 'freeze':
    os.kill(os.getpid(), signal.SIGSTOP)
stop(1)
