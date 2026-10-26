"""A pulse generator with a clockline and no direct outputs."""

from labscript import start, stop, AnalogOut, ClockLine
from labscript_devices.NarwhalPulseGenerator.labscript_devices import NarwhalPulseGenerator
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice

NarwhalPulseGenerator('pulsegen', serial_number=1234)
ClockLine('daq_clock', pulsegen.pseudoclock, 'channel 0')
DummyIntermediateDevice('daq', parent_device=daq_clock)
AnalogOut('ao0', daq, 'ao0')

start()
ao0.ramp(1e-3, 1e-3, 0, 1, samplerate=1e5)
stop(3e-3)
