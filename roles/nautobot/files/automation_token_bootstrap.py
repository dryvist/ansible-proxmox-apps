"""Idempotently ensure a least-privilege Nautobot automation API token.

Run via ``nautobot-server shell --interface python``. The token belongs to a
non-staff, non-superuser account and can write only to DCIM models through
view/add/change permissions, plus view/add on the separate ``extras.Note``
model. Nautobot's Notes API also requires view on the target DCIM object.

Prints ``AUTOMATION_TOKEN=<key>`` for the caller to publish and a changed
marker only when the database state changes.
"""
import os

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from nautobot.extras.models import Note
from nautobot.users.models import ObjectPermission, Token

User = get_user_model()

username = os.environ.get("NAUTOBOT_AUTOMATION_USERNAME", "svc-nautobot-writer")
DCIM_PERMISSION = "ansible-nautobot-automation-dcim"
NOTES_PERMISSION = "ansible-nautobot-automation-notes"
STATUS_PERMISSION = "ansible-nautobot-automation-statuses"
TOKEN_DESCRIPTION = "ansible-nautobot-automation"
PERMISSION_NAMES = {DCIM_PERMISSION, NOTES_PERMISSION, STATUS_PERMISSION}
DCIM_ACTIONS = ["view", "add", "change"]
NOTE_ACTIONS = ["view", "add"]
STATUS_ACTIONS = ["view"]


def sync_permission(name, actions, content_types, user):
    """Set one permission exactly, refusing to alter grants used elsewhere."""
    permission, created = ObjectPermission.objects.get_or_create(
        name=name,
        defaults={"actions": actions, "constraints": {}},
    )
    if permission.users.exclude(pk=user.pk).exists() or permission.groups.exists():
        raise RuntimeError("automation permission is already assigned elsewhere")

    changed = created
    if not permission.enabled:
        permission.enabled = True
        changed = True
    if list(permission.actions) != actions:
        permission.actions = actions
        changed = True
    if permission.constraints not in (None, {}):
        permission.constraints = {}
        changed = True
    expected_ids = {content_type.pk for content_type in content_types}
    if set(permission.object_types.values_list("pk", flat=True)) != expected_ids:
        permission.object_types.set(content_types)
        changed = True
    if not permission.users.filter(pk=user.pk).exists():
        permission.users.add(user)
        changed = True
    if changed:
        permission.save()
    return changed


dcim_models = list(apps.get_app_config("dcim").get_models())
if not dcim_models:
    raise RuntimeError("Nautobot DCIM has no registered models")
dcim_content_types = list(ContentType.objects.get_for_models(*dcim_models).values())
if not dcim_content_types or any(ct.app_label != "dcim" for ct in dcim_content_types):
    raise RuntimeError("could not resolve the Nautobot DCIM content types")
note_content_type = ContentType.objects.get_for_model(Note)
if note_content_type.app_label != "extras" or note_content_type.model != "note":
    raise RuntimeError("could not resolve Nautobot's extras.Note content type")
status_model = apps.get_model("extras", "Status")
status_content_type = ContentType.objects.get_for_model(status_model)
if status_content_type.app_label != "extras" or status_content_type.model != "status":
    raise RuntimeError("could not resolve Nautobot's extras.Status content type")

changed = False

with transaction.atomic():
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"is_active": True},
    )
    changed = changed or created

    user_changed = False
    for attribute, expected in (
        ("is_active", True),
        ("is_staff", False),
        ("is_superuser", False),
    ):
        if getattr(user, attribute) != expected:
            setattr(user, attribute, expected)
            user_changed = True
    if user.has_usable_password():
        user.set_unusable_password()
        user_changed = True
    if user_changed:
        user.save()
        changed = True

    # This identity is dedicated to this role. Remove any inherited Django or
    # Nautobot object grants so an old manual assignment cannot widen the token.
    if user.groups.exists():
        user.groups.clear()
        changed = True
    if user.user_permissions.exists():
        user.user_permissions.clear()
        changed = True
    for permission in ObjectPermission.objects.filter(users=user):
        if permission.name not in PERMISSION_NAMES:
            permission.users.remove(user)
            changed = True

    changed = sync_permission(
        DCIM_PERMISSION,
        DCIM_ACTIONS,
        dcim_content_types,
        user,
    ) or changed
    changed = sync_permission(
        NOTES_PERMISSION,
        NOTE_ACTIONS,
        [note_content_type],
        user,
    ) or changed
    changed = sync_permission(
        STATUS_PERMISSION,
        STATUS_ACTIONS,
        [status_content_type],
        user,
    ) or changed

    token = Token.objects.filter(user=user, description=TOKEN_DESCRIPTION).first()
    if token is None:
        token = Token(user=user, description=TOKEN_DESCRIPTION, write_enabled=True)
        token.save()
        changed = True
    else:
        token_changed = False
        if not token.write_enabled:
            token.write_enabled = True
            token_changed = True
        if token.expires is not None:
            token.expires = None
            token_changed = True
        if token_changed:
            token.save()
            changed = True

print("AUTOMATION_TOKEN=" + token.key)
print("AUTOMATION_TOKEN_CHANGED" if changed else "AUTOMATION_TOKEN_UNCHANGED")
