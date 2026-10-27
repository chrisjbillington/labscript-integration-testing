# Load a MOT, cool it in optical molasses, release it and take an absorption image
# after a time of flight. prepare.py appends this to the device definitions of
# connection_table.py to make the experiment script.
from labscript import add_time_marker

COIL_AMPS_PER_VOLT = 2.0
COOLING_AOM_MHZ = 80

t = 0
add_time_marker(t, 'MOT load', verbose=True)
start()
oven_shutter.go_high(t)
zeeman_coils.go_high(t)
push_beam.go_high(t)
mot_shutter.open(t)
repump_shutter.open(t)
mot_coils.constant(t, mot_coil_current / COIL_AMPS_PER_VOLT)
bias_x.constant(t, 0.12)
bias_y.constant(t, -0.08)
bias_z.constant(t, 0.31)
cooling_aom.setfreq(t, COOLING_AOM_MHZ + mot_detuning / 2, units='MHz')
cooling_aom.setamp(t, mot_power)
imaging_aom.setfreq(t, COOLING_AOM_MHZ + imaging_detuning / 2, units='MHz')
imaging_aom.setamp(t, 0)
repump_aom.setfreq(78.5, units='MHz')
repump_aom.setamp(1)
zeeman_aom.setfreq(112, units='MHz')
zeeman_aom.setamp(0.8)
t += mot_load_time

add_time_marker(t, 'Molasses', verbose=True)
oven_shutter.go_low(t)
zeeman_coils.go_low(t)
push_beam.go_low(t)
t += mot_coils.ramp(t, duration=2e-3, initial=mot_coil_current / COIL_AMPS_PER_VOLT,
                    final=0, samplerate=10e3)
cooling_aom.frequency.ramp(t, duration=molasses_time * 1e-3,
                           initial=COOLING_AOM_MHZ + mot_detuning / 2,
                           final=COOLING_AOM_MHZ + molasses_detuning / 2,
                           samplerate=4e3, units='MHz')
cooling_aom.amplitude.ramp(t, duration=molasses_time * 1e-3, initial=mot_power,
                           final=molasses_power, samplerate=4e3)
t += molasses_time * 1e-3

add_time_marker(t, 'Time of flight', verbose=True)
cooling_aom.setamp(t, 0)
mot_shutter.close(t)
repump_shutter.close(t)
imaging_shutter.open(t)
t += tof * 1e-3

add_time_marker(t, 'Image', verbose=True)
imaging_aom.setamp(t, imaging_power)
camera_trigger.go_high(t)
t += exposure_time * 1e-6
imaging_aom.setamp(t, 0)
camera_trigger.go_low(t)
imaging_shutter.close(t)
t += 20e-3
stop(t)
