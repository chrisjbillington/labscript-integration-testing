"""Build the Sphinx docs of every component that has a Read the Docs configuration, as
Read the Docs builds the latest version: with the dirhtml builder, in the directory of
conf.py, and with READTHEDOCS=True and READTHEDOCS_VERSION=latest. The builds are also
nitpicky. Each component is copied without its git directory to docs/src/ in the work
directory and built there, since a build writes files into the source tree. The step
fails if a build exits with a nonzero status, and reports the number of warnings of each
build without failing on them. Warnings that are not "reference target not found" are
written out in full."""

import os
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from importlib.metadata import PackageNotFoundError, version

import tomllib
from packaging.requirements import Requirement

from _common import REPOS, WORK, check, finish, sphinx_configuration

SRC = WORK / 'docs' / 'src'
OUT = WORK / 'docs' / 'html'
WARNING = re.compile(r'(^|: )(WARNING|ERROR|CRITICAL|SEVERE): ')
NITPICK = 'reference target not found'
SITE_PACKAGES = sysconfig.get_paths()['purelib']
ENV = dict(os.environ, READTHEDOCS='True', READTHEDOCS_VERSION='latest')


def unmet_docs_requirements(repo):
    """The requirements of the docs extra of the repository that the venv does not meet."""
    pyproject = tomllib.loads((repo / 'pyproject.toml').read_text())
    unmet = []
    for text in pyproject['project'].get('optional-dependencies', {}).get('docs', []):
        requirement = Requirement(text)
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            unmet.append(f'{text} (not installed)')
            continue
        if not requirement.specifier.contains(installed, prereleases=True):
            unmet.append(f'{text} ({installed} installed)')
    return unmet


def read_warnings(path, root):
    """The warnings in a Sphinx warning file, each with its continuation lines, with the
    paths made relative to the root of the copied repository and to site-packages."""
    warnings = []
    for line in path.read_text(encoding='utf8', errors='replace').splitlines():
        for prefix in [str(root), SITE_PACKAGES]:
            line = line.replace(prefix + os.sep, '').replace(prefix + '/', '')
        if WARNING.search(line) or not warnings:
            warnings.append(line)
        else:
            warnings[-1] += '\n' + line
    return [w for w in warnings if w.strip()]


components = [d.name for d in sorted(REPOS.iterdir()) if d.is_dir() and sphinx_configuration(d)]
results = []
for name in components:
    repo = REPOS / name
    root = SRC / name
    shutil.copytree(repo, root, ignore=shutil.ignore_patterns('.git'))
    conf_dir = (root / sphinx_configuration(repo)).parent
    warning_file = WORK / 'logs' / f'docs-{name}-warnings.txt'
    print(f'\n--- {name}', flush=True)
    t0 = time.time()
    with open(WORK / 'logs' / f'docs-{name}.log', 'w', encoding='utf8', errors='replace') as log:
        code = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'sphinx', '-b', 'dirhtml', '-n',
                               '-d', str(WORK / 'docs' / 'doctrees' / name), '-w', str(warning_file),
                               '.', str(OUT / name)],
                              cwd=conf_dir, env=ENV, stdout=log, stderr=subprocess.STDOUT).returncode
    seconds = time.time() - t0
    warnings = read_warnings(warning_file, root) if warning_file.exists() else []
    other = [w for w in warnings if NITPICK not in w]
    unmet = unmet_docs_requirements(repo)
    check(code == 0, f'{name}: the docs build exits with status {code} in {seconds:.0f} s, '
                     f'with {len(warnings)} warnings, {len(other)} of which are not '
                     f'"{NITPICK}"')
    for requirement in unmet:
        print(f'{name}: the docs extra requires {requirement}', flush=True)
    for warning in other:
        print(warning, flush=True)
    results.append((name, code, seconds, warnings, other, unmet))

lines = [
    '## Docs builds',
    '',
    f'Built with `-b dirhtml -n`. "Other warnings" are the warnings that are not '
    f'"{NITPICK}".',
    '',
    '| Component | Exit status | Time | Warnings | Other warnings | Docs extra not met |',
    '|---|---|---|---|---|---|',
]
for name, code, seconds, warnings, other, unmet in results:
    lines.append(f'| {name} | {code} | {seconds:.0f} s | {len(warnings)} | {len(other)} | '
                 f'{"<br>".join(unmet)} |')
for name, code, seconds, warnings, other, unmet in results:
    if other:
        lines += ['', f'<details><summary>{name}: {len(other)} other warnings</summary>', '',
                  '```', *other, '```', '', '</details>']
(WORK / 'summary-docs.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
finish()
