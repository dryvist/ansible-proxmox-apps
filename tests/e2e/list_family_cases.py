"""Print the ingest family E2E matrix as JSON: one case per family.

The old CI job ran every family's test sequentially in one job and blew its
20-minute timeout once enough AI sources were live. This prints one case per
family so the workflow can run them as parallel `strategy.matrix` entries
instead, each with its own timeout.

Reuses the same family lists the tests themselves parametrize on
(``fixtures.SYSLOG_SOURCE_IDS`` / ``fixtures.AI_SOURCE_IDS``, both derived
from the live OpenTofu inventory) so there is no second family list to keep
in sync.
"""

import json

from .fixtures import AI_SOURCE_IDS, SYSLOG_SOURCE_IDS

_FILE = "tests/e2e/test_family_matrix.py"


def cases():
    for key in SYSLOG_SOURCE_IDS:
        yield {
            "name": f"syslog:{key}",
            "nodeid": f"{_FILE}::TestSyslogFamilyMatrix::test_family_sentinel_lands_in_index[{key}]",
        }
    for key in AI_SOURCE_IDS:
        yield {
            "name": f"ai:{key}",
            "nodeid": f"{_FILE}::TestAiFamilyMatrix::test_ai_sentinel_lands_in_index[{key}]",
        }


if __name__ == "__main__":
    print(json.dumps(list(cases())))
