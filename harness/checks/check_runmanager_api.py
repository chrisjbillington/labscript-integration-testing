"""Exercise the runmanager library API: globals file CRUD, evaluation, expansion, diff,
run file creation and compilation of the runmanager_test fixture experiment."""

import os
import threading
import time

import numpy as np

from _common import WORK, attempt, check, finish, load_state

import labscript_utils.h5_lock  # noqa: F401
import h5py
import runmanager
import zmq

profile = load_state()['profile']
script = os.path.join(profile, 'userlib', 'labscriptlib', 'runmanager_test', 'experiment.py')
work = WORK / 'runmanager_api'
work.mkdir(parents=True, exist_ok=True)
gf = str(work / 'globals.h5')

API = [
    'new_globals_file', 'new_group', 'new_global', 'set_value', 'set_expansion',
    'get_all_groups', 'get_globals', 'evaluate_globals', 'expand_globals',
    'guess_expansion_type', 'dict_diff', 'globals_diff_groups', 'globals_diff_shots',
    'rename_global', 'rename_group', 'copy_group', 'delete_global', 'delete_group',
    'get_shot_globals', 'new_sequence_details', 'make_run_files',
    'make_run_file_from_globals_files', 'compile_labscript_async',
    'compile_multishot_async', 'compile_labscript_with_globals_files_async',
    'find_comments', 'remove_comments_and_tokenify', 'ExpansionError', 'iterator_to_tuple',
    'flatten_globals', 'get_grouplist', 'get_globalslist', 'get_value', 'get_units',
    'set_units', 'get_expansion', 'next_sequence_index', 'make_single_run_file',
    'is_valid_python_identifier', 'add_expansion_groups',
]
missing = [n for n in API if not hasattr(runmanager, n)]
check(not missing, f'public API present (missing: {missing})')

# Groups and globals
runmanager.new_globals_file(gf)
runmanager.new_group(gf, 'scan')
runmanager.new_group(gf, 'fixed')
for name, value, expansion in [('amplitude', '[0.1, 0.2, 0.3]', 'outer'),
                               ('gain', '(1, 2)', 'zip1'),
                               ('offset', 'array([10, 20])', 'zip1')]:
    runmanager.new_global(gf, 'scan', name)
    runmanager.set_value(gf, 'scan', name, value)
    runmanager.set_expansion(gf, 'scan', name, expansion)
for name, value in [('duration', '1.0'), ('use_do', 'True'), ('derived', 'array(amplitude) * 2')]:
    runmanager.new_global(gf, 'fixed', name)
    runmanager.set_value(gf, 'fixed', name, value)
runmanager.set_expansion(gf, 'fixed', 'derived', '')
check(set(runmanager.get_grouplist(gf)) == {'scan', 'fixed'}, 'get_grouplist')
try:
    runmanager.new_global(gf, 'fixed', '1bad')
    check(False, 'invalid global name rejected')
except ValueError as e:
    check('1bad' in str(e), f'invalid global name rejected: {e}')
runmanager.rename_global(gf, 'fixed', 'use_do', 'flag2')
check('flag2' in runmanager.get_globalslist(gf, 'fixed'), 'rename_global')
runmanager.rename_global(gf, 'fixed', 'flag2', 'use_do')
runmanager.copy_group(gf, 'fixed', gf)
check('fixed_copy' in runmanager.get_grouplist(gf), 'copy_group')
runmanager.delete_group(gf, 'fixed_copy')
check(runmanager.get_value(gf, 'scan', 'gain') == '(1, 2)', 'get_value')
runmanager.set_units(gf, 'fixed', 'duration', 's')
check(runmanager.get_units(gf, 'fixed', 'duration') == 's', 'set_units and get_units')

# Evaluate and expand
groups = runmanager.get_all_groups(gf)
sequence_globals = runmanager.get_globals(groups)
evaluated, hierarchy, expansions = runmanager.evaluate_globals(sequence_globals)
check(np.allclose(evaluated['fixed']['derived'], [0.2, 0.4, 0.6]),
      f"evaluate_globals: derived = {evaluated['fixed']['derived']}")
check(hierarchy == {'derived': ['amplitude']}, f'global hierarchy {hierarchy}')
shots = runmanager.expand_globals(sequence_globals, evaluated)
check(len(shots) == 6, f'expand_globals: {len(shots)} shots (3 outer x 2 zip)')
check(all(s['gain'] == {10: 1, 20: 2}[s['offset']] for s in shots), 'zip globals vary together')
_, dims = runmanager.expand_globals(
    sequence_globals, evaluated,
    {'outer amplitude': {'order': 1, 'shuffle': False}, 'zip zip1': {'order': 0, 'shuffle': False}},
    return_dimensions=True)
check(dims.get('zip zip1') == 2 and dims.get('outer amplitude') == 3, f'dimensions {dims}')
check(runmanager.guess_expansion_type([1, 2]) == 'outer' and runmanager.guess_expansion_type(3) == ''
      and runmanager.guess_expansion_type((1, 2)) == '', 'guess_expansion_type: lists are outer, tuples and scalars are not')

# Expansion settings record whether the user chose them. set_expansion records a custom
# setting unless told otherwise, and automatic_expansions keeps custom settings, makes
# lists and ranges outer and zips derived lists with the list they derive from, also
# when the setting of that list is custom
check(runmanager.guess_expansion_type(range(3)) == 'outer', 'guess_expansion_type: ranges are outer')
custom = runmanager.get_custom_expansions(groups)
check(custom['scan'] == {'amplitude': True, 'gain': True, 'offset': True} and custom['fixed']['derived'] is True
      and custom['fixed']['duration'] is False, f'get_custom_expansions {custom}')
runmanager.set_expansion(gf, 'fixed', 'derived', '', custom=False)
check(runmanager.get_expansion_custom(gf, 'fixed', 'derived') is False, 'set_expansion with custom=False')
flat_values = runmanager.flatten_globals(evaluated, evaluated=True)
flat_custom = {name: flag for group in runmanager.get_custom_expansions(groups).values() for name, flag in group.items()}
automatic = runmanager.automatic_expansions(flat_values, hierarchy, expansions, flat_custom)
check(automatic == {'amplitude': 'outer', 'gain': 'zip1', 'offset': 'zip1', 'duration': '', 'use_do': '',
                    'derived': 'amplitude'},
      f'automatic_expansions with a custom outer amplitude: {automatic}')
# An outer global and the zip group named after it are one axis
runmanager.set_expansion(gf, 'fixed', 'derived', 'amplitude', custom=False)
zipped_globals = runmanager.get_globals(groups)
zipped, _, _ = runmanager.evaluate_globals(zipped_globals)
zipped_shots = runmanager.expand_globals(zipped_globals, zipped)
check(len(zipped_shots) == 6 and all(np.isclose(s['derived'], 2 * s['amplitude']) for s in zipped_shots),
      f'outer global zipped with the zip group named after it: {len(zipped_shots)} shots (3 x 2 zip)')
runmanager.set_expansion(gf, 'fixed', 'derived', '', custom=False)
flat_custom['amplitude'] = False
automatic = runmanager.automatic_expansions(flat_values, hierarchy, expansions, flat_custom)
check(automatic['amplitude'] == 'amplitude' and automatic['derived'] == 'amplitude',
      f'automatic_expansions zips a derived list with its source: {automatic}')

runmanager.set_value(gf, 'fixed', 'duration', 'undefined_name + 1')
try:
    runmanager.evaluate_globals(runmanager.get_globals(runmanager.get_all_groups(gf)))
    check(False, 'evaluation error raised for an undefined name')
except Exception as e:
    check('undefined_name' in str(e), f'evaluation error raised: {type(e).__name__}')
runmanager.set_value(gf, 'fixed', 'duration', '1.0')

# Globals that refer to each other in a cycle get an error naming the cycle, and a
# global that refers to one of them gets a NameError; a global referring to another in a
# conditional expression depends on both branches
runmanager.set_value(gf, 'fixed', 'duration', 'use_do + 1')
runmanager.set_value(gf, 'fixed', 'use_do', 'duration > 0')
runmanager.set_value(gf, 'fixed', 'derived', 'amplitude if duration else gain')
evaluated, hierarchy, _ = runmanager.evaluate_globals(
    runmanager.get_globals(runmanager.get_all_groups(gf)), raise_exceptions=False)
cycle_error = evaluated['fixed']['duration']
check(isinstance(cycle_error, ValueError) and 'duration' in str(cycle_error) and 'use_do' in str(cycle_error)
      and evaluated['fixed']['use_do'] is cycle_error,
      f'globals in a cycle hold an error naming the cycle: {cycle_error!r}')
check(isinstance(evaluated['fixed']['derived'], NameError),
      f"global referring to a cycle holds NameError: {evaluated['fixed']['derived']!r}")
check(hierarchy.get('derived') == ['amplitude', 'duration', 'gain'], f'hierarchy of a conditional: {hierarchy}')
runmanager.set_value(gf, 'fixed', 'duration', '1.0')
runmanager.set_value(gf, 'fixed', 'use_do', 'True')
runmanager.set_value(gf, 'fixed', 'derived', 'array(amplitude) * 2')

# A global that fails the expansion check is still in the namespace for the globals
# that refer to it
runmanager.set_value(gf, 'scan', 'amplitude', '5')
evaluated, _, _ = runmanager.evaluate_globals(
    runmanager.get_globals(runmanager.get_all_groups(gf)), raise_exceptions=False)
check(isinstance(evaluated['scan']['amplitude'], runmanager.ExpansionError),
      f"non-iterable outer global holds ExpansionError: {evaluated['scan']['amplitude']!r}")
check(not isinstance(evaluated['fixed']['derived'], Exception) and evaluated['fixed']['derived'] == 10,
      f"global referring to it evaluates: derived = {evaluated['fixed']['derived']!r}")
runmanager.set_value(gf, 'scan', 'amplitude', '[0.1, 0.2, 0.3]')

# A global in a zip group that refers to a global on another axis holds an error naming
# that global; one that refers to a global in its own zip group evaluates
runmanager.set_expansion(gf, 'fixed', 'derived', 'zip2')
evaluated, _, _ = runmanager.evaluate_globals(
    runmanager.get_globals(runmanager.get_all_groups(gf)), raise_exceptions=False)
check(isinstance(evaluated['fixed']['derived'], ValueError) and 'amplitude' in str(evaluated['fixed']['derived']),
      f"zipped global referring to an outer global holds an error: {evaluated['fixed']['derived']!r}")
runmanager.set_value(gf, 'fixed', 'derived', 'array(offset) * 2')
runmanager.set_expansion(gf, 'fixed', 'derived', 'zip1')
evaluated, _, _ = runmanager.evaluate_globals(
    runmanager.get_globals(runmanager.get_all_groups(gf)), raise_exceptions=False)
check(np.array_equal(evaluated['fixed']['derived'], [20, 40]),
      f"zipped global referring to its own zip group evaluates: {evaluated['fixed']['derived']!r}")
runmanager.set_value(gf, 'fixed', 'derived', 'array(amplitude) * 2')
runmanager.set_expansion(gf, 'fixed', 'derived', '')

# Each write of a string to a globals file adds 4 kB to it, which is reclaimed by
# repacking the file once it has grown by 1 MB
for n in range(600):
    runmanager.set_value(gf, 'fixed', 'duration', repr(n + 1.0))
size = os.path.getsize(gf)
check(size < 1.5e6, f'globals file is {size} bytes after 600 writes', known='runmanager #144')
check(runmanager.get_value(gf, 'fixed', 'duration') == '600.0'
      and runmanager.get_units(gf, 'fixed', 'duration') == 's',
      'globals file contents after 600 writes')
leftover = [name for name in os.listdir(work) if name.endswith('.repack')]
check(not leftover, f'no temporary files left after writes: {leftover}')
runmanager.set_value(gf, 'fixed', 'duration', '1.0')

# Diff and tokenizer
d = runmanager.dict_diff({'a': 1, 'b': 2}, {'a': 1, 'b': 3, 'c': 4})
check(set(d) == {'b', 'c'}, f'dict_diff {d}')
tokens = runmanager.remove_comments_and_tokenify('a + 1 # c')
check('c' not in tokens, f'remove_comments_and_tokenify {tokens!r}')
check(runmanager.find_comments('a + 1 # c') == [(5, 9)], f"find_comments {runmanager.find_comments('a + 1 # c')}")
check(isinstance(runmanager.globals_diff_groups(groups, groups), str), 'globals_diff_groups')

# Run files
out = str(work / 'sequence')
attrs, default_folder, prefix = runmanager.new_sequence_details(script, increment_sequence_index=False)
check('sequence_id' in attrs and prefix.endswith('experiment'), f'new_sequence_details prefix {prefix}')
files = list(runmanager.make_run_files(out, sequence_globals, shots, attrs, prefix, shuffle=False))
check(len(files) == 6 and all(os.path.exists(f) for f in files), f'make_run_files wrote {len(files)} files')
sg = runmanager.get_shot_globals(files[1])
check(sg['amplitude'] in (0.1, 0.2, 0.3) and sg['duration'] == 1.0 and bool(sg['use_do']) is True
      and np.allclose(sg['derived'], [0.2, 0.4, 0.6]), f'get_shot_globals {sg}')

# Compilation, with the batch compiler's output streamed to a PULL socket. The socket
# must come from the labscript_utils Context so that it has the labconfig security
# settings.
from labscript_utils.ls_zprocess import Context

ctx = Context.instance()
pull = ctx.socket(zmq.PULL)
stream_port = pull.bind_to_random_port('tcp://127.0.0.1')
stream = []


def drain():
    while True:
        try:
            stream.append(pull.recv_multipart())
        except Exception:
            return


threading.Thread(target=drain, daemon=True).start()

gf2 = str(work / 'constants.h5')
runmanager.new_globals_file(gf2)
runmanager.new_group(gf2, 'g')
for name, value in [('amplitude', '0.5'), ('gain', '2'), ('offset', '1'), ('duration', '0.7'),
                    ('use_do', 'False')]:
    runmanager.new_global(gf2, 'g', name)
    runmanager.set_value(gf2, 'g', name, value)


def wait_for(results, n, timeout=300):
    """Wait for n callbacks, or for the first failure, after which the multishot
    compile stops."""
    t0 = time.time()
    while len(results) < n and False not in results and time.time() - t0 < timeout:
        time.sleep(0.2)
    time.sleep(1)
    return results


# The compile functions run the batch compiler in a child process; the ones that take
# globals files or several run files return before it finishes.
results = []
single = str(work / 'single.h5')
attempt('compile_labscript_with_globals_files_async runs',
        runmanager.compile_labscript_with_globals_files_async, script, [gf2], single,
        stream_port=stream_port, done_callback=results.append)
wait_for(results, 1)
check(results == [True], f'single-shot compile success {results}')
if results == [True]:
    with h5py.File(single, 'r') as f:
        check('dummy' in f['devices'], f"compiled devices {list(f['devices'])}")
        check(float(f['globals'].attrs['amplitude']) == 0.5, 'globals from the globals file')

results = []
attempt('compile_multishot_async runs', runmanager.compile_multishot_async, script, files,
        stream_port=stream_port, done_callback=results.append)
wait_for(results, 6)
check(results == [True] * 6, f'multishot compile results {results}')
if results == [True] * 6:
    with h5py.File(files[0], 'r') as f:
        check(float(f['globals'].attrs['amplitude']) == 0.1 and 'devices' in f,
              'multishot file compiled with its globals')
    with h5py.File(files[5], 'r') as f:
        check(float(f['globals'].attrs['amplitude']) == 0.3, 'last shot has the last outer value')
    attempt('globals_diff_shots on two shots of one sequence', runmanager.globals_diff_shots,
            files[0], files[5])

time.sleep(1)
output = b''.join(m[-1] for m in stream).decode(errors='replace')
check(output.count('runmanager_test experiment compiled') == 7,
      f"compiler output streamed: {output.count('runmanager_test experiment compiled')} of 7 compiles seen")
print(output[-800:])
finish()
