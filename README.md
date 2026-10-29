# labscript-integration-testing

End-to-end tests of the [labscript suite](https://github.com/labscript-suite), run on
GitHub Actions. The tests install the suite's component repositories, at their default
branches or at given branches, commits and pull requests, and run them through their
public entry points.

| Path | What it is |
|---|---|
| `harness/` | The test harness: clones the components, installs them into a virtual environment and runs the checks; `harness/README.md` describes the checks and the options |
| `screenshots/` | Scripts that take images of the main windows of BLACS, runmanager, lyse and runviewer with example data, before and after a change; `screenshots/README.md` describes them |
| `.github/workflows/screenshots.yml` | Takes those images on Windows for each Qt binding, in light and dark mode, on demand with chosen component refs |
| `.github/workflows/test.yml` | Runs the harness on Ubuntu and Windows for Python 3.11 to 3.14 with PySide6, PyQt6 and PyQt5, and builds the docs of the components and compiles their example scripts: weekly (also with Python 3.15), and on demand with chosen component refs |

To test pull requests, dispatch the workflow with their refs:

```
gh workflow run test.yml -R chrisjbillington/labscript-integration-testing \
    -f refs="lyse=pr/157 labscript-utils=pr/149"
```

`name=pr/N` tests pull request N, and `name=owner/repo@branch` a branch of any fork,
merged into the current default branch of the component. Several refs for one
component are merged in turn. The workflow's other inputs select
the runners, Python versions, Qt bindings and extra pip requirements.
