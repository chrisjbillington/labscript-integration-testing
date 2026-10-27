from labscript_devices.IMAQdxCamera.labscript_devices import IMAQdxCamera

IMAQdxCamera(
    name='camera',
    parent_device=intermediate_device,
    connection='port0/line1',
    serial_number=0xDEADBEEF,
    orientation='side',
    trigger_duration=0.01,
    mock=True,
)
