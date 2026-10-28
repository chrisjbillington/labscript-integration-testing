# Screenshots of the applications

The scripts in this directory take images of the main windows of BLACS, runmanager, lyse
and runviewer for each Qt binding, with the platform's default Qt style or with Fusion,
and with the light and dark colour schemes, for comparisons before and after a change
and for pull requests. The windows are smaller than in use, so that the images have
little empty space.

## On GitHub Actions

`.github/workflows/screenshots.yml` takes the images on Windows. Dispatch it with the
refs of the change in `after`, in the form that `test.yml` takes:

```
gh workflow run screenshots.yml -R chrisjbillington/labscript-integration-testing \
    -f after="labscript-utils=pr/151 runmanager=pr/154"
```

It has one job for each Qt binding and each of two sets: "before", with the default
branches or the refs in `before`, and "after", with the refs in `after`. The before set
is taken with the default style and with Fusion, and the after set with the styles in
`after_styles`. Each job takes the light images with Windows in light mode and the dark
images with Windows in dark mode, and uploads the images as the artifact
`screenshots-<set>-<binding>`:

```
gh run download RUN_ID -R chrisjbillington/labscript-integration-testing -D DIR
```

## Locally

`prepare.py SHARED_DRIVE`, run with the Python of a harness venv, makes the profile and
the example data: a profile at `~/labscript-suite` whose apparatus has the devices of
`fixture/connection_table.py` (a PulseBlasterUSB, an NI PCI-6733 and a NovaTech DDS9M,
with named outputs), the compiled connection table, a globals file with three groups,
twelve shots of `fixture/sequence.py` (a time-of-flight scan over two MOT load times)
with a run time, and the four analysis routines of `fixture/` in the analysislib. Two
globals of the `imaging` group cannot be evaluated; they are added after the shots are
compiled. It writes the paths to `SHARED_DRIVE/screenshots.json`. It deletes and
remakes `~/labscript-suite` and SHARED_DRIVE, and refuses to run if `~/labscript-suite`
was not made by the harness or by `prepare.py`, or if SHARED_DRIVE is not empty and was
not made by `prepare.py`. Give it a new scratch directory as SHARED_DRIVE, never a
directory with real shots.

`run_all.py --data SHARED_DRIVE/screenshots.json --out DIR --venv PySide6=PATH --venv
PyQt6=PATH --venv PyQt5=PATH` runs `shoot.py` once per combination and writes
`DIR/<app>-<binding>-<style>-<scheme>.png` with a JSON file of the binding, the Qt
version, the platform, the style, the application font and the resulting window colour.
`--app`, `--style` and `--scheme` restrict the combinations. With `--switch-scheme`, each application starts
with the other colour scheme and switches to the given one once the example data is
loaded, which shows how the application handles a change of colour scheme while it runs;
the images are named `...-switched.png`, and PyQt5 is skipped. The JSON file records the
base colour of each check box. The four applications run
at the same time, each through its combinations in turn. The profile is used by all
venvs, so one `prepare.py` serves the images of several sets of venvs, for example
before and after a change.

With `--offscreen` the applications use Qt's offscreen platform with a 1920 by 1080
screen (`offscreen.json`) and no windows are shown, which suits checks of layout. The
offscreen platform has no platform theme and no colour scheme: the default font is Qt's
fallback font, Qt 6 uses Fusion's own palette (window colour #efefef instead of the
desktop's #fcfcfc), and only light images are taken. Glyphs are rendered a little
differently. Images for comparisons and pull requests are taken on screen.

`shoot.py` replaces the binding's `QApplication` with a subclass that sets the style and
the colour scheme, runs the application's entry module and, once the main window is
shown and the splash screen is hidden, gives it the size in `SIZES` and loads the
example data. It saves the image once the data is loaded and the window has been
unchanged for 0.3 s. Before the image is taken, the window is made the active window;
the applications do this in turn, using a lock file in the output directory. On Windows,
which lets a process activate its window only while it handles input, `shoot.py` sends a
key press of Alt first. The JSON file records whether the window was active. Text cursors
do not blink, the inactive palette has the colours of the active one, and the window does
not take mouse input, so that the image does not depend on the mouse pointer.

- BLACS: the device tabs run `fixture/fake_worker.py` in place of their workers and do
  not check the output values of the devices, so they start without hardware, and the
  analysis server is shown as responding. The queue is paused and has four shots; the
  tabs are in the top-left notebook, the other notebooks are collapsed, and the NI
  card's tab is shown.
- runmanager: the experiment script and the globals file, with every group open and
  active, and the `imaging` group shown.
- lyse: the two single-shot and two multishot routines and the twelve shots, analysed.
  The shots table shows the two scanned globals and the results; the other columns are
  hidden.
- runviewer: one shot with four channels, with the markers spaced evenly. The channel
  plots are given a height of 120 pixels instead of 200, so that four fit in the
  window.

The window sizes, splitter positions and the choice of group, tab, channels and columns
are constants at the top of `shoot.py`.

The colour scheme is set with `QStyleHints.setColorScheme`, which Qt 5 does not have. On
Windows, a dark PyQt5 image uses the `windows:darkmode=2` platform option, which gives a
dark palette only when Windows itself is in dark mode. Windows is put in dark mode for
the applications, even when it is not activated, with

```
reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize /v AppsUseLightTheme /t REG_DWORD /d 0 /f
```

and back in light mode with `/d 1`. On Linux, `run_all.py` skips PyQt5 with the dark
scheme.

On a Linux machine with a real profile, run the applications in namespaces, as the
harness does. The D-Bus session bus refuses a client whose user ID is 0, so the command
runs in a nested user namespace in which the user ID is that of the real user:

```
cat > ns.sh <<'END'
#!/bin/sh
ip link set lo up && mount --bind "$SCRATCH_HOME" /root || exit 1
export HOME=/root LOGNAME=root USER=root
exec unshare -U --map-user="$REAL_UID" --map-group="$REAL_GID" "$@"
END
SCRATCH_HOME=/tmp/fakeroot REAL_UID=$(id -u) REAL_GID=$(id -g) \
    unshare -Urmnp --fork sh ns.sh python screenshots/run_all.py ...
```

`prepare.py` runs the same way, with `/root/shared_drive` as SHARED_DRIVE, and the
profile and the shots stay in the scratch home for later runs. The scratch home has no
desktop settings, so the GTK theme is the default Adwaita and not the desktop's theme.
