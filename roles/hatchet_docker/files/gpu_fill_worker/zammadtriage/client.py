"""Private JSON transport and the limited Zammad write surface."""

import ipaddress
import json
import os
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_url(url, local=False):
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("invalid service URL")
    if local:
        address = ipaddress.ip_address(parsed.hostname)
        if not (address.is_private or address.is_loopback) or address.is_unspecified:
            raise ValueError("inference requires a private local endpoint")
    return url.rstrip("/")


def request_json(base_url, token, path, payload=None, timeout=120, bearer=False):
    request = Request(
        base_url.rstrip("/") + "/" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": (f"Bearer {token}" if bearer else f"Token token={token}"),
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    # Private content must not follow redirects or an ambient outbound proxy.
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as reply:
            body = reply.read()
            return json.loads(body) if body else None
    except Exception:
        raise RuntimeError("private service request failed") from None


class Zammad:
    def __init__(self, config):
        self.url = validate_url(config["base_url"])
        self.token = os.environ[config["auth_env"]]
        if not self.token:
            raise ValueError("Zammad token is empty")

    def call(self, path, payload=None):
        return request_json(self.url, self.token, path, payload)

    def tickets(self):
        tickets = {}
        for state in ("new", "open"):
            page = 1
            while True:
                batch = self.call("tickets/search?" + urlencode({
                    "query": f"state.name:{state}", "page": page, "limit": 100,
                    "sort_by": "id", "order_by": "asc",
                }))
                if not isinstance(batch, list):
                    raise ValueError("invalid ticket search response")
                for ticket in batch:
                    tickets[ticket["id"]] = ticket
                if len(batch) < 100:
                    break
                page += 1
        return sorted(tickets.values(), key=lambda ticket: ticket["id"])

    def articles(self, ticket_id):
        return self.call(f"ticket_articles/by_ticket/{ticket_id}")

    def tag(self, ticket_id, tag):
        self.call("tags/add", {"object": "Ticket", "o_id": ticket_id, "item": tag})

    def link(self, ticket_id, original):
        links = self.call("links?" + urlencode({
            "link_object": "Ticket", "link_object_value": ticket_id,
        }))["links"]
        if any(str(link["link_object_value"]) == str(original) for link in links):
            return
        self.call("links/add", {
            "link_type": "normal", "link_object_source": "Ticket",
            "link_object_source_value": ticket_id, "link_object_target": "Ticket",
            "link_object_target_value": original,
        })

    def note(self, ticket_id, body):
        self.call("ticket_articles", {
            "ticket_id": ticket_id, "body": body, "type": "note",
            "internal": True, "content_type": "text/plain",
        })
