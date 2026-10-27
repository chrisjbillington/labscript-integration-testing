"""Compile the profile's connection table and the example experiment through runmanager,
and check the shot file contents, including the functions of the FunctionRunner that the
profile step adds, and the exposures of the mock camera that it adds."""

import os
import sys
from datetime import datetime
from pathlib import Path

from _common import SHOTS, attempt, check, finish, labconfig, save_state

import labscript_utils.h5_lock  # noqa: F401
import h5py
import runmanager
from labscript_devices.FunctionRunner.utils import deserialise_function

config = labconfig()


def compile_script(script, run_file):
    results = []
    runmanager.compile_labscript_async(script, run_file, done_callback=results.append)
    return results == [True]


# Connection table, as `labscript-profile-create --compile` does it. BLACS needs it.
ct_py = os.path.expandvars(config.get('paths', 'connection_table_py'))
ct_h5 = os.path.expandvars(config.get('paths', 'connection_table_h5'))
Path(ct_h5).parent.mkdir(parents=True, exist_ok=True)
runmanager.new_globals_file(ct_h5)
ok, _ = attempt('connection table compiles', compile_script, ct_py, ct_h5)
check(ok is True, f'connection table compile reported success ({ct_h5})')

# The example experiment, as runmanager compiles a single shot.
SHOTS.mkdir(parents=True, exist_ok=True)
script = str(Path(ct_py).parent / 'example_experiment.py')
run_file = str(SHOTS / 'example_experiment.h5')
sequence_attrs, _, _ = runmanager.new_sequence_details(script, config=config,
                                                       increment_sequence_index=False)
runmanager.make_single_run_file(run_file, {}, {}, sequence_attrs, 0, 1)
ok, _ = attempt('example experiment compiles', compile_script, script, run_file)
check(ok is True, 'example experiment compile reported success')
if ok is not True:
    finish()

with h5py.File(run_file, 'r') as f:
    groups = set(f.keys())
    check({'connection table', 'devices', 'globals', 'time_markers'} <= groups,
          f'shot file groups: {sorted(groups)}')
    devices = set(f['devices'].keys())
    check(devices == {'pseudoclock', 'intermediate_device', 'function_runner', 'camera'},
          f'devices: {sorted(devices)}')
    rows = len(f['connection table'])
    check(rows == 9, f'connection table has {rows} rows')
    markers = len(f['time_markers'])
    check(markers == 3, f'{markers} time markers')
    names = {n.decode() if isinstance(n, bytes) else str(n)
             for n in f['connection table']['name']}
    check({'pseudoclock', 'intermediate_device', 'analog_out', 'digital_out', 'function_runner',
           'camera'} <= names,
          f'connection table names: {sorted(names)}')
    master = f['connection table'].attrs['master_pseudoclock']
    master = master.decode() if isinstance(master, bytes) else str(master)
    check(master == 'pseudoclock', f'master pseudoclock attribute is {master!r}')
    check('PULSE_PROGRAM' in f['devices/pseudoclock'], 'pseudoclock has a pulse program')
    stop_time = f['devices/pseudoclock'].attrs['stop_time']
    check(abs(stop_time - 2.25) < 1e-9, f'stop time {stop_time}')
    table = f['devices/function_runner/FUNCTION_TABLE'][:]
    check(len(table) == 2, f'the FunctionRunner has {len(table)} functions')
    for t, name, source, args, kwargs in table:
        name = name.decode() if isinstance(name, bytes) else name
        source = source.decode() if isinstance(source, bytes) else source
        attempt(f'FunctionRunner function at t={t} deserialises', deserialise_function,
                name, source, args, kwargs)
        check(name == 'record_call' and source.startswith('def record_call(')
              and source.rstrip().endswith("group.attrs['stop'] = label"),
              f'FunctionRunner function at t={t} is the whole source of record_call')
    exposures = [(float(t), name.decode(), frametype.decode())
                 for t, name, frametype, _ in f['devices/camera/EXPOSURES'][:]]
    check(exposures == [(0.5, 'harness', 'first'), (0.75, 'harness', 'second')],
          f'camera exposures: {exposures}')

# BLACS stamps a shot with its run time after running it:
with h5py.File(run_file, 'r+') as f:
    f.attrs['run time'] = datetime.now().strftime('%Y%m%dT%H%M%S.%f')

save_state(connection_table_h5=ct_h5, example_shot=run_file, example_script=script)
finish()
