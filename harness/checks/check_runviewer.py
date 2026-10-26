"""Load the compiled example shot with runviewer's Shot class, which runs the runviewer
parser of every device that has one."""

import logging

import numpy as np

from _common import check, finish, load_state

from qtutils.qt import QtWidgets

app = QtWidgets.QApplication([])

import runviewer.__main__ as rv  # noqa: E402
from labscript_utils import device_registry  # noqa: E402
from labscript_utils.connections import ConnectionTable  # noqa: E402

shot_path = load_state()['example_shot']


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


capture = Capture()
logging.getLogger('runviewer').addHandler(capture)
logging.getLogger('runviewer').setLevel(logging.INFO)

# Devices with a registered parser must load; devices without one are logged as failed
# by runviewer and that is its normal behaviour.
table = ConnectionTable(shot_path)
with_parser = []
without_parser = []
for name, device in table.table.items():
    try:
        device_registry.get_runviewer_parser(device.device_class)
        with_parser.append(name)
    except Exception:
        without_parser.append(name)
print('devices with a runviewer parser:', with_parser)
print('devices without:', without_parser)
check('pseudoclock' in with_parser, 'DummyPseudoclock has a runviewer parser')

shot = rv.Shot(shot_path)
check(shot.master_pseudoclock_name == 'pseudoclock', f'master pseudoclock {shot.master_pseudoclock_name}')
traces = shot.traces
failed = [m for m in capture.records if m.startswith('Failed to load device')]
for name in with_parser:
    check(not any(m.startswith(f'Failed to load device {name}') for m in failed),
          f'parser for {name} ran without error')
for m in failed:
    print('runviewer log:', m.splitlines()[0])

# The final clock tick, at stop_time, is one period of the slowest clock limit among the
# pseudoclock and the devices on its clocklines, so a trace ends at most that long after
# stop_time.
from labscript_devices.DummyPseudoclock.labscript_devices import DummyPseudoclock  # noqa: E402
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice  # noqa: E402

final_tick = 1 / min(DummyPseudoclock.clock_limit, DummyIntermediateDevice.clock_limit)
print(f'final tick {final_tick:.3g} s')

check(len(traces) >= 1, f'{len(traces)} traces: {sorted(traces)}')
for name, (times, values) in traces.items():
    check(len(times) > 0 and len(times) == len(values), f'trace {name} has {len(times)} points')
    check(np.all(np.diff(times) >= 0), f'trace {name} times are monotonic')
    check(times[0] >= 0 and times[-1] <= shot.stop_time + final_tick,
          f'trace {name} spans {times[0]:.6g} to {times[-1]:.6g} s of {shot.stop_time} s')

# The example experiment sets digital_out high from 1 s to 1.75 s and ramps analog_out
# from 0 V to 1 V between 1.5 s and 1.75 s.
if check('intermediate_device' in with_parser, 'DummyIntermediateDevice has a runviewer parser'):
    def value_at(name, t):
        times, values = traces[name]
        return values[np.searchsorted(times, t, side='right') - 1]

    for t, expected in [(0.5, 0), (1.25, 1), (2.0, 0)]:
        value = value_at('digital_out', t)
        check(value == expected, f'digital_out is {value} at {t} s')
    for t, expected in [(1.25, 0.0), (1.625, 0.5), (2.0, 1.0)]:
        value = value_at('analog_out', t)
        check(abs(value - expected) < 0.01, f'analog_out is {value:.4g} V at {t} s')

markers = shot.markers
check(len(markers) == 4, f'{len(markers)} markers: {sorted(markers)}')
labels = {m['label'].decode() if isinstance(m['label'], bytes) else str(m['label'])
          for m in markers.values()}
check('Start' in labels and 'End' in labels, f'marker labels {sorted(labels)}')
check(len(shot.channels) == len(traces), f'{len(shot.channels)} channels')
finish()
