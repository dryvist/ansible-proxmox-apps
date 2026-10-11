"""Fetch and validate physical-drive rows from the Proxmox VE API."""
from __future__ import annotations

import http.client
import json
import os
import ssl
import urllib.parse
import urllib.request

_CONFIG = (
    "NAUTOBOT_PROXMOX_API_URL",
    "NAUTOBOT_PROXMOX_TOKEN_ID",
    "NAUTOBOT_PROXMOX_TOKEN_SECRET",
    "NAUTOBOT_PROXMOX_CA",
)
_EXCLUDED_TYPES = {"usb"}


class ProxmoxDiskClient:
    """Return rows only after every online node has a non-empty disk list."""

    def __init__(self, url: str, token_id: str, token_secret: str, ca_pem: str):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("NAUTOBOT_PROXMOX_API_URL must be an HTTPS URL.")
        self.url = url.rstrip("/")
        self.authorization = f"PVEAPIToken={token_id}={token_secret}"
        try:
            self.context = ssl.create_default_context(cadata=ca_pem)
        except (OSError, ValueError, TypeError):
            raise ValueError("NAUTOBOT_PROXMOX_CA must contain a valid PEM certificate.") from None

    @classmethod
    def from_env(cls) -> ProxmoxDiskClient:
        """Build a client or name every unset required environment variable."""
        values = {name: os.environ.get(name, "") for name in _CONFIG}
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise ValueError("Missing required Proxmox configuration: " + ", ".join(missing))
        return cls(
            values[_CONFIG[0]].strip(),
            values[_CONFIG[1]].strip(),
            values[_CONFIG[2]].strip(),
            # An EnvironmentFile may keep the PEM's newlines as literal \n; PEM
            # never contains a backslash, so this is a no-op otherwise.
            values[_CONFIG[3]].replace("\\n", "\n"),
        )

    def rows(self) -> list[dict]:
        """Read the full cluster before returning any source rows."""
        nodes = self._get("/nodes")
        if not nodes:
            raise ValueError("Proxmox returned no nodes; refusing to sync drives.")
        for node in nodes:
            if not isinstance(node, dict) or not isinstance(node.get("node"), str):
                raise TypeError("Proxmox returned a node without a name; refusing to sync drives.")
            if node.get("status") != "online":
                raise ValueError(
                    f"Proxmox node {node['node']!r} is not online; refusing to sync drives."
                )

        rows = []
        for node in nodes:
            name = node["node"].strip()
            if not name:
                raise ValueError("Proxmox returned an empty node name; refusing to sync drives.")
            disks = self._get(f"/nodes/{urllib.parse.quote(name, safe='')}/disks/list")
            if not disks:
                raise ValueError(
                    f"Proxmox node {name!r} returned zero disks; refusing to sync drives."
                )
            for disk in disks:
                if not isinstance(disk, dict):
                    raise TypeError(
                        f"Proxmox node {name!r} returned an invalid disk row; refusing to sync drives."
                    )
                if disk.get("type") not in _EXCLUDED_TYPES:
                    rows.append({**disk, "node": name})
        if not rows:
            raise ValueError("Proxmox returned no non-USB disks; refusing to sync drives.")
        return rows

    def _get(self, path: str) -> list:
        """GET one JSON API path without exposing credentials on failure."""
        request = urllib.request.Request(
            self.url + "/api2/json" + path,
            headers={"Authorization": self.authorization},
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=30) as response:
                payload = json.loads(response.read())
        except (OSError, ValueError, TypeError, http.client.HTTPException) as exc:
            raise ValueError(
                f"Proxmox API GET {path} failed ({type(exc).__name__}); refusing to sync drives."
            ) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise TypeError(f"Proxmox API GET {path} returned invalid data; refusing to sync drives.")
        return payload["data"]
