"""Worker for the blacs-workers step"""
import os
import signal
import time

import blacs.tab_base_classes
from blacs.tab_base_classes import Worker


class TestWorker(Worker):
    def init(self):
        pass

    def pid(self):
        return os.getpid()

    def set_timeouts(self, abort, kill_lock):
        blacs.tab_base_classes.WORKER_ABORT_TIMEOUT = abort
        blacs.tab_base_classes.WORKER_KILL_LOCK_TIMEOUT = kill_lock

    def sleep(self, delay):
        time.sleep(delay)
        return True

    def spin(self, duration):
        t0 = time.monotonic()
        while time.monotonic() - t0 < duration:
            pass
        return True

    def ignore_interrupt(self, duration):
        t0 = time.monotonic()
        while time.monotonic() - t0 < duration:
            try:
                time.sleep(0.1)
            except KeyboardInterrupt:
                pass
        return True

    def hold_file(self, path, duration):
        """Write to an HDF5 file for `duration` seconds, ignoring interrupts, then close
        it and keep ignoring them"""
        import h5py

        with h5py.File(path, 'w') as f:
            f.create_dataset('x', data=list(range(10)))
            self.ignore_interrupt(duration)
        self.ignore_interrupt(3600)

    def freeze(self):
        os.kill(os.getpid(), signal.SIGSTOP)

    def shutdown(self):
        with open(os.environ['BLACS_WORKERS_RECORD'], 'a') as f:
            f.write('shutdown %d\n' % os.getpid())
