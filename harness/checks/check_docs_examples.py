"""Compile the example experiment scripts in the docs of the components. In the Sphinx
source directory of each component that has a Read the Docs configuration, these are the
examples: each Python code block of a .rst or .md file, each literal block (`::`) of a
.rst file in which the highlight language is Python, each .py file that a literalinclude
directive includes, and each .py file other than conf.py. An example that contains both
`start()` and `stop(` is an experiment script and is compiled, unless the line before
it is the comment `.. fragment` (`<!-- fragment -->` in a .md file). The other examples
are fragments and are listed but not compiled. labscript's example.py is compiled as well.
Each script is compiled through runmanager as a single shot with no globals, and the step
fails if one does not compile."""

import re
from pathlib import Path

import zmq

from _common import REPOS, SHOTS, WORK, check, finish, labconfig, sphinx_configuration

import runmanager
from labscript_utils.ls_zprocess import Context

# Scripts that are compiled in addition to those in the docs, relative to the clones.
EXTRA_SCRIPTS = ['labscript/example.py']

PYTHON_LANGUAGES = {'python', 'python3', 'py'}
RST_CODE = re.compile(r'^(\s*)\.\. (code-block|code|sourcecode)::\s*(\S*)\s*$')
RST_INCLUDE = re.compile(r'^(\s*)\.\. literalinclude::\s*(\S+)\s*$')
RST_HIGHLIGHT = re.compile(r'^\s*\.\. highlight::\s*(\S+)\s*$')
MD_FENCE = re.compile(r'^(\s*)(```+|~~~+)\s*(\{(code-block|code|sourcecode|literalinclude)\})?\s*(\S*)\s*$')
RST_FRAGMENT = re.compile(r'^\s*\.\. fragment\s*$')
MD_FRAGMENT = re.compile(r'^\s*<!--\s*fragment\s*-->\s*$')
EXCLUDED_DIRS = {'_build', '_autosummary', '_apidoc', 'build'}

config = labconfig()

# The compiler's output is streamed to a PULL socket. The socket must come from the
# labscript_utils Context so that it has the labconfig security settings.
pull = Context.instance().socket(zmq.PULL)
stream_port = pull.bind_to_random_port('tcp://127.0.0.1')


def is_script(code):
    return 'start()' in code and 'stop(' in code


def marked(lines, i, pattern):
    """Whether the last nonblank line before line i is a fragment comment."""
    for line in reversed(lines[:i]):
        if line.strip():
            return bool(pattern.match(line))
    return False


def included(source_dir, document, target):
    """The path of a literalinclude target, which is relative to the document or, if it
    starts with /, to the source directory."""
    if target.startswith('/'):
        return source_dir / target.lstrip('/')
    return document.parent / target


def rst_blocks(source_dir, path):
    """(line, code or path, marked as a fragment) of each Python code block, Python
    literal block and literalinclude of a .py file."""
    lines = path.read_text(encoding='utf8').splitlines()
    highlight = 'python'
    for i, line in enumerate(lines):
        include = RST_INCLUDE.match(line)
        if include and include.group(2).endswith('.py'):
            yield i + 1, included(source_dir, path, include.group(2)), marked(
                lines, i, RST_FRAGMENT)
            continue
        language = RST_HIGHLIGHT.match(line)
        if language:
            highlight = language.group(1)
            continue
        code = RST_CODE.match(line)
        if code:
            if (code.group(3) or highlight) not in PYTHON_LANGUAGES | {'default'}:
                continue
        elif not (line.rstrip().endswith('::') and not line.lstrip().startswith('..')
                  and highlight in PYTHON_LANGUAGES | {'default'}):
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for following in lines[i + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        while body and (not body[0].strip() or body[0].strip().startswith(':')):
            body.pop(0)
        if not body:
            continue
        dedent = min(len(b) - len(b.lstrip()) for b in body if b.strip())
        code = '\n'.join(b[dedent:] for b in body).strip() + '\n'
        yield i + 1, code, marked(lines, i, RST_FRAGMENT)


def md_blocks(source_dir, path):
    """(line, code or path, marked as a fragment) of each Python code fence and
    literalinclude of a .py file."""
    lines = path.read_text(encoding='utf8').splitlines()
    i = 0
    while i < len(lines):
        fence = MD_FENCE.match(lines[i])
        if not fence or not (fence.group(3) or fence.group(5)):
            i += 1
            continue
        start = i
        body = []
        i += 1
        while i < len(lines) and not lines[i].strip().startswith(fence.group(2)):
            body.append(lines[i])
            i += 1
        i += 1
        directive, argument = fence.group(4), fence.group(5)
        if directive == 'literalinclude':
            if argument.endswith('.py'):
                yield start + 1, included(source_dir, path, argument), marked(
                    lines, start, MD_FRAGMENT)
        elif argument in PYTHON_LANGUAGES:
            body = [b for b in body if not b.startswith(':')]
            yield start + 1, '\n'.join(body).strip() + '\n', marked(lines, start, MD_FRAGMENT)


def examples(source_dir):
    """(location, code, path of the code if it is a file, marked as a fragment) of each
    example in the docs."""
    for path in sorted(source_dir.rglob('*')):
        if EXCLUDED_DIRS & set(path.relative_to(source_dir).parts) or not path.is_file():
            continue
        relative = path.relative_to(REPOS).as_posix()
        if path.suffix == '.py' and path.name != 'conf.py':
            yield relative, path.read_text(encoding='utf8'), path, False
        elif path.suffix in ('.rst', '.md'):
            blocks = rst_blocks if path.suffix == '.rst' else md_blocks
            for line, block, fragment in blocks(source_dir, path):
                if isinstance(block, Path):
                    location = f'{relative}:{line} ({block.relative_to(REPOS).as_posix()})'
                    yield location, block.read_text(encoding='utf8'), block, fragment
                else:
                    yield f'{relative}:{line}', block, None, fragment


def compiler_output():
    """The output that the compiler has streamed since the last call."""
    output = []
    while pull.poll(500):
        output.append(pull.recv_multipart()[-1])
    return b''.join(output).decode('utf8', errors='replace')


def compile_script(script, run_file):
    results = []
    runmanager.compile_labscript_async(str(script), str(run_file), stream_port=stream_port,
                                       done_callback=results.append)
    output = compiler_output()
    print(output, flush=True)
    if results != [True]:
        lines = [line for line in output.splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else 'compilation failed')


def compile_example(location, code, path):
    """Compile an example and return the error, or None if it compiled."""
    stem = re.sub(r'[^A-Za-z0-9]+', '_', location).strip('_')
    if path is None:
        path = WORK / 'docs-examples' / f'{stem}.py'
        path.write_text(code, encoding='utf8')
    run_file = SHOTS / 'docs-examples' / f'{stem}.h5'
    sequence_attrs, _, _ = runmanager.new_sequence_details(str(path), config=config,
                                                           increment_sequence_index=False)
    runmanager.make_single_run_file(str(run_file), {}, {}, sequence_attrs, 0, 1)
    try:
        compile_script(path, run_file)
    except RuntimeError as e:
        check(False, f'{location} compiles: {e}')
        return str(e)
    check(True, f'{location} compiles')
    return None


(WORK / 'docs-examples').mkdir(parents=True, exist_ok=True)
(SHOTS / 'docs-examples').mkdir(parents=True, exist_ok=True)
compiled = []
fragments = []
for repo in sorted(REPOS.iterdir()):
    conf = repo.is_dir() and sphinx_configuration(repo)
    if not conf:
        continue
    for location, code, path, fragment in examples((repo / conf).parent):
        if is_script(code) and not fragment:
            compiled.append((location, compile_example(location, code, path)))
        else:
            fragments.append(location)
for extra in EXTRA_SCRIPTS:
    path = REPOS / extra
    check(path.exists(), f'{extra} exists')
    if path.exists():
        compiled.append((extra, compile_example(extra, path.read_text(encoding='utf8'), path)))

print(f'\n{len(fragments)} fragments, not compiled:', flush=True)
for location in fragments:
    print(f'  {location}', flush=True)

lines = [
    '## Docs examples',
    '',
    f'{sum(error is None for _, error in compiled)} of {len(compiled)} example scripts '
    f'compile; {len(fragments)} examples are fragments and are not compiled.',
    '',
    '| Example script | Compiles |',
    '|---|---|',
]
for location, error in compiled:
    result = 'yes' if error is None else 'no: `' + error.replace('|', '\\|').replace('`', "'") + '`'
    lines.append(f'| {location} | {result} |')
(WORK / 'summary-docs-examples.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
finish()
