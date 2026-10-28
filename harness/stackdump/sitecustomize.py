"""Imported at startup by every Python process of a step, from the PYTHONPATH that the
harness sets. If the process is still running at the time HARNESS_STACKS_AT, faulthandler
writes the stack of each of its threads to <pid>-<script>.txt in HARNESS_STACKS."""

import os

_dir = os.environ.get('HARNESS_STACKS')
_at = os.environ.get('HARNESS_STACKS_AT')
if _dir and _at:
    import faulthandler
    import sys
    import time

    _delay = float(_at) - time.time()
    if _delay > 0:
        _label = 'python'
        _argv = sys.orig_argv[1:]
        _i = 0
        while _i < len(_argv):
            _arg = _argv[_i]
            if _arg in ('-X', '-W'):
                _i += 2
            elif _arg == '-m':
                _label = _argv[_i + 1] if _i + 1 < len(_argv) else _label
                break
            elif _arg == '-c':
                _label = 'c'
                break
            elif _arg.startswith('-'):
                _i += 1
            else:
                _label = os.path.basename(_arg)
                break
        _file = open(os.path.join(_dir, f'{os.getpid()}-{_label}.txt'), 'w')
        faulthandler.dump_traceback_later(_delay, file=_file)
