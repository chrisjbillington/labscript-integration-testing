# Test harness

End-to-end tests of the labscript suite through its public entry points. The harness
installs the component repositories into a virtual environment and checks that every
module imports, that a profile can be created, that the example experiment compiles,
that the shot can be read in lyse and by the runviewer parsers, that the runmanager
library API works, that the four applications start, that their icons have high-DPI
images and that BLACS runs shots with dummy devices and sends them to lyse. It uses pip
and uv only. Conda is not used: conda installs on Windows runners are slow, and
conda-specific checks are left until a release is close.

The GitHub Actions workflow `.github/workflows/test.yml` runs the harness on Ubuntu and
Windows for Python 3.11 to 3.14 with PySide6, PyQt6 and PyQt5 weekly and on demand with
chosen component refs, Qt bindings, Pythons and runners. The weekly run also tests Python 3.15, and its 3.15 jobs may fail. A dispatch
with the same inputs as a queued or running dispatch cancels the jobs of that run.

## Usage

```
python harness/suite.py clone [name=[owner/repo@]ref ...]
python harness/suite.py install --python 3.14 [--qt PySide6|PyQt6|PyQt5] [--pin "numpy<2.5"]
python harness/suite.py test --python 3.14 [--step NAME] [--skip NAME] [--all]
```

`clone` puts the components in `repos/` (`--repos-dir` to change). A component with no
ref is fetched and checked out at the tip of its upstream default branch, unless a clone
already exists there with uncommitted changes or with a branch other than the default
branch checked out, in which case the clone is used as it is. A ref is a branch, tag, commit or `pr/<N>`, for
example `labscript=pr/124` or `zprocess=chrisjbillington/zprocess@fix-conpty`. `pr/<N>`
is the head of pull request N. A pull request, or a branch other than the default
branch, of the upstream repository or of a fork, is merged by `clone` into the current
tip of the default branch of the component's upstream repository, so the result is the
code that merging would produce; if the merge conflicts, `clone` stops with a message.
A tag or commit is checked out as it is. Several refs for one component, for example
`lyse=pr/157 lyse=pr/161 lyse=chrisjbillington/lyse@fix-plot`, are merged in turn in the
order given into the current tip of the default branch of the component's upstream
repository. The resolved commits, and for merged refs their heads and the default
branch commit that they were merged into, are written to `repos/manifest.json` and
appear in the report.

`install` makes `harness/venvs/py<version>` with uv (`--venv` to change) and installs
every component from its clone in one resolver run, with the Qt binding and any pins.
PySide6 is installed as `PySide6<6.12`: PySide6 6.12.0 crashes lyse
([PYSIDE-3500](https://qt-project.atlassian.net/browse/PYSIDE-3500), and on Python 3.11
[PYSIDE-3474](https://qt-project.atlassian.net/browse/PYSIDE-3474)). PySide6 6.11 does not support Python 3.15, so the workflow has no PySide6
jobs on Python 3.15.
`--python` is a version for uv to find or download, or a path to an interpreter.
Components are built with `SETUPTOOLS_SCM_PRETEND_VERSION=99.0.0` because shallow clones
have no tags and the components pin each other by version.
The commit of each clone at install time is recorded in the venv's `harness.json`, and
the report's component table is taken from it, so a clone that is changed after `clone`
(a local branch, for example) is described as installed. The venv holds a copy of each
component, so `test` stops if a clone's commit is not the one installed; run `install`
again.

`clone` checks out the given refs in the clones in `--repos-dir`, so a run with refs
should use a `--repos-dir` and a `--venv` of its own if the clones there are used for
other work.

`test --venv` also accepts a conda env in which the suite is installed from conda
packages. `install` does not make conda envs, so write `harness.json` in the env
yourself, with an empty `components` so that `test` does not compare the clones with the
installed packages, and run `test` with the env activated, for example with `conda run`:

```
{"python": "3.14.10 (conda)", "qt": "PySide6", "pins": [], "repos_dir": "<path to the clones>", "install_ok": true, "components": {}}
```

Only the `zprocess-tests` step uses the clones; it runs the tests of the zprocess clone,
which should then be at the commit that the zprocess package was built from. The
report's component table is empty.

`test` runs the steps below in order and writes `report.md`, `state.json` and one log
per step to `harness/work-py<version>/` (`--work` to change), which it deletes first. A
step that another step depends on is skipped when the dependency failed, and with
`--step` a step is skipped unless the steps that it depends on are also given: every
step but `versions`, `imports` and `zprocess-tests` needs `profile`, and `lyse`,
`runviewer`, `apps`, `lyse-gui` and `blacs-shot` also need `compile`, for example
`--step profile --step compile --step runmanager-abort`. The exit status is nonzero if
any step failed. Set `GITHUB_STEP_SUMMARY` and the report is appended to it.

Every step runs with `LABSCRIPT_DISABLE_GRAPHICAL_EXCEPTHOOK=1`, so that the
applications and their subprocesses print exceptions to stderr instead of opening an
error window. labscript-utils releases before 3.5.0 ignore the variable.

## Steps

| Step | What it checks |
|---|---|
| `versions` | Python, dependency and component versions; every component is installed |
| `profile` | `labscript-profile-create` makes a profile; the labconfig points `shared_drive` at the work directory; a FunctionRunner from `fixtures/function_runner` is added to the example connection table and experiment, with one function at the start and one at the stop of the shot; the runmanager test fixtures are copied into `userlib/labscriptlib/runmanager_test` |
| `imports` | Every top-level module and the Qt-dependent modules import in a fresh interpreter with `-W error::DeprecationWarning`; the application entry modules byte-compile |
| `compile` | The profile's connection table and `example_experiment.py` compile through `runmanager.compile_labscript_async`; the shot file has the expected groups, devices, connection table rows, time markers and stop time, and the FunctionRunner's two functions with their whole source |
| `lyse` | `lyse.Run` reads globals, saves and reads back results and arrays; `get_dataframe_from_shot` and `get_dataframe_from_shots` return the results |
| `runviewer` | `runviewer.__main__.Shot` loads the shot, which runs the runviewer parser of every device that has one; the traces and markers are checked |
| `narwhal` | Shots with Narwhal Devices Pulse Generators from `fixtures/narwhal/`: the instruction tables (odd-cycle clock periods, a wait after a ramp, a powerline wait, a wait at t=0), the runviewer parser, and the BLACS worker on a simulated device as master and secondary, with waits that are triggered, time out and synchronise to the powerline, an abort, and a secondary that is never triggered |
| `runmanager-api` | The library API on the `runmanager_test` fixture: globals file CRUD, the size of a globals file after many writes, evaluation, expansion, diff, run files, single-shot and multishot compilation with the compiler output streamed to a PULL socket |
| `apps` | runmanager, runviewer, lyse and BLACS start under `QT_QPA_PLATFORM=offscreen`, listen on their labconfig ports and run for five seconds; the runmanager remote API is exercised; `zprocess.port_in_use`, when installed, returns the right result for each port and for a free port, and its times are reported; a second copy of each application reports that its port is in use, and the second BLACS creates no device tabs; the output of each is checked for tracebacks |
| `icons` | runmanager, runviewer, lyse and BLACS start, each in a subprocess of the check under `QT_QPA_PLATFORM=offscreen` at a device pixel ratio of 1; every icon of every widget, action, tab, header and item has a 32 px image as well as the 16 px one, so that it is drawn from the 32 px image on a high-DPI screen, including one attached after the application started; and no QLabel holds a pixmap of icon size, which would be drawn from the 16 px image on every screen |
| `lyse-gui` | The lyse GUI in this process under `QT_QPA_PLATFORM=offscreen`: a shot file that has not been run is not loaded; the results of two enabled single-shot routines appear in the dataframe and the shots table and a disabled routine does not run; results saved when the shot is analysed again replace them; lyse code issues no `DeprecationWarning` when the results add columns to the dataframe; a routine error pauses analysis and keeps the results saved before it; a routine that loops in Python and a routine blocked in a long sleep are interrupted by the Abort button and their workers survive, a routine that ignores the interrupt with an HDF5 file open has its worker restarted when it closes the file, without a kill, and the file is readable, analysis is paused in each case, and an interrupted worker then runs a routine to completion; in a subprocess, the Edit columns dialog survives being updated as 200 columns are added one at a time |
| `blacs-shot` | lyse and BLACS start; a copy of the example shot is submitted to BLACS as runmanager submits it, and BLACS runs it with the dummy devices of the profile's connection table and sends it to lyse; the same file submitted again runs as a repeat in a new file; both shot files have a run time and a `data` group, in which the FunctionRunner's stop function recorded that both functions ran; the output of both applications has no tracebacks and BLACS.log has no errors |
| `blacs-workers` | A BLACS device tab runs in this process under `QT_QPA_PLATFORM=offscreen` with a worker from `fixtures/blacs_workers/`. A restart while the worker is idle, in `time.sleep()` or in a Python loop ends the worker promptly with exit status 0; a worker with a job that ignores `KeyboardInterrupt` exits after its abort timeout, or when the job closes its HDF5 file, which is then readable; outside Windows a worker stopped with `SIGSTOP` is killed after the quit timeout (the timeouts are shortened); after each restart the new worker runs a job. A fatal error ends the worker without calling its `shutdown()`. The stop button runs `shutdown()` and ends the worker, the stopped tab runs no states and has a message that cannot be dismissed, and the button starts the tab again |
| `runmanager-abort` | The runmanager GUI in this process under `QT_QPA_PLATFORM=offscreen` compiles the experiment in `fixtures/runmanager_abort/`. The Abort button interrupts a compilation in `time.sleep()` or in a Python loop, the next shot is not compiled and the compiler keeps running; Restart subprocess ends a compiler in a Python loop promptly with exit status 0, one that ignores `KeyboardInterrupt` after its abort timeout, and outside Windows kills one stopped with `SIGSTOP` after the quit timeout (the timeouts are shortened); after each the compiler compiles three shots |
| `zprocess-tests` | The zprocess test suite with pytest. Skipped unless `--all` or `--step zprocess-tests` is given; it takes two minutes |

A check for a known open bug is marked `KNOWN` in the log and does not fail the step.
When the bug is fixed the check prints `FIXED` so that the marker can be removed. At
present the `lyse-gui` check "the filebox has an Abort button" is marked as known for
lyse #153, with the Abort checks run only when the button is present. The `narwhal`
check "the installed labscript-devices has the NarwhalPulseGenerator package" is marked
as known for the labscript-devices `narwhal-pulsegen` branch, with the rest of the step
run only when the package is present. The `runmanager-api` check that a globals file is
smaller than 1.5 MB after 600 writes is marked as known for runmanager #144. The `apps`
checks that a second copy of an application reports that its port is in use are marked
as known for blacs #138, lyse #159, runmanager #146 and runviewer #80, and the
`blacs-shot` checks of a shot that is submitted as soon as BLACS listens are marked as
known for blacs #138. The `blacs-workers` checks of the exit status and the time taken
are marked as known for blacs #145, and the checks of a fatal error and of the stop
button for blacs #146, with the stop button checks run only when the tab has one. The
`runmanager-abort` checks of the Abort button and of the time taken and exit status
after Restart subprocess are marked as known for runmanager #152.

## The profile

The suite reads its profile from `~/labscript-suite` and `import labscript_utils`
creates one when none exists, so the `profile` step runs before anything else imports
labscript_utils. The harness writes a marker file into the profile it creates and on the
next run deletes and recreates only a profile that has the marker. A profile without the
marker stops the run; move it away before testing on a machine that has one. On Windows
the zlock and zlog servers that an earlier run started hold their log files in the
profile open, so the `profile` step stops each process with a command line that runs
`zprocess.zlock` or `zprocess.zlog` and names a file in the profile before it deletes
the profile. The shared secret is carried over from the previous harness profile so that
a zlock or zlog server left running by an earlier run still accepts connections.

The applications use the ports in the labconfig (42517 to 42523 and 7339 to 7341), so
the `apps` and `blacs-shot` steps fail if a suite application is already running on the
machine.

On a Linux machine that has a real profile and running suite servers, the harness can run
in a user, mount, network and PID namespace instead, with a scratch directory as the
home of the mapped root user, so that the profile goes to that directory and the ports
are separate. The profile path comes from the user name, so `LOGNAME` and `USER` are set
to `root`. The harness does not end the zlock and zlog servers that the applications
start. In a PID namespace the kernel kills them when the command exits; without one,
every run leaves two servers running:

```
mkdir -p /tmp/fakeroot
env -u DISPLAY -u WAYLAND_DISPLAY unshare -Urmnp --fork sh -c 'ip link set lo up \
    && mount --bind /tmp/fakeroot /root && export HOME=/root LOGNAME=root USER=root \
    && python harness/suite.py test --python 3.14 --work /tmp/harness-work'
```

The X display is still reachable through its socket, so without the `env -u` an
application or error window started this way appears on the desktop.

## Requirements

uv on the PATH or installed in the Python that runs `suite.py`; git; a C compiler for
labscript-c-extensions; on Linux the shared libraries that Qt needs (`libegl1`,
`libopengl0`, `libgl1`, `libxkbcommon0`, `libxkbcommon-x11-0`, `libdbus-1-3`,
`libfontconfig1`, `libglib2.0-0`, `libxcb-cursor0` on Ubuntu 24.04).

## Fixtures

`fixtures/runmanager_test/` holds a connection table and an experiment with dummy
devices whose globals (`amplitude`, `gain`, `offset`, `duration`, `use_do`, `derived`)
are created by the `runmanager-api` step. The experiment prints a line so that the step
can check that compiler output is streamed.

`fixtures/function_runner/` holds the FunctionRunner that the `profile` step inserts into
the example connection table and `example_experiment.py`, after their device
definitions. The experiment adds one function at the start of the shot and one at the
stop, which records in the shot's `data/function_runner` group that both ran.

`fixtures/blacs_workers/` holds the BLACS worker of the `blacs-workers` step, with jobs
that sleep, loop, ignore `KeyboardInterrupt`, write an HDF5 file and stop the process, a
job that sets the worker's timeouts, and a `shutdown()` method that records its call.

`fixtures/runmanager_abort/` holds the experiment of the `runmanager-abort` step. The
global `mode` sets what it does after `start()`, and the globals `abort_timeout` and
`kill_lock_timeout` set the compiler's timeouts.
