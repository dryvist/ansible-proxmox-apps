"""An env lookup guarded only by `mandatory` is not guarded at all.

`lookup('env', 'NAME')` returns an EMPTY STRING when the variable is unset --
never Undefined. `mandatory` raises only on Undefined, so it can never fire on
an env lookup. The guard reads as fail-closed and is fail-open: the empty value
renders straight into whatever consumed it and the task reports success.

Measured on ansible-core 2.21, with the variable unset:

    {{ lookup('env','X') | mandatory('must be set') }}   -> ""   task OK
    {{ lookup('env','X')
       | default(undef('X is empty'), true)
       | mandatory('must be set') }}                     -> task FAILS

`default(..., true)` treats an empty string as missing and substitutes
`undef()`, which is the Undefined that `mandatory` can finally see. A value
that IS set passes through untouched, so correcting a site moves no rendered
output.

Why this matters more than a style rule: most of these sites are credentials.
A database password or an API key that renders empty produces a converge that
succeeds while deploying a service configured with no password at all -- or,
for a key-gated feature, one that silently takes the "unkeyed" branch. The
dangerous direction fails silent; the harmless one fails loud.

The scan MUST span line breaks. These expressions are wrapped with a filter on
its own continuation line, so a single-line grep finds only a small fraction of
them and makes a partial sweep look complete.
"""

from __future__ import annotations

import re
from pathlib import Path

ROLES = Path(__file__).resolve().parent.parent / "roles"
SUFFIXES = {".yml", ".yaml", ".j2"}

# An env lookup, then anything up to the `mandatory` filter, across newlines.
# Bounded so it cannot run past the end of one Jinja expression.
DEAD_GUARD = re.compile(
    r"lookup\(\s*['\"](?:ansible\.builtin\.)?env['\"]\s*,\s*['\"](?P<var>[A-Z0-9_]+)['\"]\s*\)"
    r"(?P<between>(?:[^}]{0,200}?))\|\s*mandatory\(",
    re.S,
)


def _sites():
    for path in sorted(ROLES.rglob("*")):
        if path.suffix not in SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in DEAD_GUARD.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield path, line, match.group("var"), match.group("between")


def test_no_env_lookup_relies_on_mandatory_alone():
    """Every `mandatory` on an env lookup must be preceded by `default(undef(...), true)`."""
    offenders = [
        f"{path.relative_to(ROLES.parent)}:{line} {var}"
        for path, line, var, between in _sites()
        if "undef(" not in between
    ]
    assert not offenders, (
        "These env lookups are guarded only by `mandatory`, which cannot fire on "
        "an env lookup -- an unset variable renders empty and the converge stays "
        "green. Insert `| default(undef('<VAR> is empty'), true)` before the "
        "`mandatory` filter:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_can_actually_see_a_violation():
    """Anti-vacuity: a passing scan must mean 'none found', not 'nothing scanned'.

    Without this, deleting the roles directory or breaking the pattern would make
    the test above pass for the wrong reason -- the failure mode the guard it
    checks for suffers from, one level up.
    """
    sample = (
        "foo: >-\n"
        "  {{ lookup('env', 'SOME_SECRET')\n"
        "  | mandatory('SOME_SECRET must be set') }}\n"
    )
    match = DEAD_GUARD.search(sample)
    assert match is not None, "the pattern no longer matches a known-bad wrapped site"
    assert match.group("var") == "SOME_SECRET"
    assert "undef(" not in match.group("between")

    fixed = sample.replace(
        "  | mandatory(", "  | default(undef('SOME_SECRET is empty'), true)\n  | mandatory("
    )
    fixed_match = DEAD_GUARD.search(fixed)
    assert fixed_match is not None
    assert "undef(" in fixed_match.group("between"), "the corrected form must read as guarded"


def test_scan_reaches_a_representative_number_of_sites():
    """A scan that suddenly sees almost nothing is broken, not clean."""
    assert len(list(_sites())) >= 5, "the scan found too few sites to be working"
