#!/usr/bin/env python3
"""Test harness for the labscript suite.

Clones the component repositories at given refs, installs them into a virtual
environment and runs end-to-end checks through the public entry points: import every
module, create a labscript profile, compile the example experiment, read the shot back
in lyse, run the runviewer parsers on it, exercise the runmanager library API and start
each application.

    python harness/suite.py clone [SPEC ...]
    python harness/suite.py install --python 3.14
    python harness/suite.py test

and builds the Sphinx docs of the components and compiles their example scripts:

    python harness/suite.py install --python 3.11 --docs
    python harness/suite.py docs --python 3.11

Run `python harness/suite.py <command> --help` for the options. `harness/README.md`
describes the steps and the ref specs.
"""

import argparse
import json
import os
import re
import signal
import threading
import shutil
import subprocess
import sys
import time
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
ROOT = HARNESS_DIR.parent
CHECKS_DIR = HARNESS_DIR / 'checks'
STACKDUMP_DIR = HARNESS_DIR / 'stackdump'
# Time before a step's timeout at which its Python processes write their stacks, in s:
STACKS_LEAD = 15
# Time for which the harness waits for processes started by earlier steps to write their
# stacks, in s:
STACKS_REQUEST_WAIT = 3
# Stacks directories of the steps that finished, deleted after each step:
PASSED_STACKS = []

# Components in installation order. The ref is the upstream default branch.
COMPONENTS = {
    'zprocess': ('chrisjbillington/zprocess', 'master'),
    'qtutils': ('philipstarkey/qtutils', 'master'),
    'desktop-app': ('chrisjbillington/desktop-app', 'master'),
    'labscript-c-extensions': ('labscript-suite/labscript-c-extensions', 'master'),
    'labscript-utils': ('labscript-suite/labscript-utils', 'master'),
    'labscript': ('labscript-suite/labscript', 'master'),
    'runmanager': ('labscript-suite/runmanager', 'master'),
    'blacs': ('labscript-suite/blacs', 'master'),
    'lyse': ('labscript-suite/lyse', 'master'),
    'runviewer': ('labscript-suite/runviewer', 'master'),
    'spinapi': ('chrisjbillington/spinapi', 'master'),
    'labscript-devices': ('labscript-suite/labscript-devices', 'master'),
    'labscript-suite': ('labscript-suite/labscript-suite', 'master'),
}

# The version that setuptools_scm reports for every component built from a clone.
# Shallow clones have no tags, and the components pin each other by version.
PRETEND_VERSION = '99.0.0'

QT_BINDINGS = ['PySide6', 'PyQt6', 'PyQt5']

# The requirements installed for each Qt binding. PySide6 6.12.0 aborts any
# long-running application on Python 3.11 (PYSIDE-3474).
QT_REQUIREMENTS = {
    'PySide6': ['PySide6!=6.12.0; python_version < "3.12"', 'PySide6; python_version >= "3.12"'],
    'PyQt6': ['PyQt6'],
    'PyQt5': ['PyQt5'],
}

# For the GenICamCamera check. genicam, which harvesters requires, has no wheels for
# Python 3.15.
HARVESTERS_REQUIREMENT = 'harvesters; python_version < "3.15"'

# Check scripts in `checks/`, in run order, with the steps each one needs. The profile
# step runs before anything imports labscript_utils, which creates a profile when none
# exists.
STEPS = [
    ('versions', []),
    ('profile', []),
    ('imports', []),
    ('compile', ['profile']),
    ('lyse', ['compile']),
    ('runviewer', ['compile']),
    ('narwhal', ['profile']),
    ('runmanager-api', ['profile']),
    ('apps', ['compile']),
    ('icons', ['compile']),
    ('lyse-gui', ['compile']),
    ('blacs-shot', ['compile']),
    ('cameras', ['profile']),
    ('blacs-workers', ['profile']),
    ('runmanager-abort', ['profile']),
    ('zprocess-tests', []),
]
DEFAULT_SKIP = ['zprocess-tests']

# The steps of the `docs` command.
DOCS_STEPS = [
    ('profile', []),
    ('docs', ['profile']),
    ('docs-examples', ['profile']),
]

QT_PACKAGES = {name.lower() for name in QT_BINDINGS}


def log(msg):
    print(msg, flush=True)


def run(cmd, **kwargs):
    log('$ ' + ' '.join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kwargs)


def default_repos_dir():
    return ROOT / 'repos'


def default_venv(python):
    return ROOT / 'harness' / 'venvs' / f'py{python}'.replace('/', '_').replace('\\', '_')


def venv_python(venv):
    """The interpreter of a venv, or of a conda env, which on Windows has it at the top
    level instead of in Scripts."""
    venv = Path(venv)
    if sys.platform == 'win32':
        if (venv / 'conda-meta').is_dir():
            return venv / 'python.exe'
        return venv / 'Scripts' / 'python.exe'
    return venv / 'bin' / 'python'


def uv_command():
    uv = shutil.which('uv')
    if uv:
        return [uv]
    return [sys.executable, '-m', 'uv']


# ---------------------------------------------------------------------------
# clone


def parse_spec(spec):
    """Parse `name=[owner/repo@]ref` into (name, owner/repo, ref).

    `ref` is a branch, tag, commit or `pr/<N>`."""
    if '=' not in spec:
        raise SystemExit(f'bad spec {spec!r}: expected name=[owner/repo@]ref')
    name, _, rest = spec.partition('=')
    if name not in COMPONENTS:
        raise SystemExit(f'unknown component {name!r}; known: {", ".join(COMPONENTS)}')
    repo, default_ref = COMPONENTS[name]
    if '@' in rest:
        repo, _, ref = rest.partition('@')
    else:
        ref = rest
    return name, repo, ref or default_ref


def rev_parse(dest, rev):
    return subprocess.run(['git', '-C', str(dest), 'rev-parse', rev],
                          capture_output=True, text=True, check=True).stdout.strip()


def is_branch_or_pull_request(upstream, default_ref, repo, ref):
    """Whether `ref` of `repo` is a pull request, or a branch other than the default branch
    `default_ref` of the component's `upstream` repo."""
    if ref.startswith('pr/'):
        return True
    if repo.lower() == upstream.lower() and ref == default_ref:
        return False
    heads = subprocess.run(['git', 'ls-remote', '--heads', f'https://github.com/{repo}', ref],
                           capture_output=True, text=True, check=True).stdout
    return any(line.split('\t')[-1] == f'refs/heads/{ref}' for line in heads.splitlines())


def ref_label(upstream, repo, ref):
    """`ref`, prefixed with `repo@` if `repo` is not the component's `upstream` repo."""
    return ref if repo.lower() == upstream.lower() else f'{repo}@{ref}'


def merge_refs(dest, upstream, refs, base_ref):
    """Check out `base_ref` with the refs `refs`, a list of (owner/repo, ref), merged into
    it in turn, and return (base commit, {label: head commit}). A ref `pr/<N>` is the head
    of pull request N. The histories are fetched in full so that the merge bases are
    available."""
    shallow = subprocess.run(['git', '-C', str(dest), 'rev-parse', '--is-shallow-repository'],
                             capture_output=True, text=True).stdout.strip() == 'true'
    unshallow = ['--unshallow'] if shallow else []
    run(['git', '-C', dest, 'fetch', '-q'] + unshallow + ['origin', base_ref], check=True)
    run(['git', '-C', dest, 'checkout', '-q', '--detach', 'FETCH_HEAD'], check=True)
    base = rev_parse(dest, 'HEAD')
    heads = {}
    for repo, ref in refs:
        label = ref_label(upstream, repo, ref)
        fetch_ref = f'refs/pull/{ref[3:]}/head' if ref.startswith('pr/') else ref
        run(['git', '-C', dest, 'fetch', '-q', f'https://github.com/{repo}', fetch_ref], check=True)
        head = rev_parse(dest, 'FETCH_HEAD')
        merged = run(['git', '-C', dest, '-c', 'user.name=harness', '-c', 'user.email=harness@localhost',
                      'merge', '-q', '--no-edit', head])
        if merged.returncode:
            run(['git', '-C', dest, 'merge', '--abort'])
            onto = ' and '.join([base_ref] + list(heads))
            raise SystemExit(f'{dest.name}: {label} conflicts with {onto}')
        heads[label] = head
    return base, heads


def origin_repo(dest):
    """The owner/repo, in lower case, of the GitHub URL of origin in the clone at `dest`."""
    url = subprocess.run(['git', '-C', str(dest), 'remote', 'get-url', 'origin'],
                         capture_output=True, text=True).stdout.strip()
    url = url.removesuffix('/').removesuffix('.git')
    return '/'.join(url.replace(':', '/').split('/')[-2:]).lower()


def local_work(dest, default_ref):
    """A description of the uncommitted changes or the checked-out branch other than
    `default_ref` in the clone at `dest`, or None if it has neither."""
    status = subprocess.run(['git', '-C', str(dest), 'status', '--porcelain', '--untracked-files=no'],
                            capture_output=True, text=True, check=True).stdout
    if status:
        return 'uncommitted changes'
    branch = subprocess.run(['git', '-C', str(dest), 'symbolic-ref', '-q', '--short', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
    if branch and branch != default_ref:
        return f'branch {branch}'
    return None


def describe_heads(heads):
    return ' and '.join(f'{ref} (head {head[:10]})' for ref, head in heads.items())


def cmd_clone(args):
    repos_dir = Path(args.repos_dir)
    repos_dir.mkdir(parents=True, exist_ok=True)
    specs = {}
    for spec in args.spec:
        name, repo, ref = parse_spec(spec)
        specs.setdefault(name, []).append((repo, ref))
    manifest = {}
    for name, (repo, default_ref) in COMPONENTS.items():
        dest = repos_dir / name
        if name in specs:
            refs = specs[name]
            merge = len(refs) > 1 or is_branch_or_pull_request(repo, default_ref, *refs[0])
            if not merge:
                repo = refs[0][0]
        elif (dest / '.git').exists() and local_work(dest, default_ref):
            head = rev_parse(dest, 'HEAD')
            log(f'{name}: using existing clone at {head[:10]} ({local_work(dest, default_ref)})')
            manifest[name] = {'repo': None, 'ref': None, 'commit': head}
            continue
        else:
            refs = [(repo, default_ref)]
            merge = False
        url = f'https://github.com/{repo}'
        fresh = not (dest / '.git').exists()
        if fresh:
            dest.mkdir(parents=True, exist_ok=True)
            run(['git', 'init', '-q', dest], check=True)
            run(['git', '-C', dest, 'remote', 'add', 'origin', url], check=True)
        elif origin_repo(dest) != repo.lower():
            run(['git', '-C', dest, 'remote', 'set-url', 'origin', url], check=True)
        if merge:
            base, heads = merge_refs(dest, repo, refs, default_ref)
            head = rev_parse(dest, 'HEAD')
            manifest[name] = {'repo': repo, 'ref': ' '.join(heads), 'commit': head, 'base': base,
                              'heads': heads}
            log(f'{name}: {repo} {describe_heads(heads)} merged into {default_ref} '
                f'{base[:10]} as {head[:10]}')
        else:
            (_, ref), = refs
            shallow = subprocess.run(['git', '-C', str(dest), 'rev-parse', '--is-shallow-repository'],
                                     capture_output=True, text=True).stdout.strip() == 'true'
            depth = ['--depth', '1'] if fresh or shallow else []
            run(['git', '-C', dest, 'fetch', '-q'] + depth + ['origin', ref], check=True)
            run(['git', '-C', dest, 'checkout', '-q', '--detach', 'FETCH_HEAD'], check=True)
            head = rev_parse(dest, 'HEAD')
            manifest[name] = {'repo': repo, 'ref': ref, 'commit': head}
            log(f'{name}: {repo} {ref} at {head[:10]}')
    (repos_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1))


# ---------------------------------------------------------------------------
# install


def installed_components(repos_dir):
    """The commit of each clone at install time, with the repo and ref from the clone
    manifest when the manifest's commit is the one installed, so that the report describes
    the code that is in the venv even if a clone was changed after it was cloned."""
    manifest_path = repos_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    components = {}
    for name in COMPONENTS:
        dest = repos_dir / name
        head = subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True).stdout.strip()
        entry = manifest.get(name, {})
        if entry.get('commit') == head:
            components[name] = entry
        else:
            branch = subprocess.run(['git', '-C', str(dest), 'rev-parse', '--abbrev-ref', 'HEAD'],
                                    capture_output=True, text=True).stdout.strip()
            ref = None if branch in ('', 'HEAD') else branch
            components[name] = {'repo': None, 'ref': ref, 'commit': head}
    return components


def docs_requirements(repos_dir):
    """The requirements of the `docs` extras of the components, without the Qt bindings,
    and with one pin for each package: the pin that the most components give."""
    import tomllib

    pins = {}
    requirements = []
    for name in COMPONENTS:
        pyproject = repos_dir / name / 'pyproject.toml'
        if not pyproject.exists():
            continue
        extras = tomllib.loads(pyproject.read_text())['project'].get('optional-dependencies', {})
        for requirement in extras.get('docs', []):
            package = re.match(r'[A-Za-z0-9._-]+', requirement).group().lower().replace('_', '-')
            if package in QT_PACKAGES:
                continue
            if '==' in requirement:
                pins.setdefault(package, []).append(requirement.replace(' ', ''))
            elif requirement not in requirements:
                requirements.append(requirement)
    for package, given in pins.items():
        requirements.append(max(given, key=given.count))
    return requirements


def cmd_install(args):
    repos_dir = Path(args.repos_dir)
    venv = Path(args.venv or default_venv(args.python)).resolve()
    missing = [n for n in COMPONENTS if not (repos_dir / n).exists()]
    if missing:
        raise SystemExit(f'missing clones in {repos_dir}: {", ".join(missing)}; run clone first')
    if venv.exists():
        shutil.rmtree(venv)
    uv = uv_command()
    run(uv + ['venv', '-q', '--python', args.python, venv], check=True)
    py = venv_python(venv)
    env = dict(os.environ, SETUPTOOLS_SCM_PRETEND_VERSION=PRETEND_VERSION)
    requirements = [str(repos_dir / n) for n in COMPONENTS]
    requirements += QT_REQUIREMENTS[args.qt] + ['pytest', HARVESTERS_REQUIREMENT] + args.pin
    if args.docs:
        requirements += docs_requirements(repos_dir)
    result = run(uv + ['pip', 'install', '--python', py] + requirements, env=env)
    components = installed_components(repos_dir)
    version = subprocess.run([str(py), '-c', 'import platform; print(platform.python_version())'],
                             capture_output=True, text=True).stdout.strip()
    info = {
        'python': version or args.python,
        'qt': args.qt,
        'pins': args.pin,
        'docs': args.docs,
        'repos_dir': str(repos_dir.resolve()),
        'install_ok': result.returncode == 0,
        'components': components,
    }
    (venv / 'harness.json').write_text(json.dumps(info, indent=1))
    if result.returncode != 0:
        raise SystemExit('install failed')
    log(f'installed into {venv} with Python {version}')


# ---------------------------------------------------------------------------
# test


class StepResult:
    def __init__(self, name):
        self.name = name
        self.status = 'skipped'
        self.seconds = 0.0
        self.detail = ''


def step_env(info, work):
    env = dict(os.environ)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['LABSCRIPT_DISABLE_GRAPHICAL_EXCEPTHOOK'] = '1'
    env['QT_ENV'] = info['qt']
    env['HARNESS_WORK'] = str(work)
    env['HARNESS_REPOS'] = info['repos_dir']
    env['HARNESS_FIXTURES'] = str(HARNESS_DIR / 'fixtures')
    env['PYTHONUNBUFFERED'] = '1'
    return env


def kill_tree(proc):
    """End the process and the processes that it started."""
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def write_stacks_state(work, text):
    """Replace the file that tells the processes of every step which step is running and
    whether to write their stacks."""
    tmp = work / 'stacks-state.tmp'
    tmp.write_text(text)
    for _ in range(50):
        try:
            os.replace(tmp, work / 'stacks-state')
            return
        except PermissionError:
            # Windows: a process is reading the file.
            time.sleep(0.1)
    os.replace(tmp, work / 'stacks-state')


def run_step(name, py, env, work, timeout):
    script = CHECKS_DIR / ('check_' + name.replace('-', '_') + '.py')
    logfile = work / 'logs' / f'{name}.log'
    result = StepResult(name)
    t0 = time.time()
    stacks = work / 'logs' / f'{name}-stacks'
    stacks.mkdir(parents=True, exist_ok=True)
    env = dict(env)
    env['HARNESS_STACKS'] = str(stacks)
    env['HARNESS_STACKS_AT'] = str(t0 + timeout - STACKS_LEAD)
    env['HARNESS_STACKS_STATE'] = str(work / 'stacks-state')
    env['HARNESS_STEP'] = name
    write_stacks_state(work, f'{stacks}\n')
    env['PYTHONPATH'] = os.pathsep.join(
        [str(STACKDUMP_DIR)] + [p for p in [env.get('PYTHONPATH')] if p]
    )
    log(f'\n===== {name}')
    with open(logfile, 'w', encoding='utf8', errors='replace') as f:
        # The check is the leader of its own process group, so that the processes it
        # starts can be ended with it. On Windows, taskkill ends the tree instead.
        kwargs = {} if sys.platform == 'win32' else {'start_new_session': True}
        proc = subprocess.Popen([str(py), '-X', 'utf8', str(script)], cwd=work, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)

        def relay():
            for line in proc.stdout:
                text = line.decode('utf8', errors='replace')
                f.write(text)
                sys.stdout.write(text)
                sys.stdout.flush()

        # Output is relayed in a thread so that a check that hangs without exiting
        # is still subject to the timeout.
        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            write_stacks_state(work, f'{stacks}\ndump\n')
            time.sleep(STACKS_REQUEST_WAIT)
            kill_tree(proc)
            code = None
        # Processes that the check started and that are still running keep the pipe
        # open; wait briefly for the rest of the output and go on without it.
        reader.join(timeout=5)
        if code is None:
            for path in sorted(stacks.iterdir()):
                text = path.read_text(encoding='utf8', errors='replace')
                if text:
                    text = f'\n===== stacks of {path.stem}\n' + text
                    f.write(text)
                    sys.stdout.write(text)
        sys.stdout.flush()
    # On Windows, a process that was started by an earlier step and is still running
    # holds its file in that step's directory open until it reads the new state.
    if code is not None:
        PASSED_STACKS.append(stacks)
    for d in PASSED_STACKS:
        shutil.rmtree(d, ignore_errors=True)
    result.seconds = time.time() - t0
    if code == 0:
        result.status = 'passed'
    elif code is None:
        result.status = 'failed'
        result.detail = f'timed out after {timeout} s'
    else:
        result.status = 'failed'
        result.detail = f'exit code {code}'
    markers = logfile.read_text(encoding='utf8', errors='replace').splitlines()
    counts = [f'{n} {word.lower()}' for word in ['KNOWN', 'FIXED']
              if (n := sum(line.startswith(word + ' ') for line in markers))]
    result.detail = ', '.join([d for d in [result.detail] if d] + counts)
    log(f'===== {name}: {result.status} in {result.seconds:.0f} s {result.detail}')
    return result


def write_report(results, info, manifest, path):
    lines = [
        f"# labscript suite test harness report",
        '',
        f"Python {info['python']}, {info['qt']}, pins: {' '.join(info['pins']) or 'none'}, "
        f"platform {sys.platform}",
        '',
        '| Step | Result | Time | Detail |',
        '|---|---|---|---|',
    ]
    for r in results:
        lines.append(f'| {r.name} | {r.status} | {r.seconds:.0f} s | {r.detail} |')
    lines += ['', '| Component | Ref | Commit |', '|---|---|---|']
    for name, m in manifest.items():
        if m.get('heads'):
            ref = f"{m['repo']}@{describe_heads(m['heads'])} merged into {m['base'][:10]}"
        elif m.get('repo'):
            ref = f"{m['repo']}@{m['ref']}"
        else:
            ref = 'existing clone'
        lines.append(f"| {name} | {ref} | {m['commit'][:10]} |")
    for r in results:
        step_summary = path.parent / f'summary-{r.name}.md'
        if step_summary.exists():
            lines += ['', step_summary.read_text(encoding='utf8').rstrip()]
    text = '\n'.join(lines) + '\n'
    path.write_text(text)
    return text


def open_venv(args):
    """The interpreter and harness.json of the venv of the test or docs command, after
    checking that the clones have not changed since it was installed."""
    venv = Path(args.venv or default_venv(args.python)).resolve()
    py = venv_python(venv)
    if not py.exists():
        raise SystemExit(f'no virtual environment at {venv}; run install first')
    info = json.loads((venv / 'harness.json').read_text())
    repos_dir = Path(info['repos_dir'])
    changed = []
    for name, entry in info.get('components', {}).items():
        head = subprocess.run(['git', '-C', str(repos_dir / name), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True).stdout.strip()
        if head and head != entry['commit']:
            changed.append(f'{name} (installed {entry["commit"][:10]}, clone at {head[:10]})')
    if changed:
        raise SystemExit(f'the clones in {repos_dir} have changed since {venv} was installed: '
                         f'{", ".join(changed)}; run install again')
    return venv, py, info


def run_steps(args, venv, py, info, steps, selected):
    """Run the steps of `steps` that are in `selected`, write the report and exit with
    status 1 if a step failed."""
    manifest = info.get('components')
    if manifest is None:
        manifest_path = Path(info['repos_dir']) / 'manifest.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    work = Path(args.work or (venv.parent / f'work-{venv.name}')).resolve()
    if work.exists():
        shutil.rmtree(work)
    (work / 'logs').mkdir(parents=True)
    env = step_env(info, work)

    results = []
    passed = set()
    for name, needs in steps:
        if name not in selected:
            continue
        unmet = [n for n in needs if n not in passed and n in selected]
        if unmet or any(n not in selected and n in needs for n in needs):
            r = StepResult(name)
            r.detail = 'needs ' + ', '.join(needs)
            log(f'\n===== {name}: skipped ({r.detail})')
            results.append(r)
            continue
        r = run_step(name, py, env, work, args.timeout)
        results.append(r)
        if r.status == 'passed':
            passed.add(name)

    text = write_report(results, info, manifest, work / 'report.md')
    log('\n' + text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf8') as f:
            f.write(text)
    failed = [r for r in results if r.status == 'failed']
    sys.exit(1 if failed else 0)


def cmd_test(args):
    venv, py, info = open_venv(args)
    selected = [s for s, _ in STEPS]
    if args.step:
        selected = [s for s in selected if s in args.step]
    skip = set(args.skip) | (set() if args.step or args.all else set(DEFAULT_SKIP))
    selected = [s for s in selected if s not in skip]
    run_steps(args, venv, py, info, STEPS, selected)


def cmd_docs(args):
    venv, py, info = open_venv(args)
    if not info.get('docs'):
        raise SystemExit(f'{venv} was installed without the docs requirements; '
                         'run install with --docs')
    selected = [s for s, _ in DOCS_STEPS]
    if args.step:
        selected = [s for s in selected if s in args.step]
    run_steps(args, venv, py, info, DOCS_STEPS, selected)


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('clone', help='clone or update the component repositories')
    p.add_argument('--repos-dir', default=default_repos_dir())
    p.add_argument('spec', nargs='*',
                   help='name=[owner/repo@]ref, ref a branch, tag, commit or pr/N; '
                        'several refs for one name are merged in turn')
    p.set_defaults(func=cmd_clone)

    p = sub.add_parser('install', help='make a virtual environment and install the components')
    p.add_argument('--python', required=True, help='version for uv, or a path to an interpreter')
    p.add_argument('--venv', help=f'default harness/venvs/py<python>')
    p.add_argument('--repos-dir', default=default_repos_dir())
    p.add_argument('--qt', default='PySide6', choices=QT_BINDINGS)
    p.add_argument('--pin', action='append', default=[], metavar='REQUIREMENT',
                   help='extra requirement, for example "numpy<2.5"; repeatable')
    p.add_argument('--docs', action='store_true',
                   help='also install the requirements of the docs extras of the components')
    p.set_defaults(func=cmd_install)

    p = sub.add_parser('test', help='run the checks in a virtual environment made by install')
    p.add_argument('--python', help='version given to install, to find the default venv')
    p.add_argument('--venv')
    p.add_argument('--work', help='directory for logs, the shot files and the report')
    p.add_argument('--step', action='append', default=[], choices=[s for s, _ in STEPS],
                   help='run only these steps; repeatable')
    p.add_argument('--skip', action='append', default=[], choices=[s for s, _ in STEPS],
                   help=f'skip these steps; by default {", ".join(DEFAULT_SKIP)}')
    p.add_argument('--all', action='store_true', help='also run the steps skipped by default')
    p.add_argument('--timeout', type=int, default=900, help='seconds per step')
    p.set_defaults(func=cmd_test)

    p = sub.add_parser('docs', help='build the docs of the components and compile their '
                                    'example scripts in a venv made by install --docs')
    p.add_argument('--python', help='version given to install, to find the default venv')
    p.add_argument('--venv')
    p.add_argument('--work', help='directory for logs, the built docs and the report')
    p.add_argument('--step', action='append', default=[], choices=[s for s, _ in DOCS_STEPS],
                   help='run only these steps; repeatable')
    p.add_argument('--timeout', type=int, default=1800, help='seconds per step')
    p.set_defaults(func=cmd_docs)

    args = parser.parse_args()
    if args.command in ('install', 'test', 'docs') and not args.venv and not args.python:
        parser.error('--python or --venv is required')
    args.func(args)


if __name__ == '__main__':
    main()
