from labscript import start, stop, AnalogOut, DigitalOut
from labscript_devices.DummyPseudoclock.labscript_devices import DummyPseudoclock
from labscript_devices.DummyIntermediateDevice.labscript_devices import DummyIntermediateDevice

DummyPseudoclock('pseudoclock')
DummyIntermediateDevice('dummy', parent_device=pseudoclock.clockline)
AnalogOut('ao0', dummy, 'ao0')
DigitalOut('do0', dummy, 'do0')

start()
ao0.constant(t=0, value=amplitude)
ao0.ramp(t=0.1, duration=duration / 2, initial=amplitude, final=amplitude * gain, samplerate=1e3)
if use_do:
    do0.go_high(t=0.2)
stop(duration)
print('runmanager_test experiment compiled')
