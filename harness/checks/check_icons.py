"""Start runmanager, runviewer, lyse and BLACS, each in a subprocess of this script,
under the offscreen platform at a device pixel ratio of 1, and check that every icon
of every widget, action, tab, header and item has a 32 px image as well as the 16 px
one, so that it is drawn from the 32 px image on a high-DPI screen, including one
attached after the application started; and that no QLabel holds a pixmap of icon size,
which would be drawn from the 16 px image on every screen."""

import os
import runpy
import subprocess
import sys
import traceback

from _common import check, finish

APPS = ['runmanager', 'runviewer', 'lyse', 'blacs']

# Time from the start of the application's event loop to the check, for the window to
# be built:
SETTLE_SECONDS = 5

# Icons and pixmaps larger than this are not icons of the suite's icon set:
ICON_SIZE_LIMIT = 32


def run_app(app):
    """Start the application in a subprocess that runs this script in check mode, and
    record whether its icons pass."""
    try:
        proc = subprocess.run([sys.executable, '-X', 'utf8', __file__, app],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    except subprocess.TimeoutExpired as e:
        print((e.stdout or b'').decode('utf8', errors='replace'), flush=True)
        check(False, f'{app}: the application ended within 300 s')
        return
    print(proc.stdout.decode('utf8', errors='replace'), flush=True)
    check(proc.returncode == 0, f'{app}: every icon has its 32 px image and no label holds an icon pixmap')


def describe(widget):
    """The class and object names of a widget and its parents."""
    names = []
    w = widget
    while w is not None:
        names.append(f'{type(w).__name__}({w.objectName()!r})')
        w = w.parentWidget()
    return ' in '.join(names)


def check_app(app):
    from qtutils.qt import QtCore, QtGui, QtWidgets
    QIcon = QtGui.QIcon
    problems = []

    def check_icon(what, icon):
        if not isinstance(icon, QIcon) or icon.isNull():
            return
        sizes = sorted({s.width() for s in icon.availableSizes()})
        if sizes == [16]:
            problems.append(f'{what}: the icon has only the 16 px image')

    def check_decoration(what, value):
        if isinstance(value, QtGui.QPixmap):
            check_pixmap(what, value)
        else:
            check_icon(what, value)

    def check_pixmap(what, pixmap):
        if pixmap is None or pixmap.isNull():
            return
        if pixmap.devicePixelRatio() == 1 and max(pixmap.width(), pixmap.height()) <= ICON_SIZE_LIMIT:
            problems.append(f'{what}: a {pixmap.width()}x{pixmap.height()} pixmap at device '
                            f'pixel ratio 1')

    def check_model(what, model, parent=QtCore.QModelIndex(), depth=0):
        if model is None or depth > 8:
            return
        for row in range(min(model.rowCount(parent), 1000)):
            for column in range(model.columnCount(parent)):
                index = model.index(row, column, parent)
                if not index.isValid():
                    continue
                check_decoration(f'{what} item ({row}, {column}) at depth {depth}',
                                 model.data(index, QtCore.Qt.DecorationRole))
                if column == 0 and model.hasChildren(index):
                    check_model(what, model, index, depth + 1)

    seen_actions = set()
    for widget in QtWidgets.QApplication.allWidgets():
        what = describe(widget)
        if widget.isWindow():
            check_icon(f'window icon of {what}', widget.windowIcon())
        if isinstance(widget, (QtWidgets.QAbstractButton, QtWidgets.QMenu)):
            check_icon(f'icon of {what}', widget.icon())
        elif hasattr(widget, 'icon') and callable(widget.icon):
            # A widget class with an icon, such as an IconLabel
            try:
                check_icon(f'icon of {what}', widget.icon())
            except TypeError:
                pass
        if isinstance(widget, QtWidgets.QLabel):
            check_pixmap(f'pixmap of {what}', widget.pixmap())
        if isinstance(widget, QtWidgets.QTabBar):
            for i in range(widget.count()):
                check_icon(f'tab {i} ({widget.tabText(i)!r}) of {what}', widget.tabIcon(i))
        if isinstance(widget, QtWidgets.QComboBox):
            for i in range(widget.count()):
                check_icon(f'item {i} of {what}', widget.itemIcon(i))
        if isinstance(widget, QtWidgets.QToolBox):
            for i in range(widget.count()):
                check_icon(f'page {i} of {what}', widget.itemIcon(i))
        # The methods are called unbound: a widget subclass may have an attribute of the
        # same name.
        if isinstance(widget, QtWidgets.QHeaderView):
            model = QtWidgets.QHeaderView.model(widget)
            if model is not None:
                for i in range(widget.count()):
                    check_decoration(f'section {i} of {what}',
                                     model.headerData(i, widget.orientation(), QtCore.Qt.DecorationRole))
        if isinstance(widget, QtWidgets.QAbstractItemView):
            check_model(what, QtWidgets.QAbstractItemView.model(widget))
        for action in widget.actions():
            if id(action) in seen_actions:
                continue
            seen_actions.add(id(action))
            check_icon(f'action {action.text()!r} of {what}', action.icon())

    for problem in problems:
        check(False, f'{app}: {problem}')
    check(not problems, f'{app}: {len(seen_actions)} actions and {len(QtWidgets.QApplication.allWidgets())} '
                        f'widgets checked, {len(problems)} problems')
    return not problems


def run_in_app(app):
    """Run the application's entry module in this process, check its icons once its
    event loop has run for SETTLE_SECONDS, and end it."""
    sys.argv = [app]
    from qtutils.qt import QtCore, QtWidgets
    BaseQApplication = QtWidgets.QApplication
    result = {'ok': False}

    def start():
        try:
            result['ok'] = check_app(app)
        except Exception:
            traceback.print_exc()
            check(False, f'{app}: the icon check ran without an exception')
        QtWidgets.QApplication.instance().exit(0)

    class QApplication(BaseQApplication):
        def exec(self):
            QtCore.QTimer.singleShot(SETTLE_SECONDS * 1000, start)
            return super().exec()

    QtWidgets.QApplication = QApplication
    runpy.run_module(app, run_name='__main__', alter_sys=True)
    sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        run_in_app(sys.argv[1])
    for app in APPS:
        run_app(app)
    finish()
