"""Multi-file tasks: changes that must stay consistent across modules.

Each task ships a small repository. The model must emit complete file blocks
for every file it changes; the hidden-in-plain-sight spec is tests.py.
"""

TASKS = [
    # ------------------------------------------------------------------ mf-01
    {
        "id": "mf-01",
        "category": "multifile",
        "title": "add archived flag through model, repo and api",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Add soft-delete support to the note app, end to end.\n\n"
            "Requirements:\n"
            "- Note gains an `archived` attribute that defaults to False, and to_dict must "
            "include it under the key \"archived\".\n"
            "- InMemoryRepo.archive(note_id) marks a note archived and returns it; an unknown "
            "id raises KeyError.\n"
            "- InMemoryRepo.list(include_archived=False) hides archived notes by default.\n"
            "- app.api.serialize(repo, include_archived=True) returns JSON-ready dicts and must "
            "forward the flag to repo.list.\n"
            "- Existing ids, ordering and titles must not change.\n\n"
            "Update every layer that needs it. Do not change tests.py."
        ),
        "write_to": "store/models.py",
        "files": {
            "store/__init__.py": "",
            "app/__init__.py": "",
            "store/models.py": '''"""Domain models."""


class Note:
    def __init__(self, id, title):
        self.id = id
        self.title = title

    def to_dict(self):
        return {"id": self.id, "title": self.title}
''',
            "store/repo.py": '''"""In-memory note repository."""

from store.models import Note


class InMemoryRepo:
    def __init__(self):
        self._notes = {}
        self._next_id = 1

    def add(self, title):
        note = Note(self._next_id, title)
        self._notes[note.id] = note
        self._next_id += 1
        return note

    def get(self, note_id):
        return self._notes.get(note_id)

    def list(self):
        return list(self._notes.values())
''',
            "app/api.py": '''"""Serialisation layer."""


def serialize(repo):
    return [n.to_dict() for n in repo.list()]
''',
            "tests.py": '''
from app.api import serialize
from store.repo import InMemoryRepo

repo = InMemoryRepo()
a = repo.add("alpha")
b = repo.add("beta")
assert (a.id, a.title) == (1, "alpha")
assert a.archived is False
assert [n.id for n in repo.list()] == [1, 2]

repo.archive(2)
assert repo.get(2).archived is True
assert [n.id for n in repo.list()] == [1]
assert [n.id for n in repo.list(include_archived=True)] == [1, 2]

assert serialize(repo) == [
    {"id": 1, "title": "alpha", "archived": False},
    {"id": 2, "title": "beta", "archived": True},
], serialize(repo)
assert serialize(repo, include_archived=False) == [
    {"id": 1, "title": "alpha", "archived": False},
], serialize(repo, include_archived=False)

try:
    repo.archive(99)
    raise AssertionError("expected KeyError")
except KeyError:
    pass
print("ok")
''',
        },
        "oracle": {
            "store/models.py": '''"""Domain models."""


class Note:
    def __init__(self, id, title, archived=False):
        self.id = id
        self.title = title
        self.archived = archived

    def to_dict(self):
        return {"id": self.id, "title": self.title, "archived": self.archived}
''',
            "store/repo.py": '''"""In-memory note repository."""

from store.models import Note


class InMemoryRepo:
    def __init__(self):
        self._notes = {}
        self._next_id = 1

    def add(self, title):
        note = Note(self._next_id, title)
        self._notes[note.id] = note
        self._next_id += 1
        return note

    def get(self, note_id):
        return self._notes.get(note_id)

    def archive(self, note_id):
        note = self._notes.get(note_id)
        if note is None:
            raise KeyError(note_id)
        note.archived = True
        return note

    def list(self, include_archived=False):
        notes = list(self._notes.values())
        if include_archived:
            return notes
        return [n for n in notes if not n.archived]
''',
            "app/api.py": '''"""Serialisation layer."""


def serialize(repo, include_archived=True):
    return [n.to_dict() for n in repo.list(include_archived=include_archived)]
''',
        },
        "max_tokens": 3000,
    },
    # ------------------------------------------------------------------ mf-02
    {
        "id": "mf-02",
        "category": "multifile",
        "title": "extract validators and delegate at call time",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Extract the low-level field checks into a new module app/validators.py with "
            "is_valid_email(value) and is_valid_phone(value).\n\n"
            "app/forms.py must keep its public helpers is_valid_email, is_valid_phone and "
            "build_contact, but they must delegate to app.validators at call time (look the "
            "function up on the validators module each call, do not copy the implementation and "
            "do not `from app.validators import is_valid_email`). The service layer must keep "
            "working and must observe a monkeypatched validator.\n\n"
            "Keep the existing acceptance rules for email, phone and contact building. "
            "Do not change tests.py."
        ),
        "write_to": "app/validators.py",
        "files": {
            "app/__init__.py": "",
            "app/forms.py": '''"""Form validation and contact building."""

import re

_EMAIL = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
_PHONE = re.compile(r"^\\+?[0-9][0-9 -]{6,}$")


def is_valid_email(value):
    return bool(_EMAIL.match(value or ""))


def is_valid_phone(value):
    return bool(_PHONE.match(value or ""))


def build_contact(name, email, phone):
    if not name or not name.strip():
        raise ValueError("name is required")
    if not is_valid_email(email):
        raise ValueError("bad email: %r" % (email,))
    if not is_valid_phone(phone):
        raise ValueError("bad phone: %r" % (phone,))
    return {"name": name.strip(), "email": email, "phone": phone}
''',
            "app/service.py": '''"""Service layer."""

from app import forms


def create_contact(name, email, phone):
    contact = forms.build_contact(name, email, phone)
    contact["source"] = "service"
    return contact
''',
            "tests.py": '''
import app.forms as forms
import app.service as service
import app.validators as validators

assert validators.is_valid_email("ada@example.com") is True
assert validators.is_valid_email("nope") is False
assert validators.is_valid_phone("+1 555 0100") is True
assert validators.is_valid_phone("abc") is False

contact = service.create_contact("Ada", "ada@example.com", "+1 555 0100")
assert contact["name"] == "Ada" and contact["source"] == "service"

original = validators.is_valid_email
try:
    validators.is_valid_email = lambda v: v == "only@example.com"
    assert forms.is_valid_email("only@example.com") is True
    assert forms.is_valid_email("ada@example.com") is False
    assert service.create_contact(
        "X", "only@example.com", "+1 555 0100"
    )["email"] == "only@example.com"
    try:
        service.create_contact("X", "ada@example.com", "+1 555 0100")
        raise AssertionError("service must consult the patched validator")
    except ValueError:
        pass
finally:
    validators.is_valid_email = original

assert forms.is_valid_email("ada@example.com") is True
print("ok")
''',
        },
        "oracle": {
            "app/validators.py": '''"""Low-level field validators."""

import re

_EMAIL = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
_PHONE = re.compile(r"^\\+?[0-9][0-9 -]{6,}$")


def is_valid_email(value):
    return bool(_EMAIL.match(value or ""))


def is_valid_phone(value):
    return bool(_PHONE.match(value or ""))
''',
            "app/forms.py": '''"""Form validation and contact building."""

from app import validators


def is_valid_email(value):
    return validators.is_valid_email(value)


def is_valid_phone(value):
    return validators.is_valid_phone(value)


def build_contact(name, email, phone):
    if not name or not name.strip():
        raise ValueError("name is required")
    if not is_valid_email(email):
        raise ValueError("bad email: %r" % (email,))
    if not is_valid_phone(phone):
        raise ValueError("bad phone: %r" % (phone,))
    return {"name": name.strip(), "email": email, "phone": phone}
''',
        },
        "max_tokens": 2800,
    },
    # ------------------------------------------------------------------ mf-03
    {
        "id": "mf-03",
        "category": "multifile",
        "title": "signature change across callers",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Change users.service.get_user to this exact signature:\n\n"
            "    get_user(user_id, *, include_deleted=False)\n\n"
            "- The first parameter is renamed from uid to user_id.\n"
            "- include_deleted is keyword-only and defaults to False.\n"
            "- A soft-deleted user raises KeyError unless include_deleted is True.\n"
            "- Unknown ids always raise KeyError.\n\n"
            "Update every caller. Admin views must be able to load deleted users; the active-user "
            "count must look at deleted users and skip them rather than crash. "
            "Do not change tests.py."
        ),
        "write_to": "users/service.py",
        "files": {
            "users/__init__.py": "",
            "users/service.py": '''"""User service."""

_USERS = {
    1: {"id": 1, "name": "Ada", "deleted": False},
    2: {"id": 2, "name": "Grace", "deleted": True},
    3: {"id": 3, "name": "Linus", "deleted": False},
}


def get_user(uid):
    return _USERS[uid]
''',
            "users/admin.py": '''"""Admin views."""

from users import service


def load_user(uid):
    return service.get_user(uid)
''',
            "users/report.py": '''"""Reporting."""

from users import service


def count_active(ids):
    n = 0
    for uid in ids:
        user = service.get_user(uid)
        if not user["deleted"]:
            n += 1
    return n
''',
            "tests.py": '''
import inspect

from users import admin, report, service

assert service.get_user(1)["name"] == "Ada"
assert service.get_user(user_id=3)["name"] == "Linus"

try:
    service.get_user(2)
    raise AssertionError("deleted user must not be returned by default")
except KeyError:
    pass

assert service.get_user(2, include_deleted=True)["name"] == "Grace"

try:
    service.get_user(99)
    raise AssertionError("unknown id must raise KeyError")
except KeyError:
    pass

sig = inspect.signature(service.get_user)
assert "user_id" in sig.parameters, sig
assert "uid" not in sig.parameters, sig
p = sig.parameters["include_deleted"]
assert p.kind is inspect.Parameter.KEYWORD_ONLY, p.kind
assert p.default is False, p.default

assert admin.load_user(2)["name"] == "Grace"
assert report.count_active([1, 2, 3]) == 2
assert report.count_active([2]) == 0
print("ok")
''',
        },
        "oracle": {
            "users/service.py": '''"""User service."""

_USERS = {
    1: {"id": 1, "name": "Ada", "deleted": False},
    2: {"id": 2, "name": "Grace", "deleted": True},
    3: {"id": 3, "name": "Linus", "deleted": False},
}


def get_user(user_id, *, include_deleted=False):
    user = _USERS[user_id]
    if user["deleted"] and not include_deleted:
        raise KeyError(user_id)
    return user
''',
            "users/admin.py": '''"""Admin views."""

from users import service


def load_user(user_id):
    return service.get_user(user_id, include_deleted=True)
''',
            "users/report.py": '''"""Reporting."""

from users import service


def count_active(ids):
    n = 0
    for user_id in ids:
        user = service.get_user(user_id, include_deleted=True)
        if not user["deleted"]:
            n += 1
    return n
''',
        },
        "max_tokens": 2800,
    },
    # ------------------------------------------------------------------ mf-04
    {
        "id": "mf-04",
        "category": "multifile",
        "title": "break a circular import",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Importing settings.py raises ImportError because config.py and settings.py import "
            "each other. Break the cycle while keeping the public behaviour: settings.PREFIX is "
            "\"APP_\", settings.base() returns a fresh copy of the defaults, and config.get(name) "
            "looks a name up in config.DEFAULTS. The default timeout is 30 and retries is 3.\n\n"
            "Do not change tests.py."
        ),
        "write_to": "config.py",
        "files": {
            "config.py": '''"""Runtime configuration."""

from settings import DEFAULT_TIMEOUT

DEFAULTS = {"timeout": DEFAULT_TIMEOUT, "retries": 3}


def get(name):
    return DEFAULTS[name]
''',
            "settings.py": '''"""Settings facade."""

import config

PREFIX = "APP_"


def base():
    return config.DEFAULTS.copy()
''',
            "tests.py": '''
import settings
import config

assert settings.PREFIX == "APP_"
assert config.DEFAULTS["timeout"] == 30
assert config.DEFAULTS["retries"] == 3
assert config.get("timeout") == 30

b = settings.base()
assert b == {"timeout": 30, "retries": 3}, b
b["timeout"] = 99
assert config.DEFAULTS["timeout"] == 30, "base() must return a copy"

try:
    config.get("missing")
    raise AssertionError("expected KeyError")
except KeyError:
    pass
print("ok")
''',
        },
        "oracle": {
            "config.py": '''"""Runtime configuration."""

DEFAULT_TIMEOUT = 30
DEFAULTS = {"timeout": DEFAULT_TIMEOUT, "retries": 3}


def get(name):
    return DEFAULTS[name]
''',
        },
        "max_tokens": 2200,
    },
    # ------------------------------------------------------------------ mf-05
    {
        "id": "mf-05",
        "category": "multifile",
        "title": "plugin registry with duplicate detection",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Harden the plugin registry.\n\n"
            "- register(name, fn, override=False) raises ValueError when the name already exists "
            "unless override is True; it returns fn.\n"
            "- get(name) raises KeyError for an unknown name.\n"
            "- names() returns the registered names in sorted order.\n"
            "- plugins.builtin.install(registry) must be safe to call more than once.\n\n"
            "Keep the existing built-in plugins registered under the names \"upper\" and "
            "\"lower\". Do not change tests.py."
        ),
        "write_to": "plugins/registry.py",
        "files": {
            "plugins/__init__.py": "",
            "plugins/registry.py": '''"""Plugin registry."""


class Registry:
    def __init__(self):
        self._plugins = {}

    def register(self, name, fn, override=False):
        self._plugins[name] = fn
        return fn

    def get(self, name):
        return self._plugins[name]

    def names(self):
        return list(self._plugins)
''',
            "plugins/builtin.py": '''"""Built-in plugins."""

from plugins.registry import Registry


def install(registry):
    registry.register("upper", str.upper)
    registry.register("lower", str.lower)
''',
            "tests.py": '''
from plugins.registry import Registry
from plugins.builtin import install

r = Registry()
r.register("b", lambda: "B")
r.register("a", lambda: "A")
assert r.names() == ["a", "b"], r.names()
assert r.get("a")() == "A"

try:
    r.register("a", lambda: "X")
    raise AssertionError("duplicate register must raise ValueError")
except ValueError:
    pass

r.register("a", lambda: "X", override=True)
assert r.get("a")() == "X"

try:
    r.get("missing")
    raise AssertionError("expected KeyError")
except KeyError:
    pass

install(r)
install(r)
assert r.names() == ["a", "b", "lower", "upper"], r.names()
assert r.get("upper")("ok") == "OK"
assert r.get("lower")("OK") == "ok"
print("ok")
''',
        },
        "oracle": {
            "plugins/registry.py": '''"""Plugin registry."""


class Registry:
    def __init__(self):
        self._plugins = {}

    def register(self, name, fn, override=False):
        if name in self._plugins and not override:
            raise ValueError("plugin already registered: %r" % (name,))
        self._plugins[name] = fn
        return fn

    def get(self, name):
        return self._plugins[name]

    def names(self):
        return sorted(self._plugins)
''',
            "plugins/builtin.py": '''"""Built-in plugins."""

from plugins.registry import Registry


def install(registry):
    registry.register("upper", str.upper, override=True)
    registry.register("lower", str.lower, override=True)
''',
        },
        "max_tokens": 2400,
    },
    # ------------------------------------------------------------------ mf-06
    {
        "id": "mf-06",
        "category": "multifile",
        "title": "fix chunk() and verify both consumers",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "lib.util.chunk(seq, size) must return a list of consecutive slices of at most "
            "`size` items, including a final short slice. size < 1 raises ValueError.\n\n"
            "Two consumers depend on it: lib.batcher.batches returns the sum of each slice and "
            "lib.pager.pages returns each slice as a space-joined string. The suite fails because "
            "the last partial slice is dropped. Fix the shared helper so both consumers pass; "
            "do not special-case either consumer. Do not change tests.py."
        ),
        "write_to": "lib/util.py",
        "files": {
            "lib/__init__.py": "",
            "lib/util.py": '''"""Sequence helpers."""


def chunk(seq, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    return [seq[i:i + size] for i in range(0, len(seq) - size + 1, size)]
''',
            "lib/batcher.py": '''"""Batching."""

from lib.util import chunk


def batches(items, size):
    return [sum(part) for part in chunk(items, size)]
''',
            "lib/pager.py": '''"""Paging."""

from lib.util import chunk


def pages(items, size):
    return [" ".join(str(x) for x in part) for part in chunk(items, size)]
''',
            "tests.py": '''
from lib.util import chunk
from lib.batcher import batches
from lib.pager import pages

assert chunk([], 3) == []
assert chunk([1], 3) == [[1]]
assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]], chunk([1, 2, 3, 4, 5], 2)
assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
assert batches([1, 2, 3, 4, 5], 2) == [3, 7, 5], batches([1, 2, 3, 4, 5], 2)
assert pages([1, 2, 3, 4, 5], 2) == ["1 2", "3 4", "5"]

try:
    chunk([1], 0)
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("ok")
''',
        },
        "oracle": {
            "lib/util.py": '''"""Sequence helpers."""


def chunk(seq, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    return [seq[i:i + size] for i in range(0, len(seq), size)]
''',
        },
        "max_tokens": 2400,
    },
]
