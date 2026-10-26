"""Print the Python, dependency and component versions in the venv."""

import importlib
import importlib.metadata
import os
import platform
import sys

from _common import check, finish

print(sys.version)
print(platform.platform())
print()

for dist in ['numpy', 'h5py', 'pandas', 'scipy', 'pyzmq', 'matplotlib', 'pyqtgraph',
             'qtpy', 'setuptools_scm', os.environ['QT_ENV']]:
    try:
        print(f'{dist:24s} {importlib.metadata.version(dist)}')
    except importlib.metadata.PackageNotFoundError:
        print(f'{dist:24s} not installed')
print()

components = ['zprocess', 'qtutils', 'desktop-app', 'labscript-c-extensions',
              'labscript-utils', 'labscript', 'runmanager', 'blacs', 'lyse', 'runviewer',
              'labscript-devices', 'labscript-suite']
for dist in components:
    try:
        version = importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        version = None
    check(version is not None, f'{dist} installed ({version})')

qt = importlib.import_module(os.environ['QT_ENV'] + '.QtCore')
print('Qt runtime', qt.qVersion())
finish()
