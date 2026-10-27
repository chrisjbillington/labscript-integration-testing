"""Start one suite application with a given Qt style and colour scheme, load example
data into it, and save an image of its main window.

    python shoot.py APP --style default|fusion --scheme system|light|dark
        --data SCREENSHOTS.json --out IMAGE.png [--size WxH]

APP is blacs, runmanager, lyse or runviewer. SCREENSHOTS.json is written by prepare.py
and holds the paths of the files to load. The window has the size in SIZES unless
--size is given. After the image is saved, a JSON file with the same name as the image
records the Qt binding, versions, platform, style and the resulting colour scheme, and
the process keeps running until it is killed.

BLACS runs its device tabs with fixture/fake_worker.py in place of the device workers,
which needs the fixture directory on PYTHONPATH, without checking the output values of
the devices, and shows the analysis server as responding without connecting to it. The
channel plots of runviewer are given a height of RUNVIEWER_PLOT_HEIGHT.

Each image is saved once the example data is loaded and the window has not changed for
SETTLE_TIME."""

import argparse
import json
import os
import platform
import runpy
import sys
import time
from pathlib import Path

SIZES = {
    'blacs': '1100x480',
    'runmanager': '1000x480',
    'lyse': '1100x600',
    'runviewer': '1000x780',
}
# Widths of the left pane of BLACS, runviewer and lyse, in pixels:
BLACS_QUEUE_WIDTH = 260
RUNVIEWER_LEFT_WIDTH = 280
# Height of runviewer's shots pane, in pixels:
RUNVIEWER_SHOTS_HEIGHT = 160
LYSE_LEFT_WIDTH = 760
# Height of each channel plot of runviewer, in pixels:
RUNVIEWER_PLOT_HEIGHT = 120
# The group tab of runmanager, the device tab of BLACS, the shot of runviewer and its
# channels, and the columns of lyse's shots table that the images show:
RUNMANAGER_GROUP = 'imaging'
BLACS_TAB = 'ni_6733'
BLACS_QUEUED_SHOTS = 4
RUNVIEWER_SHOT = 7
RUNVIEWER_CHANNELS = ['camera_trigger', 'cooling_aom_amp', 'mot_coils', 'mot_shutter']
LYSE_COLUMNS = ['mot_load_time', 'tof', 'fit_cloud', 'check_saturation']
# Duration for which the window must be unchanged before we consider it drawn, in
# seconds. It is longer than the 0.1 s interval at which runviewer resamples traces.
SETTLE_TIME = 0.3
# Maximum duration for which we wait to activate the main window, in seconds:
ACTIVATION_TIMEOUT = 20
PALETTE_ROLES = [
    'WindowText', 'Button', 'Light', 'Midlight', 'Dark', 'Mid', 'Text', 'BrightText',
    'ButtonText', 'Base', 'Window', 'Shadow', 'Highlight', 'HighlightedText', 'Link',
    'LinkVisited', 'AlternateBase', 'ToolTipBase', 'ToolTipText', 'PlaceholderText',
    'Accent',
]

parser = argparse.ArgumentParser()
parser.add_argument('app', choices=['blacs', 'runmanager', 'lyse', 'runviewer'])
parser.add_argument('--style', choices=['default', 'fusion'], required=True)
parser.add_argument('--scheme', choices=['system', 'light', 'dark'], required=True)
parser.add_argument('--data', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--size', help='main window size in pixels, WxH')
args = parser.parse_args()
sys.argv = [args.app]
data = json.loads(Path(args.data).read_text())
out = Path(args.out)
width, height = (int(n) for n in (args.size or SIZES[args.app]).split('x'))

QT_ENV = os.environ.get('QT_ENV', '')
if QT_ENV == 'PyQt5' and sys.platform == 'win32':
    # Qt 5 has no colour scheme API. On Windows its dark palette is enabled with this
    # platform option and is used only when Windows is in dark mode.
    if args.scheme == 'dark':
        os.environ['QT_QPA_PLATFORM'] = 'windows:darkmode=2'

from qtutils.qt import QtCore, QtGui, QtWidgets, QT_ENV  # noqa: E402

BaseQApplication = QtWidgets.QApplication
Checked = QtCore.Qt.CheckState.Checked


def app_object():
    """The application object that the entry module creates, or None before that."""
    return getattr(sys.modules['__main__'], 'app', None)


def main_window():
    windows = [
        w for w in QtWidgets.QApplication.topLevelWidgets()
        if isinstance(w, QtWidgets.QMainWindow) and w.isVisible()
    ]
    if not windows:
        return None
    return max(windows, key=lambda w: w.width() * w.height())


def settle(condition=lambda: True):
    """Process events until condition() is true and the main window's image has not
    changed for SETTLE_TIME, for at most 120 seconds."""
    qapp = QtWidgets.QApplication.instance()
    window = main_window()
    t0 = time.monotonic()
    image = None
    t_changed = t0
    while True:
        qapp.processEvents()
        time.sleep(0.02)
        now = time.monotonic()
        if now - t0 > 120:
            print('condition not met after 120 s', flush=True)
            return
        if not condition():
            image = None
            t_changed = now
            continue
        new_image = window.grab().toImage()
        if new_image != image:
            image = new_image
            t_changed = now
        elif now - t_changed > SETTLE_TIME:
            return


def setup_runmanager(app):
    from runmanager import get_grouplist

    app.ui.lineEdit_labscript_file.setText(data['labscript_file'])
    app.open_globals_file(data['globals_file'])
    for group in get_grouplist(data['globals_file']):
        if (data['globals_file'], group) not in app.currently_open_groups:
            app.open_group(data['globals_file'], group)
    model = app.groups_model
    for row in range(model.rowCount()):
        file_item = model.item(row, app.GROUPS_COL_NAME)
        for child_row in range(file_item.rowCount()):
            active = file_item.child(child_row, app.GROUPS_COL_ACTIVE)
            if not active.data(app.GROUPS_ROLE_IS_DUMMY_ROW):
                active.setCheckState(Checked)
    engage_text = f"Engage ({len(data['shots'])} shots)"
    settle(lambda: app.ui.pushButton_engage.text() == engage_text)
    tabs = app.ui.tabWidget
    for index in range(tabs.count()):
        if tabs.tabText(index) == RUNMANAGER_GROUP:
            tabs.setCurrentIndex(index)


def setup_lyse(app):
    app.singleshot_routinebox.add_routines(
        [(path, Checked) for path in data['singleshot_routines']])
    app.multishot_routinebox.add_routines(
        [(path, Checked) for path in data['multishot_routines']])
    for shot in data['shots']:
        app.filebox.incoming_queue.put(shot)
    model = app.filebox.shots_model
    output = app.output_box.output_textedit
    multishot_names = [Path(path).name for path in data['multishot_routines']]
    settle(lambda: model.dataframe.shape[0] == len(data['shots'])
           and model.get_first_incomplete() is None
           and not app.filebox.multishot_required
           and all(name in output.toPlainText() for name in multishot_names))
    visible = {
        index: name == '__status' or name[0] in LYSE_COLUMNS
        for index, name in model.column_names.items()
    }
    app.filebox.set_columns_visible(visible)
    model._view.resizeColumnsToContents()
    model._view.scrollToTop()
    app.ui.splitter_horizontal.setSizes([LYSE_LEFT_WIDTH, width - LYSE_LEFT_WIDTH])
    app.ui.splitter.setSizes([1, 1])


def setup_runviewer(app):
    rv = sys.modules['__main__']

    app.load_shot(data['shots'][RUNVIEWER_SHOT])
    settle(lambda: app.shot_model.rowCount() == 1)
    app.shot_model.item(0, rv.SHOT_MODEL__CHECKBOX_INDEX).setCheckState(Checked)
    settle(lambda: app.channel_model.rowCount() > 0)
    for row in range(app.channel_model.rowCount()):
        item = app.channel_model.item(row, rv.CHANNEL_MODEL__CHECKBOX_INDEX)
        if item.text() in RUNVIEWER_CHANNELS:
            item.setCheckState(Checked)
    settle(lambda: len(app.plot_widgets) >= len(RUNVIEWER_CHANNELS))
    for plot in app.plot_widgets.values():
        plot.setMinimumHeight(RUNVIEWER_PLOT_HEIGHT)
        plot.setMaximumHeight(RUNVIEWER_PLOT_HEIGHT)
    app.ui.splitter.setSizes([RUNVIEWER_LEFT_WIDTH, width - RUNVIEWER_LEFT_WIDTH])
    app.ui.splitter_2.setSizes([RUNVIEWER_SHOTS_HEIGHT, height - RUNVIEWER_SHOTS_HEIGHT])
    app.ui.equal_space_time.click()


def setup_blacs(app):
    settle(lambda: all(tab.state == 'idle' for tab in app.tablist.values()))
    app.analysis_submission.server_online = 'online'
    app.queue.manager_paused = True
    for shot in data['shots'][:BLACS_QUEUED_SHOTS]:
        app.queue.process_request(shot)
    notebook = app.tab_widgets[0]
    # Every device tab is visible after startup and the tabs are drawn over each other
    # until each has been the current tab once.
    for index in range(notebook.count()):
        notebook.setCurrentIndex(index)
    notebook.setCurrentWidget(app.tablist[BLACS_TAB]._ui)
    app.ui.tab_top_vertical_splitter.setSizes([1, 0])
    app.ui.tab_horizontal_splitter.setSizes([1, 0])
    app.ui.main_splitter.setSizes([BLACS_QUEUE_WIDTH, width - BLACS_QUEUE_WIDTH])


SETUP = {
    'runmanager': setup_runmanager,
    'lyse': setup_lyse,
    'runviewer': setup_runviewer,
    'blacs': setup_blacs,
}


def save(window, active):
    """Write the JSON file of the image"""
    qapp = QtWidgets.QApplication.instance()
    hints = qapp.styleHints()
    scheme = hints.colorScheme().name if hasattr(hints, 'colorScheme') else None
    window_colour = qapp.palette().color(QtGui.QPalette.ColorRole.Window)
    info = {
        'app': args.app,
        'style_requested': args.style,
        'scheme_requested': args.scheme,
        'binding': QT_ENV,
        'qt_version': QtCore.qVersion(),
        'python': platform.python_version(),
        'os': platform.platform(),
        'qpa_platform': qapp.platformName(),
        'style': qapp.style().objectName(),
        'style_sheet': bool(qapp.styleSheet()),
        'color_scheme': scheme,
        'window_colour': window_colour.name(),
        'window_is_dark': window_colour.lightness() < 128,
        'window_active': active,
        'device_pixel_ratio': window.devicePixelRatioF(),
        'font': qapp.font().toString(),
    }
    # run_all.py reads the file as soon as it exists, so it is written whole by a rename.
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(info, indent=1))
    os.replace(tmp, out.with_suffix('.json'))
    print('saved', out, flush=True)


def use_active_colours():
    """Give the application's inactive palette the colours of its active palette, so that
    the image does not depend on whether the window has the focus."""
    qapp = QtWidgets.QApplication.instance()
    palette = qapp.palette()
    Active, Inactive = QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorGroup.Inactive
    for name in PALETTE_ROLES:
        role = getattr(QtGui.QPalette.ColorRole, name, None)
        if role is not None:
            palette.setColor(Inactive, role, palette.color(Active, role))
    qapp.setPalette(palette)


def activate(window):
    """Make the window the active window. Windows lets a process activate one of its
    windows only while it handles input, so on Windows we send a key press of the Alt
    key first."""
    window.raise_()
    if sys.platform == 'win32':
        import ctypes

        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x2
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(int(window.winId()))
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    window.activateWindow()


def take_screenshot():
    poll.stop()
    app = app_object()
    window = main_window()
    # The mouse pointer does not highlight the widgets under it:
    window.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput)
    window.showNormal()
    use_active_colours()
    window.resize(width, height)
    settle()
    SETUP[args.app](app)
    window.resize(width, height)
    settle(lambda: (window.width(), window.height()) == (width, height))
    # The applications run at the same time, and each makes its window active before its
    # image is taken. A lock file in the output directory makes them do this in turn.
    # We wait at most ACTIVATION_TIMEOUT for the lock and for the window to be active.
    lock = out.parent / 'activation.lock'
    t0 = time.monotonic()
    while time.monotonic() - t0 < ACTIVATION_TIMEOUT:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            break
        except FileExistsError:
            time.sleep(0.05)
    try:
        activate(window)
        t0 = time.monotonic()
        while not window.isActiveWindow() and time.monotonic() - t0 < ACTIVATION_TIMEOUT:
            QtWidgets.QApplication.instance().processEvents()
            time.sleep(0.02)
        settle()
        active = window.isActiveWindow()
        window.grab().save(str(out))
    finally:
        lock.unlink(missing_ok=True)
    save(window, active)


def check_ready():
    # The entry modules hide the splash screen once startup is complete. The splash
    # screen processes events while it is shown, so this timer can fire during startup.
    splash = getattr(sys.modules['__main__'], 'splash', None)
    if splash is not None and splash.isVisible():
        return
    if app_object() is not None and main_window() is not None:
        take_screenshot()


class QApplication(BaseQApplication):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if args.style == 'fusion':
            self.setStyle(QtWidgets.QStyleFactory.create('Fusion'))
        if args.scheme != 'system' and hasattr(self.styleHints(), 'setColorScheme'):
            scheme = {'light': QtCore.Qt.ColorScheme.Light, 'dark': QtCore.Qt.ColorScheme.Dark}
            self.styleHints().setColorScheme(scheme[args.scheme])
        # Text cursors are shown without blinking:
        self.setCursorFlashTime(0)
        global poll
        poll = QtCore.QTimer()
        poll.timeout.connect(check_ready)
        poll.start(50)


QtWidgets.QApplication = QApplication

if args.app == 'blacs':
    from blacs.analysis_submission import AnalysisSubmission
    from blacs.device_base_class import DeviceTab
    from blacs.tab_base_classes import Tab

    create_worker = Tab.create_worker

    def create_fake_worker(self, name, WorkerClass, workerargs=None):
        create_worker(self, name, 'fake_worker.FakeWorker', workerargs)

    Tab.create_worker = create_fake_worker
    supports_remote_value_check = DeviceTab.supports_remote_value_check
    DeviceTab.supports_remote_value_check = (
        lambda self, support: supports_remote_value_check(self, False))

    def check_connectivity(self):
        self.server_online = 'online'
        self.time_of_last_connectivity_check = time.time()

    AnalysisSubmission.check_connectivity = check_connectivity

runpy.run_module(args.app, run_name='__main__', alter_sys=True)
