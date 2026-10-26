from labscript_devices.FunctionRunner.labscript_devices import FunctionRunner

FunctionRunner(name='function_runner')


def record_call(shot_context, t, label):
    """Record in the shot file that the start and stop functions ran"""
    if t == 'start':
        shot_context.started = label
        return
    import labscript_utils.h5_lock  # noqa: F401
    import h5py

    with h5py.File(shot_context.h5_file, 'r+') as f:
        group = f.require_group(f'data/{shot_context.device_name}')
        group.attrs['start'] = shot_context.started
        group.attrs['stop'] = label


function_runner.add_function('start', record_call, 'start function ran')
function_runner.add_function('stop', record_call, label='stop function ran')
