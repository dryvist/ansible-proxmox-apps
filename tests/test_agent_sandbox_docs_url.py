"""The public docs checkout only accepts credential-free HTTPS URLs."""

from pathlib import Path
import unittest
from urllib.parse import urlsplit

import yaml

DOCS_TASKS = (
    Path(__file__).resolve().parents[1]
    / "roles"
    / "agent_sandbox"
    / "tasks"
    / "main"
    / "docs.yml"
)


def docs_repository_url_guards():
    task = yaml.safe_load(DOCS_TASKS.read_text(encoding="utf-8"))[0]
    assertions = task["ansible.builtin.assert"]["that"]
    return [
        assertion
        for assertion in assertions
        if "agent_sandbox_docs_repository_url" in assertion
    ]


def accepted_by_guards(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and "@" not in parts.netloc


class DocsRepositoryUrl(unittest.TestCase):
    def test_task_requires_https_without_userinfo(self):
        guards = docs_repository_url_guards()
        self.assertEqual(
            guards,
            [
                "agent_sandbox_docs_repository_url | urlsplit('scheme') == 'https'",
                "'@' not in (agent_sandbox_docs_repository_url | urlsplit('netloc'))",
            ],
        )

    def test_userinfo_url_is_refused(self):
        self.assertFalse(accepted_by_guards("https://user@/public/docs.git"))

    def test_non_https_url_is_refused(self):
        self.assertFalse(accepted_by_guards("http:///public/docs.git"))

    def test_https_url_without_userinfo_passes_the_guard(self):
        self.assertTrue(accepted_by_guards("https:///public/docs.git"))

    def test_failure_message_recommends_supported_credentials(self):
        task = yaml.safe_load(DOCS_TASKS.read_text(encoding="utf-8"))[0]
        message = task["ansible.builtin.assert"]["fail_msg"]
        self.assertIn("credential helper", message)


if __name__ == "__main__":
    unittest.main()
