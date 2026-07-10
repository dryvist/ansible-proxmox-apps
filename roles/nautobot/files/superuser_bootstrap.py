"""Idempotently ensure the Nautobot superuser exists.

Run via ``nautobot-server shell --interface python`` with the superuser name,
email, and password supplied in the environment (never on argv). Prints
``SUPERUSER_CHANGED`` only when the database row changed, so the calling
Ansible task can report change accurately.
"""
import os

from django.contrib.auth import get_user_model

User = get_user_model()

name = os.environ["NAUTOBOT_SUPERUSER_NAME"]
email = os.environ.get("NAUTOBOT_SUPERUSER_EMAIL", "")
password = os.environ["NAUTOBOT_SUPERUSER_PASSWORD"]

user, created = User.objects.get_or_create(username=name, defaults={"email": email})
changed = created

if not user.is_superuser:
    user.is_superuser = True
    changed = True
if not user.is_staff:
    user.is_staff = True
    changed = True
if email and user.email != email:
    user.email = email
    changed = True
if created or not user.check_password(password):
    user.set_password(password)
    changed = True
if changed:
    user.save()

print("SUPERUSER_CHANGED" if changed else "SUPERUSER_UNCHANGED")
