"""Import every top-level module and the GUI-dependent modules in separate interpreters
with DeprecationWarning as an error, and byte-compile the application entry modules."""

import subprocess
import sys

from _common import check, finish

MODULES = [
    'zprocess',
    'zprocess.remote',
    'qtutils',
    'qtutils.qt',
    'desktop_app',
    'labscript_c_extensions.runviewer.resample',
    'labscript_utils',
    'labscript_utils.h5_lock',
    'labscript_utils.labconfig',
    'labscript_utils.connections',
    'labscript_utils.properties',
    'labscript_utils.ls_zprocess',
    'labscript_utils.device_registry',
    'labscript_utils.qtwidgets.toolpalette',
    'labscript_utils.qtwidgets.analogoutput',
    'labscript_utils.qtwidgets.digitaloutput',
    'labscript_utils.qtwidgets.ddsoutput',
    'labscript_utils.qtwidgets.outputbox',
    'labscript_utils.qtwidgets.headerview_with_widgets',
    'labscript',
    'labscript.functions',
    'labscript_devices',
    'labscript_devices.DummyPseudoclock.labscript_devices',
    'labscript_devices.DummyPseudoclock.blacs_tabs',
    'labscript_devices.DummyPseudoclock.runviewer_parsers',
    'labscript_devices.DummyIntermediateDevice',
    'labscript_devices.PulseBlaster',
    'labscript_devices.PulseBlasterUSB',
    'labscript_devices.PineBlaster',
    'labscript_devices.NI_DAQmx.labscript_devices',
    'labscript_devices.NI_DAQmx.blacs_tabs',
    'labscript_devices.NI_DAQmx.runviewer_parsers',
    'labscript_devices.PrawnBlaster.labscript_devices',
    'labscript_devices.PrawnBlaster.blacs_tabs',
    'labscript_devices.PrawnBlaster.runviewer_parsers',
    'labscript_devices.PrawnDO.labscript_devices',
    'labscript_devices.IMAQdxCamera.labscript_devices',
    'labscript_devices.IMAQdxCamera.blacs_tabs',
    'labscript_devices.NovaTechDDS9M',
    'labscript_devices.Camera',
    'labscript_devices.ZaberStageController',
    'labscript_devices.FunctionRunner.labscript_devices',
    'labscript_devices.FunctionRunner.blacs_tabs',
    'runmanager',
    'runmanager.remote',
    'runmanager.widgets',
    'blacs',
    'blacs.tab_base_classes',
    'blacs.device_base_class',
    'blacs.experiment_queue',
    'blacs.plugins',
    'blacs.front_panel_settings',
    'blacs.output_classes',
    'lyse',
    'lyse.dataframe_utilities',
    'lyse.utils.worker',
    'runviewer',
]

# Application entry points. Importing them runs the application, so they are only
# byte-compiled.
ENTRY_MODULES = ['blacs.__main__', 'lyse.__main__', 'runmanager.__main__',
                 'runviewer.__main__', 'lyse.analysis_subprocess',
                 'runmanager.batch_compiler']


def run(code):
    return subprocess.run([sys.executable, '-X', 'utf8', '-W', 'error::DeprecationWarning',
                           '-c', code], capture_output=True, text=True, timeout=120)


for module in MODULES:
    result = run(f'import {module}')
    if not check(result.returncode == 0, f'import {module}'):
        print('    ' + result.stderr.strip().replace('\n', '\n    '))

for module in ENTRY_MODULES:
    result = run(
        'import importlib.util, py_compile, sys\n'
        f'spec = importlib.util.find_spec({module!r})\n'
        'py_compile.compile(spec.origin, doraise=True)\n'
    )
    if not check(result.returncode == 0, f'byte-compile {module}'):
        print('    ' + result.stderr.strip().replace('\n', '\n    '))

finish()
