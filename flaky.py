"""
Flake8 API for github diffs.

TODO:
    - unsure if pyflakes works with this.

"""

import os
import sys
from cStringIO import StringIO
import difflib

from flake8.engine import get_parser, get_style_guide, StyleGuide, _flake8_noqa
from pep8 import DiffReport, HUNK_REGEX, filename_match , parse_udiff
import requests
from unidiff import parse_unidiff

from .github import get_pull_request


def parse_ghdiff(diff):
    """Replacement for ``pep8.parse_udiff``.
    Bug: blank lines aren't included in the resultant list
    of "which lines should flake8 check", which may
    skew results.
    """
    s = StringIO(diff)
    rv = {}
    patchset = parse_unidiff(s)
    for pfile in patchset:
        fn = './' + pfile.path
        rv[fn] = []
        for hunk in pfile:
            for idx, line in enumerate(hunk.target_lines):
                if line not in hunk.source_lines:
                    rv[fn].append(hunk.target_start + idx)
                
    return rv

from contextlib import contextmanager
@contextmanager
def stdout_redirect(buf):
    _stdout = sys.stdout
    sys.stdout = buf
    try:
        yield None
    finally:
        sys.stdout = _stdout


class DiffAwareCapturingStyleGuide(StyleGuide):
    """PEP8 StyleGuide that allows us to force a DiffReport
    without relying on the pep8 module's parameter handling
    to enable one.
    (flake8 bypasses pep8's parameter handling)
    Additionally captures the pep8 output and returns it to
    the caller, rather than just printing it to the screen.
    (there *has* to be a better way to do this)
    This breaks the contract of the `input_file()` method,
    so this class is not interoperable with the rest
    of flake/pep8.
    """
    def input_file(self, filename, lines, diff):
        """Run all checks on lines of code present in diff.""" 
        self.options.selected_lines = parse_ghdiff(diff)
        fchecker = self.checker_class(
            filename, lines=lines, report=DiffReport(self.options), options=self.options
        )
        # Any "# flake8: noqa" line?
        if any(_flake8_noqa(line) for line in fchecker.lines):
            return 0

        # patch stdout before calling into pep8
        capture = StringIO()
        with stdout_redirect(capture):
            cnt = fchecker.check_all()
            
        return cnt, capture.getvalue()
        #_stdout = sys.stdout
        #sys.stdout = output = StringIO()
        #try:
        #    cnt = fchecker.check_all()
        #finally:
        #    sys.stdout = _stdout
        #
        #return cnt, output.getvalue()


def pullrequest_flake8_check(url, org, repo, number, token):
    """Run a flake8 check on a pull request."""
    pr = get_pull_request(url, org, repo, number, token)
    diff = pr.diff()  

    # github is being flaky; consume the generator
    pullfiles = list(pr.iter_files()) 
    for pullfile in pullfiles:  #pr.iter_files():
        path = pullfile.filename
        if not path.endswith('.py'):  # TODO
            continue
        try:
            resp = requests.get(pullfile.raw_url)
            resp.raise_for_status()
        except requests.RequestException as ex:
            # TODO
            print str(ex)
            break
        else:
            flake8_style = DiffAwareCapturingStyleGuide(ignore=['E501'])
            count, results = flake8_style.input_file(
                #  '.' since there is no base path for github diff
                './{}'.format(path), 
                resp.content.splitlines(True),
                diff
            )
            yield path, count, results.splitlines()


