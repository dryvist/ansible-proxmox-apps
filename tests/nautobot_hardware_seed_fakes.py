"""Minimal Django/Nautobot test doubles shared by nautobot_hardware_seed.py.

Split out of that file so it reads as fixtures-then-behavior instead of one
monolithic module: Record/FakeManager/FakeQuerySet/Collector stand in for
model instances, managers, querysets, and the job logger, with just enough
surface for roles/nautobot/files/jobs/ssot_hardware.py to run unmodified.
"""
from __future__ import annotations

from typing import Any


def _matches(item: Any, **kwargs: Any) -> bool:
    """Match an item against kwargs, supporting the one lookup suffix in use.

    ``field__isnull=<bool>`` mirrors Django: True when the field is unset
    (missing or ``None``), compared against the requested boolean. Every
    other key is a plain equality check on the attribute of the same name.
    """
    for key, wanted in kwargs.items():
        field, _, suffix = key.partition("__")
        if suffix == "isnull":
            if (getattr(item, field, None) is None) != bool(wanted):
                return False
        elif getattr(item, key, None) != wanted:
            return False
    return True


class Record:
    """An object with named attributes, standing in for a model instance."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)
        self._store: list[Record] | None = None

    def delete(self) -> None:
        """Remove self from the backing store, mirroring the real delete()."""
        if self._store is not None and self in self._store:
            self._store.remove(self)


class FakeManager:
    """Minimal Django manager: enough for get_or_create/update_or_create/filter."""

    def __init__(self, store: list[Record], key: str) -> None:
        self.store, self.key = store, key
        self.created: list[Record] = []

    def _match(self, **kwargs):
        wanted = {k: v for k, v in kwargs.items() if k != "defaults"}
        for item in self.store:
            if _matches(item, **wanted):
                return item
        return None

    def filter(self, **kwargs):
        """Return a queryset-ish list supporting .first() and .exists()."""
        found = [i for i in self.store if _matches(i, **kwargs)]
        return FakeQuerySet(found)

    def get_or_create(self, defaults=None, **kwargs):
        """Return (obj, created)."""
        existing = self._match(**kwargs)
        if existing is not None:
            return existing, False
        obj = Record(**{**(defaults or {}), **kwargs})
        obj._store = self.store
        self.store.append(obj)
        self.created.append(obj)
        return obj, True

    def update_or_create(self, defaults=None, **kwargs):
        """Return (obj, created), applying defaults on both paths."""
        existing = self._match(**kwargs)
        if existing is not None:
            existing.__dict__.update(defaults or {})
            return existing, False
        return self.get_or_create(defaults=defaults, **kwargs)


class FakeQuerySet(list):
    """List with the queryset methods the job calls."""

    def first(self):
        """Return the first match or None."""
        return self[0] if self else None

    def exists(self) -> bool:
        """Return whether anything matched."""
        return bool(self)

    def exclude(self, **kwargs):
        """Return the items that do NOT match kwargs — the inverse of filter."""
        return FakeQuerySet([i for i in self if not _matches(i, **kwargs)])


class Collector:
    """Captures logger calls so a warning can be asserted on."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg, *args):  # noqa: D102
        self.warnings.append(msg % args if args else msg)

    def info(self, msg, *args):  # noqa: D102
        self.infos.append(msg % args if args else msg)
