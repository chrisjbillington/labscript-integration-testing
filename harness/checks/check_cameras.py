"""Compile a shot with the cameras of fixtures/cameras/experiment.py and run their BLACS
workers in this process: a shot, whose images are saved to the shot file, a snap, the
attributes text and continuous acquisition. The mock camera of each camera package
returns 500 x 500 images. The DummyCamera's images are the values of its functions. The
GenICamCamera runs with the simulated GenTL producer of the genicam package, if harvesters
is installed. On Linux, the IMAQdxCamera without mock runs in a second process with stub
NI-IMAQdx and NI Vision libraries built from fixtures/cameras/imaqdx_stub, which check
the ctypes declarations, the attribute types and that every allocation is disposed."""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from _common import FIXTURES, SHOTS, WORK, attempt, check, finish, labconfig

import labscript_utils.h5_lock  # noqa: F401
import h5py
import labscript_utils.properties
import runmanager
from labscript_utils.ls_zprocess import ZMQServer

FIX = FIXTURES / 'cameras'
SHOT = SHOTS / 'cameras.h5'
STUB_DIR = WORK / 'imaqdx_stub'
STUB_SERIAL_NUMBER = 0x1234ABCD
MOCK_CAMERAS = {
    'imaqdx_mock': 'IMAQdxCamera',
    'pylon_mock': 'PylonCamera',
    'spinnaker_mock': 'SpinnakerCamera',
    'flycapture2_mock': 'FlyCapture2Camera',
    'andor_mock': 'AndorSolis',
    'thorlabs_mock': 'ThorlabsTSICamera',
}
WORKERS = {
    'IMAQdxCamera': 'IMAQdxCameraWorker',
    'PylonCamera': 'PylonCameraWorker',
    'SpinnakerCamera': 'SpinnakerCameraWorker',
    'FlyCapture2Camera': 'FlyCapture2CameraWorker',
    'AndorSolis': 'AndorSolisWorker',
    'ThorlabsTSICamera': 'ThorlabsTSICameraWorker',
    'DummyCamera': 'DummyCameraWorker',
    'GenICamCamera': 'GenICamCameraWorker',
}


class ImageReceiver(ZMQServer):
    """Receives the images that a worker sends to its tab"""

    def __init__(self):
        ZMQServer.__init__(self, port=None, dtype='multipart')
        self.images = []

    def handler(self, data):
        metadata = json.loads(data[0])
        image = np.frombuffer(memoryview(data[1]), dtype=metadata['dtype'])
        self.images.append(image.reshape(metadata['shape']).copy())
        return [b'ok']


def make_worker(name, receiver):
    """Instantiate the camera's worker in this process with the arguments that its BLACS
    tab gives it, and run its init()"""
    with h5py.File(SHOT, 'r') as f:
        properties = labscript_utils.properties.get(f, name, 'connection_table_properties')
        device_properties = labscript_utils.properties.get(f, name, 'device_properties')
        row = f['connection table'][list(f['connection table']['name']).index(name.encode())]
    device_class = row['class'].decode()
    module = __import__(f'labscript_devices.{device_class}.blacs_workers',
                        fromlist=[WORKERS[device_class]])
    worker_class = getattr(module, WORKERS[device_class])
    worker = worker_class.__new__(worker_class)
    worker.device_name = name
    worker.parent_host = 'localhost'
    worker.serial_number = properties['serial_number']
    worker.orientation = properties['orientation']
    worker.camera_attributes = device_properties['camera_attributes']
    worker.manual_mode_camera_attributes = properties['manual_mode_camera_attributes']
    worker.mock = properties['mock']
    worker.image_receiver_port = receiver.port
    if 'cti_file' in properties:
        worker.cti_file = properties['cti_file']
    worker.init()
    return worker


def wait_for(condition, timeout=10):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if condition():
            return True
        time.sleep(0.05)
    return False


def run_worker(name, receiver):
    """Run the camera's worker through a shot, a snap, the attributes text and continuous
    acquisition. Return the saved images, as {frametype: array}, and the attributes of the
    image group, or None if the worker failed."""
    worker, ok = attempt(f'{name}: the worker starts', make_worker, name, receiver)
    if not ok:
        return None
    try:
        _, ok = attempt(f'{name}: transition_to_buffered', worker.transition_to_buffered,
                        name, str(SHOT), {}, True)
        if ok:
            attempt(f'{name}: transition_to_manual', worker.transition_to_manual)
        n = len(receiver.images)
        attempt(f'{name}: snap', worker.snap)
        check(len(receiver.images) == n + 1, f'{name}: the snapped image is sent to the tab')
        text, _ = attempt(f'{name}: get_attributes_as_text', worker.get_attributes_as_text,
                          'simple')
        print(text)
        n = len(receiver.images)
        _, ok = attempt(f'{name}: start_continuous', worker.start_continuous, None)
        if ok:
            check(wait_for(lambda: len(receiver.images) >= n + 3),
                  f'{name}: continuous acquisition sends images to the tab')
            attempt(f'{name}: stop_continuous', worker.stop_continuous)
    finally:
        attempt(f'{name}: shutdown', worker.shutdown)
    with h5py.File(SHOT, 'r') as f:
        orientation = worker.orientation or name
        group = f.get(f'images/{orientation}')
        if not check(group is not None, f'{name}: images/{orientation} exists'):
            return None
        check(group.attrs.get('camera') == name and not group.attrs['failed_shot'],
              f'{name}: images/{orientation} has camera {name!r} and failed_shot false')
        images = {frametype: dataset[:] for frametype, dataset in group['harness'].items()}
        for frametype, image in images.items():
            check(image.dtype == np.uint16, f'{name}: {frametype} image is uint16')
        return images, dict(group.attrs)


def pylon_mock_fixed():
    """Whether the PylonCamera worker gets the attributes of the mock camera"""
    import inspect
    from labscript_devices.PylonCamera.blacs_workers import PylonCameraWorker

    return 'self.mock' in inspect.getsource(PylonCameraWorker.get_attributes_as_dict)


def compile_shot():
    sequence_attrs, _, _ = runmanager.new_sequence_details(
        str(FIX / 'experiment.py'), config=labconfig(), increment_sequence_index=False)
    runmanager.make_single_run_file(str(SHOT), {}, {}, sequence_attrs, 0, 1)
    results = []
    runmanager.compile_labscript_async(str(FIX / 'experiment.py'), str(SHOT),
                                       done_callback=results.append)
    return results == [True]


def check_dummy(receiver):
    with h5py.File(SHOT, 'r') as f:
        present = 'dummy' in f['devices']
    if not check(present, 'the installed labscript-devices has DummyCamera',
                 known='labscript-devices dummy-camera branch'):
        return
    result = run_worker('dummy', receiver)
    if result is None:
        return
    images, _ = result
    # The pixels are 2 um, magnified by 2, so X and Y are the pixel coordinates in um
    # from the centre of the image:
    X, Y = np.meshgrid(np.arange(8) - 3.5, np.arange(6) - 2.5)
    expected = {
        'gradient': np.floor(1000.5 + 10 * X + 100 * Y),
        'zero': np.zeros((6, 8)),
        'saturated': np.full((6, 8), 4095),
    }
    for frametype, image in expected.items():
        check(frametype in images and np.array_equal(images[frametype], image),
              f'dummy: the {frametype} image is the value of its function')


def check_genicam(receiver):
    try:
        import harvesters  # noqa: F401
    except ImportError:
        print('harvesters is not installed, which has no genicam wheel for this Python')
        return
    with h5py.File(SHOT, 'r') as f:
        present = 'genicam' in f['devices']
    if not check(present, 'the installed labscript-devices has GenICamCamera',
                 known='labscript-devices genicam-camera branch'):
        return
    result = run_worker('genicam', receiver)
    if result is None:
        return
    images, attrs = result
    check(set(images) == {'first', 'second'}
          and all(image.shape == (100, 120) for image in images.values()),
          f'genicam: two 100 x 120 images: {[i.shape for i in images.values()]}')
    check(attrs.get('Width') == 120 and attrs.get('PixelFormat') == 'Mono8',
          f'genicam: the saved attributes have Width 120 and PixelFormat Mono8: {attrs}')


def build_imaqdx_stub():
    """Build the stub libraries, and return whether they were built"""
    STUB_DIR.mkdir(parents=True, exist_ok=True)
    source = FIX / 'imaqdx_stub'
    commands = [
        ['cc', '-Wall', '-O2', '-shared', '-fPIC', '-o', STUB_DIR / 'libnivision.so',
         source / 'nivision.c'],
        ['cc', '-Wall', '-O2', '-shared', '-fPIC', '-o', STUB_DIR / 'libniimaqdx.so',
         source / 'niimaqdx.c', f'-L{STUB_DIR}', '-lnivision'],
    ]
    for command in commands:
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True)
        print(result.stdout + result.stderr)
        if result.returncode:
            return False
    return True


def check_imaqdx_stub(receiver):
    """Run in a process with the stub libraries on LD_LIBRARY_PATH"""
    nivision = ctypes.CDLL('libnivision.so')
    try:
        from labscript_devices.IMAQdxCamera import imaqdx
    except ImportError:
        imaqdx = None
    if not check(imaqdx is not None, 'the installed labscript-devices has the imaqdx module',
                 known='labscript-devices imaqdx-ctypes branch'):
        return
    result = run_worker('imaqdx_stub', receiver)
    check(nivision.stub_live_allocations() == 0,
          f'imaqdx_stub: every NI Vision allocation is disposed '
          f'({nivision.stub_live_allocations()} not disposed)')
    if result is None:
        return
    images, attrs = result
    x, y = np.meshgrid(np.arange(16), np.arange(8))
    for n, frametype in enumerate(['first', 'second']):
        check(frametype in images and np.array_equal(images[frametype], 10000 * n + 100 * y + x),
              f'imaqdx_stub: the {frametype} image is frame {n} of the stub camera')
    prefix = 'CameraAttributes::'
    expected = {
        'ImageFormatControl::Width': 16,
        'ImageFormatControl::OffsetX': -3,
        'ImageFormatControl::PixelFormat': 'Mono16',
        'ImageFormatControl::ReverseX': True,
        'AcquisitionControl::ExposureTime': 250.5,
        'AcquisitionControl::TriggerMode': 'On',
        'DeviceControl::DeviceUserID': 'harness',
    }
    saved = {name[len(prefix):]: attrs.get(name) for name in attrs if name.startswith(prefix)}
    types = {bool: (bool, np.bool_), int: np.integer, float: np.floating, str: str}
    for name, value in expected.items():
        check(saved.get(name) == value and isinstance(saved.get(name), types[type(value)]),
              f'imaqdx_stub: the saved attribute {name} is {value!r}: {saved.get(name)!r}')
    check('DeviceControl::DeviceReset' not in saved and 'DeviceControl::DeviceModelName' not in saved,
          'imaqdx_stub: unreadable and read-only attributes are not saved')

    # Errors from the libraries:
    worker = make_worker('imaqdx_stub', receiver)
    try:
        try:
            worker.camera.set_attribute(prefix + 'ImageFormatControl::PixelFormat', 'Mono12')
            error = None
        except Exception as e:
            error = e.__cause__
        check(isinstance(error, imaqdx.IMAQdxError) and error.code == 0xBFF69012,
              f'imaqdx_stub: an invalid enumeration value raises IMAQdxError 0xBFF69012: {error!r}')
        worker.camera.configure_acquisition(continuous=False, bufferCount=1)
        images = []
        thread = threading.Thread(target=worker.camera.grab_multiple, args=(2, images),
                                  daemon=True)
        thread.start()
        time.sleep(1)
        check(len(images) == 1 and thread.is_alive(),
              'imaqdx_stub: grab_multiple retries a grab that times out')
        worker.camera.abort_acquisition()
        thread.join(5)
        check(not thread.is_alive(), 'imaqdx_stub: abort_acquisition ends grab_multiple')
        worker.camera.stop_acquisition()
    finally:
        worker.shutdown()
    try:
        imaqdx.imaqDispose(12345)
        error = None
    except imaqdx.ImaqError as e:
        error = e
    check(error is not None and error.code == -1074396120 and 'Not an image' in str(error),
          f'imaqdx_stub: imaqDispose of an invalid pointer raises ImaqError: {error!r}')
    check(nivision.stub_live_allocations() == 0,
          'imaqdx_stub: every NI Vision allocation is disposed after the errors')


receiver = ImageReceiver()
try:
    if '--imaqdx-stub' in sys.argv:
        check_imaqdx_stub(receiver)
        finish()

    SHOTS.mkdir(parents=True, exist_ok=True)
    ok, _ = attempt('the cameras experiment compiles', compile_shot)
    if not check(ok is True, 'the cameras experiment compile reported success'):
        finish()

    for name in MOCK_CAMERAS:
        if name == 'pylon_mock' and not pylon_mock_fixed():
            check(False, 'pylon_mock: the worker saves the attributes of the mock camera',
                  known='labscript-devices triggerable-camera branch')
            continue
        result = run_worker(name, receiver)
        if result is not None:
            images, _ = result
            check(set(images) == {'first', 'second'}
                  and all(image.shape == (500, 500) for image in images.values()),
                  f'{name}: two 500 x 500 images')
    check_dummy(receiver)
    check_genicam(receiver)

    if sys.platform.startswith('linux') and shutil.which('cc'):
        if check(build_imaqdx_stub(), 'the stub NI-IMAQdx and NI Vision libraries build'):
            env = dict(os.environ, LD_LIBRARY_PATH=str(STUB_DIR))
            result = subprocess.run([sys.executable, __file__, '--imaqdx-stub'], env=env)
            check(result.returncode == 0, 'the IMAQdx stub checks passed')
    else:
        print('The IMAQdx stub checks run on Linux with a C compiler only')
finally:
    receiver.shutdown()

finish()
