"""Make a labscript profile and the example data for the screenshots.

    python prepare.py SHARED_DRIVE

Run with the Python of a venv in which the suite is installed. The profile is made at
~/labscript-suite, which must not exist or must have been made by the test harness or
by this script; it is deleted and made again. SHARED_DRIVE must not exist, must be
empty or must have been made by this script; it is deleted and made again. The
profile's shared drive is SHARED_DRIVE, and its apparatus has the devices of
fixture/connection_table.py. The script compiles the connection table, makes a globals
file, compiles a sequence of twelve shots from the globals and gives each shot a run
time, as BLACS would, so that lyse loads it. It then adds two globals that cannot be
evaluated, so that runmanager shows its colour for errors. It writes the paths that
shoot.py needs to SHARED_DRIVE/screenshots.json."""

import argparse
import configparser
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'fixture'
PROFILE_MARKER = '.created-by-labscript-test-harness'

# (group, name, value, units, expansion)
GLOBALS = [
    ('MOT', 'mot_load_time', '[1.0, 2.0]', 's', 'outer'),
    ('MOT', 'mot_coil_current', '3.5', 'A', ''),
    ('MOT', 'mot_detuning', '-12', 'MHz', ''),
    ('MOT', 'mot_power', '0.8', '', ''),
    ('molasses', 'molasses_time', '5', 'ms', ''),
    ('molasses', 'molasses_detuning', '-45', 'MHz', ''),
    ('molasses', 'molasses_power', '0.35', '', ''),
    ('imaging', 'tof', 'np.linspace(1, 11, 6)', 'ms', 'outer'),
    ('imaging', 'imaging_detuning', '0', 'MHz', ''),
    ('imaging', 'imaging_power', '0.15', '', ''),
    ('imaging', 'exposure_time', '200', 'us', ''),
    ('imaging', 'camera_binning', '2', '', ''),
    ('imaging', 'imaging_axis', "'vertical'", '', ''),
    ('imaging', 'save_raw_images', 'True', '', ''),
]
# Globals that are added after the shots are compiled:
ERROR_GLOBALS = [
    ('imaging', 'probe_frequency', 'imaging_detuning + probe_offset', 'MHz', ''),
    ('imaging', 'repump_power', '0.5 *', '', ''),
]
SINGLESHOT_ROUTINES = ['fit_cloud.py', 'check_saturation.py']
MULTISHOT_ROUTINES = ['temperature.py', 'loading_curve.py']

parser = argparse.ArgumentParser()
parser.add_argument('shared_drive')
args = parser.parse_args()
shared_drive = Path(args.shared_drive).resolve()

# labscript_utils makes a profile when it is imported, so the old profile is removed and
# the new one made before anything imports it.
from labscript_profile import LABSCRIPT_SUITE_PROFILE as profile  # noqa: E402
from labscript_profile import default_labconfig_path  # noqa: E402
from labscript_profile.create import create_profile  # noqa: E402

if (shared_drive.exists() and any(shared_drive.iterdir())
        and not (shared_drive / 'screenshots.json').exists()):
    sys.exit(f'{shared_drive} is not empty and was not made by this script')

old_secret = None
if profile.exists():
    if not (profile / PROFILE_MARKER).exists():
        sys.exit(f'{profile} exists and was not made by the test harness or by this script')
    keys = list((profile / 'labconfig').glob('zpsecret-*.key'))
    if keys:
        old_secret = keys[0].read_text()
    shutil.rmtree(profile)
create_profile()
(profile / PROFILE_MARKER).write_text('')
if old_secret is not None:
    # A zlock server left running by an earlier run keeps the old secret.
    for key in (profile / 'labconfig').glob('zpsecret-*.key'):
        key.write_text(old_secret)

if shared_drive.exists():
    shutil.rmtree(shared_drive)
shared_drive.mkdir(parents=True)
config = configparser.ConfigParser(interpolation=None)
config.read(default_labconfig_path())
config.set('DEFAULT', 'shared_drive', str(shared_drive))
with open(default_labconfig_path(), 'w') as f:
    config.write(f)

import labscript_utils.h5_lock  # noqa: E402, F401
import h5py  # noqa: E402
import runmanager  # noqa: E402
from labscript_utils.labconfig import LabConfig  # noqa: E402

labconfig = LabConfig()
ct_py = Path(os.path.expandvars(labconfig.get('paths', 'connection_table_py')))
ct_h5 = Path(os.path.expandvars(labconfig.get('paths', 'connection_table_h5')))
labscriptlib = ct_py.parent
analysislib = Path(os.path.expandvars(labconfig.get('DEFAULT', 'analysislib')))

for path in labscriptlib.glob('*.py'):
    if path.name != '__init__.py':
        path.unlink()
connection_table = (FIXTURE / 'connection_table.py').read_text()
ct_py.write_text(connection_table)
devices = connection_table.split("\n\nif __name__ == '__main__':")[0]
experiment = labscriptlib / 'mot_tof.py'
experiment.write_text(devices + '\n\n' + (FIXTURE / 'sequence.py').read_text())

analysislib.mkdir(parents=True, exist_ok=True)
for name in SINGLESHOT_ROUTINES + MULTISHOT_ROUTINES:
    shutil.copy(FIXTURE / name, analysislib / name)


def compile_shots(script, run_files):
    results = []
    runmanager.compile_multishot_async(str(script), [str(f) for f in run_files],
                                       done_callback=results.append)
    if results != [True] * len(run_files):
        sys.exit(f'compiling {script} failed')


ct_h5.parent.mkdir(parents=True, exist_ok=True)
runmanager.new_globals_file(str(ct_h5))
compile_shots(ct_py, [ct_h5])

globals_file = labscriptlib / 'globals.h5'
runmanager.new_globals_file(str(globals_file))


def add_globals(globals_list):
    for group, name, value, units, expansion in globals_list:
        if group not in runmanager.get_grouplist(str(globals_file)):
            runmanager.new_group(str(globals_file), group)
        runmanager.new_global(str(globals_file), group, name)
        runmanager.set_value(str(globals_file), group, name, value)
        runmanager.set_units(str(globals_file), group, name, units)
        if expansion:
            runmanager.set_expansion(str(globals_file), group, name, expansion)


add_globals(GLOBALS)

sequence_globals = runmanager.get_globals(runmanager.get_all_groups(str(globals_file)))
evaluated, _, _ = runmanager.evaluate_globals(sequence_globals)
shots = runmanager.expand_globals(sequence_globals, evaluated)
sequence_attrs, output_dir, prefix = runmanager.new_sequence_details(str(experiment))
run_files = list(runmanager.make_run_files(output_dir, sequence_globals, shots,
                                           sequence_attrs, prefix))
compile_shots(experiment, run_files)
add_globals(ERROR_GLOBALS)

run_time = datetime.now().astimezone()
for run_file in run_files:
    with h5py.File(run_file, 'r+') as f:
        f.attrs['run time'] = run_time.strftime('%Y%m%dT%H%M%S.%f%z')
    run_time += timedelta(seconds=4.2)

data = {
    'globals_file': str(globals_file),
    'labscript_file': str(experiment),
    'shots': [str(f) for f in run_files],
    'singleshot_routines': [str(analysislib / name) for name in SINGLESHOT_ROUTINES],
    'multishot_routines': [str(analysislib / name) for name in MULTISHOT_ROUTINES],
}
(shared_drive / 'screenshots.json').write_text(json.dumps(data, indent=1))
print(f'{len(run_files)} shots in {output_dir}')
