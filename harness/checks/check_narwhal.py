"""Compile shots with Narwhal Devices Pulse Generators, check their instruction tables,
run the runviewer parser on them, and run the BLACS worker on a simulated device: a
shot with waits as master and secondary, an abort, a secondary that is never
triggered, and a device with no direct outputs."""

import logging
import sys
import time
from pathlib import Path

import numpy as np

from _common import FIXTURES, SHOTS, attempt, check, finish, labconfig

import labscript_utils.h5_lock  # noqa: F401
import h5py
import runmanager

from qtutils.qt import QtWidgets

app = QtWidgets.QApplication([])

import runviewer.__main__ as rv  # noqa: E402

try:
    from labscript_devices.NarwhalPulseGenerator.driver import CYCLE
except ImportError:
    CYCLE = None
if not check(CYCLE is not None, 'the installed labscript-devices has the NarwhalPulseGenerator package',
             known='labscript-devices narwhal-pulsegen branch'):
    finish()

FIX = FIXTURES / 'narwhal'
sys.path.insert(0, str(FIX))
from narwhal_sim import POWERLINE_WAIT, SimulatedWorker  # noqa: E402

logging.basicConfig(level=logging.INFO)
config = labconfig()
N_CHANNELS = 24


def compile_script(script, run_file):
    results = []
    runmanager.compile_labscript_async(script, run_file, done_callback=results.append)
    return results == [True]


def compile_fixture(name):
    script = str(FIX / f'{name}.py')
    run_file = str(SHOTS / f'narwhal_{name}.h5')
    SHOTS.mkdir(parents=True, exist_ok=True)
    sequence_attrs, _, _ = runmanager.new_sequence_details(
        script, config=config, increment_sequence_index=False)
    runmanager.make_single_run_file(run_file, {}, {}, sequence_attrs, 0, 1)
    ok, _ = attempt(f'{name} compiles', compile_script, script, run_file)
    check(ok is True, f'{name} compile reported success')
    return run_file if ok is True else None


def front_panel(high=()):
    return {f'channel {n}': int(n in high) for n in range(N_CHANNELS)}


def make_worker(device_name, serial_number, hardware_triggers):
    worker = SimulatedWorker.__new__(SimulatedWorker)
    worker.device_name = device_name
    worker.serial_number = serial_number
    worker.hardware_triggers = hardware_triggers
    worker.logger = logging.getLogger(f'narwhal.{device_name}')
    worker.init()
    return worker


def run_to_completion(master, timeout=10.0):
    """Start the run and wait for it as the tab does. Returns whether it finished."""
    master.start_run()
    deadline = time.monotonic() + timeout
    finished = False
    while not finished and time.monotonic() < deadline:
        finished, _ = master.wait_for_run_finished(0.5)
    return finished


# ---- Compile and check the instruction tables

run_file = compile_fixture('experiment')
if run_file is None:
    finish()

with h5py.File(run_file, 'r') as f:
    master_program = f['devices/pulsegen/PULSE_PROGRAM'][:]
    master_attrs = dict(f['devices/pulsegen'].attrs)
    secondary_program = f['devices/pulsegen2/PULSE_PROGRAM'][:]
    secondary_attrs = dict(f['devices/pulsegen2'].attrs)
    waits = f['waits'][:]

print(f'master program ({len(master_program)} instructions):')
for row in master_program:
    print('  ', row)
print(f'secondary program ({len(secondary_program)} instructions):')
for row in secondary_program:
    print('  ', row)

check(master_attrs['is_master_pseudoclock'] and not secondary_attrs['is_master_pseudoclock'],
      'is_master_pseudoclock is set for the master and not the secondary')
check(master_attrs['used_channels'] == 0b1101, f"master used_channels {master_attrs['used_channels']:#b}")
check(secondary_attrs['used_channels'] == 1 << 7, f"secondary used_channels {secondary_attrs['used_channels']:#b}")
check(master_attrs['trigger_out_length'] == 2, f"trigger_out_length {master_attrs['trigger_out_length']} cycles")

# The final clock tick, at the stop time, lasts one period of the slowest clock limit
# among the pseudoclock and the devices on its clocklines: 1 us for the master, whose
# clockline has a DummyIntermediateDevice, and one cycle for the secondary.
for name, program, attrs, final_tick in [('master', master_program, master_attrs, 100),
                                         ('secondary', secondary_program, secondary_attrs, 1)]:
    duration = program['duration'].astype(np.int64)
    # A looping instruction repeats itself and the instruction before it.
    loops = program['goto_counter'] > 0
    total = duration.sum() + (duration[loops] + duration[np.flatnonzero(loops) - 1]) @ program['goto_counter'][loops].astype(np.int64)
    stop_cycles = int(round(attrs['stop_time'] / CYCLE))
    check(total == stop_cycles + final_tick,
          f'{name}: instructions last {total} cycles, stop time is {stop_cycles} cycles plus a final tick of {final_tick}')
    check((program['goto_address'][loops] == np.flatnonzero(loops) - 1).all(),
          f'{name}: every loop jumps back to the preceding instruction')
    n_waits = int(program['stop_and_wait'].sum())
    check(n_waits == len(waits), f'{name}: {n_waits} instructions wait, the shot has {len(waits)} waits')
    check(not (program['stop_and_wait'] & loops).any(), f'{name}: no looping instruction waits')
    check((duration >= 1).all(), f'{name}: every instruction lasts at least one cycle')

# The ramp with a period of 101 cycles: high 50, low 51, 100 ticks in all.
high = master_program['duration'] == 50
low = np.concatenate([[False], high[:-1]]) & (master_program['duration'] == 51)
ticks = (master_program['goto_counter'][low] + 1).sum()
check(low.sum() >= 1 and ticks == 100, f'odd period: {low.sum()} tick pairs of 50 + 51 cycles for {ticks} ticks')
# The wait after the ramp follows a tick pair that was split from its loop:
wait_rows = np.flatnonzero(master_program['stop_and_wait'])
first_wait = wait_rows[0]
check(master_program['goto_counter'][first_wait] == 0
      and master_program['goto_counter'][first_wait - 2] >= 0
      and master_program['duration'][first_wait] == master_program['duration'][first_wait - 2],
      f'the first wait is on instruction {first_wait}, a copy of the loop before it')
sync = np.flatnonzero(master_program['powerline_sync'])
check(len(sync) == 1 and sync[0] == wait_rows[2] + 1,
      f'powerline_sync on instruction {sync.tolist()}, after the third wait at {wait_rows[2]}')
check(not secondary_program['powerline_sync'].any(), 'the secondary has no powerline_sync')

# ---- Runviewer

shot, ok = attempt('runviewer loads the shot', rv.Shot, run_file)
if ok:
    traces = shot.traces
    print('traces:', sorted(traces))
    for name in ['shutter', 'pulsegen2_trigger', 'daq_clock', 'probe']:
        check(name in traces, f'runviewer has a trace for {name}')
    wait_times = {w['label'].decode(): w['time'] for w in waits}
    if 'shutter' in traces:
        t, v = traces['shutter']
        rises = t[np.flatnonzero(np.diff(v, prepend=0) > 0)]
        falls = t[np.flatnonzero(np.diff(v, prepend=0) < 0)]
        check(len(rises) == 1 and rises[0] < 1e-5, f'shutter rises once, at {rises}')
        check(len(falls) == 1 and 0 <= falls[0] - wait_times['imaged'] < 2e-5,
              f"shutter falls once, at {falls}, {falls - wait_times['imaged']} after the 'imaged' wait")
    if 'probe' in traces:
        t, v = traces['probe']
        rises = t[np.flatnonzero(np.diff(v, prepend=0) > 0)]
        check(len(rises) == 1 and 0 <= rises[0] - wait_times['loaded'] < 2e-5,
              f"probe (on the secondary) rises once, at {rises}, {rises - wait_times['loaded']} after the 'loaded' wait")
    if 'daq_clock' in traces:
        t, v = traces['daq_clock']
        n_ticks = int((np.diff(v, prepend=0) > 0).sum())
        # 100 ticks of the odd-period ramp and 1 at its end, 2 of the second ramp,
        # whose end is the first wait, 1 at the start and after each wait, 1 at the
        # stop time:
        check(n_ticks == 100 + 1 + 2 + 4 + 1, f'daq_clock has {n_ticks} ticks')

# ---- The worker on simulated devices

# Pauses: the start, then the waits 'loaded' (hardware trigger after 20 ms), 'imaged'
# (no trigger: times out after 50 ms) and 'mains' (powerline).
master = make_worker('pulsegen', 1234, [None, 0.02, None, None])
secondary = make_worker('pulsegen2', 5678, [0.001, 0.02, 0.06, 0.02])
info = master.get_device_info()
check(info['serial_number'] == 1234 and info['firmware_version'] == '1.002', f'device info {info}')

master.program_manual(front_panel(high=[5, 6]))
remote = master.check_remote_values()
check(remote == front_panel(high=[5, 6]), 'program_manual sets the channels and check_remote_values reads them back')
state, powerline, run_time, notifications = master.get_status()
check(not state.running and powerline.locked and notifications == [], 'get_status reports an idle device')

final = master.transition_to_buffered('pulsegen', run_file, front_panel(high=[5, 6]), True)
check(final == front_panel(high=[5, 6]),
      f'final values: unused channels 5 and 6 keep the front panel values, the rest are low: {final}')
secondary_final = secondary.transition_to_buffered('pulsegen2', run_file, front_panel(), True)
check(secondary_final == front_panel(), f'secondary final values {secondary_final}')
ram = master.port.device.ram
check(all((ram[a].state >> 5) & 0b11 == 0b11 for a in ram), 'unused channels are high in every instruction written')
check(ram[0].notify is False and ram[first_wait].notify and ram[first_wait + 1].notify,
      'the instruction that waits and the one after it notify')

t0 = time.monotonic()
check(run_to_completion(master), f'the run finished in {time.monotonic() - t0:.2f} s')
check(master.transition_to_manual() is True, 'master transition_to_manual')
check(secondary.transition_to_manual() is True, 'secondary transition_to_manual')
with h5py.File(run_file, 'r') as f:
    measured = f['/data/waits'][:]
print(measured)
check([w['label'].decode() for w in measured] == ['loaded', 'imaged', 'mains'], 'waits recorded in order')
check(measured['timed_out'].tolist() == [False, True, False], f"timed_out {measured['timed_out'].tolist()}")
# The worker times the wait timeout with time.monotonic(), which has a resolution of
# 15.6 ms on Windows before Python 3.13, so the timed-out wait may be shorter than its
# timeout by that much. The other two waits are timed by the simulator's threads.
check(0.018 <= measured['duration'][0] < 0.1, f"'loaded' lasted {measured['duration'][0]:.4f} s (trigger after 0.02 s)")
check(0.034 <= measured['duration'][1] < 0.2, f"'imaged' lasted {measured['duration'][1]:.4f} s (timeout 0.05 s)")
check(POWERLINE_WAIT - 0.002 <= measured['duration'][2] < 0.1, f"'mains' lasted {measured['duration'][2]:.4f} s (powerline after {POWERLINE_WAIT} s)")
check(master.check_remote_values() == front_panel(high=[5, 6]), 'the device ends in the final state')

# Abort during the run:
master.transition_to_buffered('pulsegen', run_file, front_panel(), True)
master.start_run()
time.sleep(0.01)
check(master.abort_buffered() is True, 'abort_buffered')
state = master.device.get_state()
check(not state.running and state.current_address == 0 and state.accept_hardware_trigger == 'never',
      f'after the abort the device is reset: running {state.running}, address {state.current_address}, accept {state.accept_hardware_trigger}')
master.program_manual(front_panel())
check(master.check_remote_values() == front_panel(), 'program_manual after the abort')

# A secondary that is never triggered:
untriggered = make_worker('pulsegen2', 5678, [None])
untriggered.transition_to_buffered('pulsegen2', run_file, front_panel(), True)
try:
    untriggered.transition_to_manual()
except RuntimeError as e:
    check('may not have received its trigger' in str(e), f'untriggered secondary: {e}')
else:
    check(False, 'untriggered secondary: transition_to_manual did not raise')

for worker in [master, secondary, untriggered]:
    worker.shutdown()

# ---- A wait at t=0

run_file = compile_fixture('wait_at_start')
if run_file is not None:
    with h5py.File(run_file, 'r') as f:
        program = f['devices/pulsegen/PULSE_PROGRAM'][:]
        attrs = dict(f['devices/pulsegen'].attrs)
    print('wait_at_start program:')
    for row in program:
        print('  ', row)
    check(attrs['wait_at_start'] and program['stop_and_wait'][0] and program['duration'][0] == 1,
          'the program begins with a one-cycle instruction that waits')
    worker = make_worker('pulsegen', 1234, [None, 0.02])
    worker.transition_to_buffered('pulsegen', run_file, front_panel(high=[9]), True)
    check(worker.port.device.ram[0].state == 1 << 9,
          'the waiting instruction holds the front panel state')
    check(worker.port.device.ram[1].state == 1 << 9 and worker.port.device.ram[2].state == (1 << 9) | (1 << 2),
          'the next instructions hold the front panel state on channel 9 and the shutter on channel 2')
    check(run_to_completion(worker), 'the run finished after the trigger that ends the wait')
    check(worker.transition_to_manual() is True, 'transition_to_manual')
    worker.shutdown()

# ---- A pulse generator with no direct outputs

run_file = compile_fixture('no_direct_outputs')
if run_file is not None:
    with h5py.File(run_file, 'r') as f:
        program = f['devices/pulsegen/PULSE_PROGRAM'][:]
        attrs = dict(f['devices/pulsegen'].attrs)
    duration = program['duration'].astype(np.int64)
    loops = program['goto_counter'] > 0
    total = duration.sum() + (duration[loops] + duration[np.flatnonzero(loops) - 1]) @ program['goto_counter'][loops].astype(np.int64)
    stop_cycles = int(round(attrs['stop_time'] / CYCLE))
    check(attrs['used_channels'] == 1 and total == stop_cycles + 100,
          f'no direct outputs: instructions last {total} cycles, stop time is {stop_cycles} cycles plus a final tick of 100')

finish()
