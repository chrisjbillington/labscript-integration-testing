"""Cameras for the cameras step: the mock camera of each camera package, a DummyCamera, a
GenICamCamera with the simulated producer that the genicam package ships, and an
IMAQdxCamera with serial number 0x1234ABCD, which the stub NI-IMAQdx library has. The
DummyCamera and GenICamCamera are left out if the installed labscript-devices or genicam
does not have them."""

import os

from labscript import start, stop
from labscript_devices.DummyPseudoclock.labscript_devices import DummyPseudoclock
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice
from labscript_devices.IMAQdxCamera.labscript_devices import IMAQdxCamera
from labscript_devices.PylonCamera.labscript_devices import PylonCamera
from labscript_devices.SpinnakerCamera.labscript_devices import SpinnakerCamera
from labscript_devices.FlyCapture2Camera.labscript_devices import FlyCapture2Camera
from labscript_devices.AndorSolis.labscript_devices import AndorSolis
from labscript_devices.ThorlabsTSICamera.labscript_devices import ThorlabsTSICamera

try:
    from labscript_devices.DummyCamera.labscript_devices import DummyCamera
except ImportError:
    DummyCamera = None
try:
    from labscript_devices.GenICamCamera.labscript_devices import GenICamCamera
    import genicam
except ImportError:
    GenICamCamera = None

DummyPseudoclock('pseudoclock')
DummyIntermediateDevice('intermediate_device', parent_device=pseudoclock.clockline)

MOCK_CAMERAS = {
    'imaqdx_mock': IMAQdxCamera,
    'pylon_mock': PylonCamera,
    'spinnaker_mock': SpinnakerCamera,
    'flycapture2_mock': FlyCapture2Camera,
    'andor_mock': AndorSolis,
    'thorlabs_mock': ThorlabsTSICamera,
}
cameras = []
for name, cls in MOCK_CAMERAS.items():
    cameras.append(
        cls(
            name,
            parent_device=intermediate_device,
            connection=f'port0/line{len(cameras)}',
            serial_number=12345,
            trigger_duration=0.01,
            mock=True,
        )
    )

cameras.append(
    IMAQdxCamera(
        'imaqdx_stub',
        parent_device=intermediate_device,
        connection=f'port0/line{len(cameras)}',
        serial_number='1234ABCD',
        orientation='stub',
        trigger_duration=0.01,
        camera_attributes={
            'CameraAttributes::ImageFormatControl::Width': 16,
            'CameraAttributes::ImageFormatControl::Height': 8,
            'CameraAttributes::ImageFormatControl::OffsetX': -3,
            'CameraAttributes::ImageFormatControl::PixelFormat': 'Mono16',
            'CameraAttributes::ImageFormatControl::ReverseX': True,
            'CameraAttributes::AcquisitionControl::ExposureTime': 250.5,
            'CameraAttributes::AcquisitionControl::TriggerMode': 'On',
            'CameraAttributes::DeviceControl::DeviceUserID': 'harness',
        },
        manual_mode_camera_attributes={
            'CameraAttributes::AcquisitionControl::TriggerMode': 'Off'
        },
        saved_attribute_visibility_level='advanced',
    )
)

if DummyCamera is not None:
    dummy = DummyCamera(
        'dummy',
        parent_device=intermediate_device,
        connection=f'port0/line{len(cameras)}',
        pixel_size=[2.0, 2.0],
        magnification=2.0,
        trigger_duration=0.01,
        camera_attributes={'Width': 8, 'Height': 6, 'PixelFormat': 'Mono12'},
    )

if GenICamCamera is not None:
    cameras.append(
        GenICamCamera(
            'genicam',
            parent_device=intermediate_device,
            connection=f'port0/line{len(cameras) + 1}',
            serial_number='0',
            cti_file=os.path.join(os.path.dirname(genicam.__file__), 'viky.cti'),
            trigger_duration=0.01,
            camera_attributes={'PixelFormat': 'Mono8', 'Width': 120, 'Height': 100},
        )
    )


def gradient(X, Y, offset):
    return offset + 10 * X + 100 * Y


start()
for camera in cameras:
    camera.expose(0.1, 'harness', 'first')
    camera.expose(0.2, 'harness', 'second')
if DummyCamera is not None:
    # Out of time order, so that the images are sorted by time
    dummy.expose(0.3, 'harness', 'saturated', function=lambda X, Y: 1e6 + X)
    dummy.expose(0.1, 'harness', 'gradient', function=gradient, offset=1000.5)
    dummy.expose(0.2, 'harness', 'zero')
stop(1)
