"""Idempotently ensure a read-only Nautobot API token for the dynamic inventory.

Run via ``nautobot-server shell --interface python`` (mirrors
``superuser_bootstrap.py``). Ensures a non-privileged service account, grants it
a view-only ObjectPermission on the object types the GraphQL dynamic inventory
reads (Device, VirtualMachine, Tag), and mints one write-disabled Token for it.
Prints ``RO_TOKEN=<key>`` (always, so the caller can publish it) and
``RO_TOKEN_CHANGED`` only when a database row changed.

Fail-closed by construction: the user is never superuser/staff and the token has
``write_enabled = False``, so a mistaken or missing permission grant yields *no*
access (caught by the inventory parity check), never excess access — the token
cannot write regardless of permissions. Issue #1006.

Live-validation note (verify at cutover): Nautobot 2.x ``users.Token`` /
``users.ObjectPermission`` field names (``write_enabled``, ``actions``,
``object_types``) target current 2.x and can shift across minor versions.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from nautobot.users.models import ObjectPermission, Token

User = get_user_model()

username = os.environ.get("NAUTOBOT_RO_USERNAME", "svc-inventory-ro")
PERM_NAME = "ansible-readonly-inventory"
TOKEN_DESC = "ansible-readonly-inventory"

# Object types the GraphQL dynamic inventory reads (inventory/nautobot.yml).
RO_TYPES = [
    ("dcim", "device"),
    ("virtualization", "virtualmachine"),
    ("extras", "tag"),
]

changed = False

user, created = User.objects.get_or_create(
    username=username, defaults={"is_active": True}
)
changed = changed or created
# Never privileged — re-enforce every run in case it was changed by hand.
if user.is_superuser or user.is_staff:
    user.is_superuser = False
    user.is_staff = False
    user.save()
    changed = True

perm, perm_created = ObjectPermission.objects.get_or_create(
    name=PERM_NAME, defaults={"actions": ["view"]}
)
changed = changed or perm_created
if perm.actions != ["view"]:
    perm.actions = ["view"]
    perm.save()
    changed = True
perm.object_types.set(
    ContentType.objects.get(app_label=app, model=model) for app, model in RO_TYPES
)
if not perm.users.filter(pk=user.pk).exists():
    perm.users.add(user)
    changed = True

token = Token.objects.filter(user=user, description=TOKEN_DESC).first()
if token is None:
    token = Token(user=user, description=TOKEN_DESC, write_enabled=False)
    token.save()
    changed = True
elif token.write_enabled:  # re-enforce read-only on an existing token
    token.write_enabled = False
    token.save()
    changed = True

print("RO_TOKEN=" + token.key)
print("RO_TOKEN_CHANGED" if changed else "RO_TOKEN_UNCHANGED")
