"""Imported at startup by every Python process of a step, from the PYTHONPATH that the
harness sets.

If the process is still running at the time HARNESS_STACKS_AT, faulthandler writes the
stack of each of its threads to <pid>-<script>.txt in HARNESS_STACKS, the stacks
directory of the step that started the process. The first line of the file
HARNESS_STACKS_STATE is the stacks directory of the step that is running. Once that is a
later step, the process cancels the timer. If the second line is 'dump', the process
writes its stacks to that step's directory."""

import os

_dir = os.environ.get('HARNESS_STACKS')
_at = os.environ.get('HARNESS_STACKS_AT')
_state = os.environ.get('HARNESS_STACKS_STATE')
if _dir and _at and _state:
    import faulthandler
    import sys
    import threading
    import time

    def _label():
        argv = sys.orig_argv[1:]
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg in ('-X', '-W'):
                i += 2
            elif arg == '-m':
                return argv[i + 1] if i + 1 < len(argv) else 'python'
            elif arg == '-c':
                return 'c'
            elif arg.startswith('-'):
                i += 1
            else:
                return os.path.basename(arg)
        return 'python'

    _name = f'{os.getpid()}-{_label()}.txt'
    _delay = float(_at) - time.time()
    _timer_file = None
    if _delay > 0:
        _timer_file = open(os.path.join(_dir, _name), 'w')
        faulthandler.dump_traceback_later(_delay, file=_timer_file)

    def _watch():
        global _timer_file
        dumped = set()
        try:
            while True:
                time.sleep(1)
                try:
                    with open(_state) as f:
                        lines = f.read().splitlines()
                except OSError:
                    continue
                if not lines or lines[0] == _dir:
                    continue
                if _timer_file is not None:
                    faulthandler.cancel_dump_traceback_later()
                    _timer_file.close()
                    _timer_file = None
                if lines[1:2] == ['dump'] and lines[0] not in dumped:
                    dumped.add(lines[0])
                    with open(os.path.join(lines[0], _name), 'w') as f:
                        f.write("At the step's timeout:\n")
                        f.flush()
                        faulthandler.dump_traceback(file=f, all_threads=True)
        except BaseException:
            pass

    threading.Thread(target=_watch, name='harness-stackdump', daemon=True).start()
