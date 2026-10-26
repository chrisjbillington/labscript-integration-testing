"""A pulse generator that waits for a trigger before its first instruction. There is no
wait monitor: labscript does not allow a wait at t=0 with one."""

from labscript import start, stop, wait, DigitalOut
from labscript_devices.NarwhalPulseGenerator.labscript_devices import NarwhalPulseGenerator

NarwhalPulseGenerator('pulsegen', serial_number=1234, use_wait_monitor=False)
DigitalOut('shutter', pulsegen.direct_outputs, 'channel 2')

start()
t = wait('go', 0, timeout=1.0)
shutter.go_high(t)
t += 1e-3
shutter.go_low(t)
t += 1e-3
stop(t)
