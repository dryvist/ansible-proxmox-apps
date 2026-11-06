"""Fail closed unless inference is configured as a direct private IP endpoint."""

from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit


def validate(config):
    if not isinstance(config, dict) or set(config) != {"splunk_url", "local_model_url", "state_path"}:
        raise ValueError("splunktriage requires splunk_url, local_model_url, and state_path")
    for key in ("splunk_url", "local_model_url"):
        url = urlsplit(config[key])
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError(f"splunktriage {key} must be an absolute URL without credentials")
        if key == "splunk_url" and url.scheme != "https":
            raise ValueError("splunktriage requires HTTPS for Splunk")
        if key == "local_model_url":
            try:
                address = ip_address(url.hostname)
            except ValueError:
                raise ValueError("splunktriage requires a direct local model IP") from None
            if not address.is_private or address.is_unspecified or address.is_multicast:
                raise ValueError("splunktriage requires a direct local model IP")
    if not isinstance(config["state_path"], str) or not Path(config["state_path"]).is_absolute():
        raise ValueError("splunktriage state_path must be absolute")
