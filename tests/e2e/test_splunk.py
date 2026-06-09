"""Splunk component tests for the logging pipeline."""

import time
import urllib.error
import uuid

import pytest

from .helpers import post_splunk_hec, query_splunk, splunk_hec_health, wait_for_event


class TestSplunkComponent:
    """Validate Splunk independently of HAProxy and Cribl."""

    def test_management_export_query_works(self, splunk_creds):
        """Verify the search/jobs/export endpoint accepts an authenticated query."""
        mgmt_url, user, password = splunk_creds
        try:
            results = query_splunk(
                mgmt_url,
                user,
                password,
                "| makeresults | eval e2e_component=\"splunk-export\"",
                earliest=None,
                timeout=30,
                raise_errors=True,
            )
        except (urllib.error.URLError, OSError) as exc:
            pytest.fail(f"Splunk management export query failed at {mgmt_url}: {exc}")

        assert results, "Splunk export query returned no results"
        assert results[0].get("e2e_component") == "splunk-export"

    def test_hec_health_endpoint(self, splunk_hec_url):
        """Verify Splunk HEC reports healthy."""
        status, body = splunk_hec_health(splunk_hec_url)
        assert status == 200, f"Splunk HEC health returned {status}: {body}"

    def test_direct_hec_event_is_searchable(
        self,
        splunk_creds,
        splunk_hec_url,
        splunk_hec_token,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """POST directly to HEC and verify the sentinel is searchable."""
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-hec-{uuid.uuid4().hex[:12]}-{int(time.time())}"
        status, body = post_splunk_hec(
            splunk_hec_url,
            splunk_hec_token,
            f"E2E direct HEC sentinel: {sentinel}",
            index="main",
            sourcetype="e2e:hec:test",
        )

        assert status == 200, f"Splunk HEC POST returned {status}: {body}"
        assert "Success" in body or '"code":0' in body, (
            f"Splunk HEC POST did not return a success body: {body}"
        )

        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index="main",
            sourcetype="e2e:hec:test",
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, f"Direct HEC sentinel {sentinel} was not searchable"
