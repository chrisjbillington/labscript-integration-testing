from labscript import start, stop, AnalogOut, DigitalOut
from labscript_devices.DummyPseudoclock.labscript_devices import DummyPseudoclock
from labscript_devices.DummyIntermediateDevice.labscript_devices import DummyIntermediateDevice

DummyPseudoclock('pseudoclock')
DummyIntermediateDevice('dummy', parent_device=pseudoclock.clockline)
AnalogOut('ao0', dummy, 'ao0')
DigitalOut('do0', dummy, 'do0')

if __name__ == '__main__':
    start()
    stop(1)
