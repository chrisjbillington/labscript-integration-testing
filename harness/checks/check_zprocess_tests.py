"""Run the zprocess test suite from its clone."""

import subprocess
import sys

from _common import REPOS, check, finish

result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', 'tests'],
                        cwd=REPOS / 'zprocess')
check(result.returncode == 0, f'zprocess tests exit code {result.returncode}')
finish()
