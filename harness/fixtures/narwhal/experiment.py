"""A master pulse generator with a clockline, a digital output and a trigger to a
secondary pulse generator, with three waits: one ended by a trigger, one that times out
and one synchronised to the powerline. The clockline has a ramp with a period of an odd
number of cycles, and a ramp that ends at a wait."""

from labscript import start, stop, wait, AnalogOut, ClockLine, DigitalOut, Trigger
from labscript_devices.NarwhalPulseGenerator.labscript_devices import NarwhalPulseGenerator
from labscript_devices.DummyIntermediateDevice.labscript_devices import DummyIntermediateDevice

NarwhalPulseGenerator('pulsegen', serial_number=1234, trigger_out_length=20e-9)
ClockLine('daq_clock', pulsegen.pseudoclock, 'channel 0')
DummyIntermediateDevice('daq', parent_device=daq_clock)
AnalogOut('ao0', daq, 'ao0')
DigitalOut('shutter', pulsegen.direct_outputs, 'channel 2')
Trigger('pulsegen2_trigger', pulsegen.direct_outputs, 'channel 3')
NarwhalPulseGenerator('pulsegen2', serial_number=5678,
                      trigger_device=pulsegen2_trigger, trigger_connection='trigger')
DigitalOut('probe', pulsegen2.direct_outputs, 'channel 7')

t = start()
shutter.go_high(t)
t += 1e-3
# 100 clock ticks with a period of 101 cycles:
ao0.ramp(t, 101e-6, 0, 1, samplerate=1 / 1.01e-6)
t += 101e-6
t += 1e-3
# A ramp that ends at a wait:
ao0.ramp(t, 2e-3, 1, 0, samplerate=1e3)
t += 2e-3
t += wait('loaded', t, timeout=1.0)
probe.go_high(t)
t += 1e-3
t += wait('imaged', t, timeout=0.05)
shutter.go_low(t)
t += 1e-3
t += pulsegen.wait_for_powerline('mains', t)
probe.go_low(t)
t += 1e-3
stop(t)
