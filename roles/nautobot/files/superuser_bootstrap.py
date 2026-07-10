"""Idempotently ensure the Nautobot superuser exists.

Run via ``nautobot-server shell --interface python`` with the superuser name,
email, and password supplied in the environment (never on argv). Prints
``SUPERUSER_CREATED`` on first creation and ``SUPERUSER_UPDATED`` thereafter so
the calling Ansible task can report change accurately.
"""
import os

from django.contrib.auth import get_user_model

User = get_user_model()

name = os.environ["NAUTOBOT_SUPERUSER_NAME"]
email = os.environ.get("NAUTOBOT_SUPERUSER_EMAIL", "")
password = os.environ["NAUTOBOT_SUPERUSER_PASSWORD"]

user, created = User.objects.get_or_create(username=name, defaults={"email": email})
user.is_superuser = True
user.is_staff = True
if email:
    user.email = email
user.set_password(password)
user.save()

print("SUPERUSER_CREATED" if created else "SUPERUSER_UPDATED")
