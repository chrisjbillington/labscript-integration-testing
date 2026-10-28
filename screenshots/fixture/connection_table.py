from labscript import AnalogOut, ClockLine, DDS, DigitalOut, Shutter, StaticDDS, start, stop
from labscript_devices.NI_DAQmx.models import NI_PCI_6733
from labscript_devices.NovaTechDDS9M.labscript_devices import NovaTechDDS9M
from labscript_devices.PulseBlasterUSB.labscript_devices import PulseBlasterUSB

PulseBlasterUSB(name='pulseblaster_0', board_number=0)
ClockLine(name='ni_clock', pseudoclock=pulseblaster_0.pseudoclock, connection='flag 0')
ClockLine(name='novatech_clock', pseudoclock=pulseblaster_0.pseudoclock, connection='flag 1')

Shutter(name='mot_shutter', parent_device=pulseblaster_0.direct_outputs,
        connection='flag 2', delay=(3e-3, 2e-3))
Shutter(name='repump_shutter', parent_device=pulseblaster_0.direct_outputs,
        connection='flag 3', delay=(3e-3, 2e-3))
Shutter(name='imaging_shutter', parent_device=pulseblaster_0.direct_outputs,
        connection='flag 4', delay=(3e-3, 2e-3))
DigitalOut(name='camera_trigger', parent_device=pulseblaster_0.direct_outputs,
           connection='flag 5')

NI_PCI_6733(name='ni_6733', parent_device=ni_clock, clock_terminal='/Dev1/PFI0',
             MAX_name='Dev1')
AnalogOut(name='mot_coils', parent_device=ni_6733, connection='ao0')
AnalogOut(name='bias_x', parent_device=ni_6733, connection='ao1')
AnalogOut(name='bias_y', parent_device=ni_6733, connection='ao2')
AnalogOut(name='bias_z', parent_device=ni_6733, connection='ao3')
DigitalOut(name='oven_shutter', parent_device=ni_6733, connection='port0/line0')
DigitalOut(name='zeeman_coils', parent_device=ni_6733, connection='port0/line1')
DigitalOut(name='push_beam', parent_device=ni_6733, connection='port0/line2')
DigitalOut(name='oven_heater', parent_device=ni_6733, connection='port0/line3')
DigitalOut(name='mot_aom_switch', parent_device=ni_6733, connection='port0/line4',
           inverted=True)
DigitalOut(name='repump_aom_switch', parent_device=ni_6733, connection='port0/line5',
           inverted=True)
DigitalOut(name='probe_aom_switch', parent_device=ni_6733, connection='port0/line6',
           inverted=True)
DigitalOut(name='push_aom_switch', parent_device=ni_6733, connection='port0/line7',
           inverted=True)

NovaTechDDS9M(name='novatech', parent_device=novatech_clock, com_port='COM4')
DDS(name='cooling_aom', parent_device=novatech, connection='channel 0')
DDS(name='imaging_aom', parent_device=novatech, connection='channel 1')
StaticDDS(name='repump_aom', parent_device=novatech, connection='channel 2')
StaticDDS(name='zeeman_aom', parent_device=novatech, connection='channel 3')


if __name__ == '__main__':
    start()
    stop(1)
