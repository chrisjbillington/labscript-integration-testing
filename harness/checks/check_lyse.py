"""Read the compiled example shot with the lyse Run API and the dataframe utilities,
and write and read back results."""

import numpy as np

from _common import attempt, check, finish, load_state

import lyse
from lyse.dataframe_utilities import get_dataframe_from_shot, get_dataframe_from_shots

shot = load_state()['example_shot']

# Names that analysis routines read from the lyse module.
check(getattr(lyse, 'spinning_top', None) is False,
      'lyse.spinning_top is False outside the analysis subprocess')
check(lyse.path is None, 'lyse.path is None outside the analysis subprocess')
star = {}
exec('from lyse import *', star)
check('path' in star and 'Run' in star and 'data' in star, 'star import provides path, Run and data')
check('spinning_top' in star, 'star import provides spinning_top')

run = lyse.Run(shot)
run.set_group('harness')
g = run.get_globals()
check(isinstance(g, dict), f'get_globals returns a dict with {len(g)} entries')

run.save_result('answer', 42.0)
run.save_result('flag', True)
run.save_result('label', 'text')
run.save_result_array('array', np.arange(5.0))
check(run.get_result('harness', 'answer') == 42.0, 'save_result and get_result round-trip')
check(run.get_result('harness', 'flag') is True or run.get_result('harness', 'flag') == True,
      'boolean result round-trip')
check(run.get_result('harness', 'label') == 'text', 'string result round-trip')
check(np.array_equal(run.get_result_array('harness', 'array'), np.arange(5.0)),
      'save_result_array and get_result_array round-trip')
results = run.get_results('harness', 'answer', 'flag')
check(results == [42.0, True], f'get_results returns {results}')

df, ok = attempt('get_dataframe_from_shot', get_dataframe_from_shot, shot)
if ok:
    check(len(df) == 1, f'dataframe has {len(df)} row')
    check(('harness', 'answer') in df.columns, f'dataframe columns: {list(df.columns)[:12]}')
    check(float(df[('harness', 'answer')].iloc[0]) == 42.0, 'result value in the dataframe')

df2, ok = attempt('get_dataframe_from_shots', get_dataframe_from_shots, [shot, shot])
if ok:
    check(len(df2) == 2, f'two-shot dataframe has {len(df2)} rows')

ro = lyse.Run(shot, no_write=True)
check(ro.get_result('harness', 'answer') == 42.0, 'no_write Run reads results')
finish()
