from __future__ import absolute_import, unicode_literals

import logging
import os
import sys

import six

from virtualenv.info import IS_WIN

from .discover import Discover
from .py_info import CURRENT, PythonInfo
from .py_spec import PythonSpec


class Builtin(Discover):
    def __init__(self, options):
        super(Builtin, self).__init__()
        self.python_spec = options.python

    @classmethod
    def add_parser_arguments(cls, parser):
        parser.add_argument(
            "-p",
            "--python",
            dest="python",
            metavar="py",
            help="target interpreter for which to create a virtual (either absolute path or identifier string)",
            default=sys.executable,
        )

    def run(self):
        return get_interpreter(self.python_spec)

    def __repr__(self):
        return six.ensure_str(self.__unicode__())

    def __unicode__(self):
        return "{} discover of python_spec={!r}".format(self.__class__.__name__, self.python_spec)


def get_interpreter(key):
    spec = PythonSpec.from_string_spec(key)
    logging.info("find interpreter for spec %r", spec)
    proposed_paths = set()
    for interpreter, impl_must_match in propose_interpreters(spec):
        if interpreter.executable not in proposed_paths:
            logging.info("proposed %s", interpreter)
            if interpreter.satisfies(spec, impl_must_match):
                logging.debug("accepted target interpreter %s", interpreter)
                return interpreter
            proposed_paths.add(interpreter.executable)


def propose_interpreters(spec):
    # 1. we always try with the lowest hanging fruit first, the current interpreter
    yield CURRENT, True

    # 2. if it's an absolute path and exists, use that
    if spec.is_abs and os.path.exists(spec.path):
        yield PythonInfo.from_exe(spec.path), True

    # 3. otherwise fallback to platform default logic
    if IS_WIN:
        from .windows import propose_interpreters

        for interpreter in propose_interpreters(spec):
            yield interpreter, True

    paths = get_paths()
    # find on path, the path order matters (as the candidates are less easy to control by end user)
    tested_exes = set()
    for pos, path in enumerate(paths):
        path = six.ensure_text(path)
        logging.debug(LazyPathDump(pos, path))
        for candidate, match in possible_specs(spec):
            found = check_path(candidate, path)
            if found is not None:
                exe = os.path.abspath(found)
                if exe not in tested_exes:
                    tested_exes.add(exe)
                    interpreter = PathPythonInfo.from_exe(exe, raise_on_error=False)
                    if interpreter is not None:
                        yield interpreter, match


def get_paths():
    path = os.environ.get(str("PATH"), None)
    if path is None:
        try:
            path = os.confstr("CS_PATH")
        except (AttributeError, ValueError):
            path = os.defpath
    if not path:
        paths = []
    else:
        paths = [p for p in path.split(os.pathsep) if os.path.exists(p)]
    return paths


class LazyPathDump(object):
    def __init__(self, pos, path):
        self.pos = pos
        self.path = path

    def __repr__(self):
        return six.ensure_str(self.__unicode__())

    def __unicode__(self):
        content = "discover PATH[{}]={}".format(self.pos, self.path)
        if os.environ.get(str("_VIRTUALENV_DEBUG")):  # this is the over the board debug
            content += " with =>"
            for file_name in os.listdir(self.path):
                try:
                    file_path = os.path.join(self.path, file_name)
                    if os.path.isdir(file_path) or not os.access(file_path, os.X_OK):
                        continue
                except OSError:
                    pass
                content += " "
                content += file_name
        return content


def check_path(candidate, path):
    _, ext = os.path.splitext(candidate)
    if sys.platform == "win32" and ext != ".exe":
        candidate = candidate + ".exe"
    if os.path.isfile(candidate):
        return candidate
    candidate = os.path.join(path, candidate)
    if os.path.isfile(candidate):
        return candidate
    return None


def possible_specs(spec):
    # 4. then maybe it's something exact on PATH - if it was direct lookup implementation no longer counts
    yield spec.str_spec, False
    # 5. or from the spec we can deduce a name on path  that matches
    for exe, match in spec.generate_names():
        yield exe, match


class PathPythonInfo(PythonInfo):
    """"""