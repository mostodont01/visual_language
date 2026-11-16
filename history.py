"""Version history of a project: commits and branches, stored in the .vl file.

Pure Python (no Qt). The project file holds it under history/:

    history/history.json    {"current": branch name,
                             "branches": {name: {"head": commit id | null, "draft": snapshot | null}},
                             "commits": {id: {"parent", "message", "time", "snapshot", "summary"}}}
    history/objects/<sha1>  content-addressed blobs: snapshots, node JSON texts, code files

A snapshot is the whole project state (graph, compile settings, palette and
imported nodes) as JSON:

    {"project": {...project.json without format/version...},
     "packages": {node id: {"json": blob, "files": {code path: blob}}}}

Blobs are stored once, so unchanged nodes and files cost nothing per commit.
A branch's "draft" is its uncommitted working state; the current branch's
draft is the live project, so it is only stored for the other branches.
"""

import hashlib
import json
import time
import zipfile
from typing import Any

HISTORY_ENTRY = "history/history.json"
OBJECTS_PREFIX = "history/objects/"
DEFAULT_BRANCH = "main"
MAX_BRANCH_NAME = 50

# Imported node packages as plain data: {node id: (json text, {code path: bytes})}.
Packages = dict[str, tuple[str, dict[str, bytes]]]


class HistoryError(Exception):
    """A history operation that can't be done (bad branch name, unknown commit...)."""


def _hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _normalize(value: Any) -> Any:
    """Whole floats as ints, so 0.0 and 0 (e.g. a position before and after
    loading) give the same snapshot."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def summarize(old: dict | None, new: dict) -> dict[str, list[int]]:
    """What changed between two project dicts: {"nodes": [added, removed, changed],
    "wires": [added, removed]}. Moving a node doesn't count as a change."""
    def nodes(project):
        return {n["id"]: (n.get("type"), _canonical(n.get("values", {})), n.get("widget_visible"))
                for n in (project or {}).get("nodes", [])}

    def wires(project):
        return {(c["source_node"], c["source_socket"], c["target_node"], c["target_socket"])
                for c in (project or {}).get("connections", [])}

    old_nodes, new_nodes = nodes(old), nodes(new)
    old_wires, new_wires = wires(old), wires(new)
    changed = sum(1 for nid in old_nodes.keys() & new_nodes.keys() if old_nodes[nid] != new_nodes[nid])
    return {
        "nodes": [len(new_nodes.keys() - old_nodes.keys()), len(old_nodes.keys() - new_nodes.keys()), changed],
        "wires": [len(new_wires - old_wires), len(old_wires - new_wires)],
    }


def describe_summary(summary: dict[str, list[int]] | None) -> str:
    """'+2 nodes, −1 wire, 1 changed' (or 'settings only' when the graph didn't change)."""
    if not summary:
        return ""
    (n_add, n_rem, n_chg), (w_add, w_rem) = summary.get("nodes", [0, 0, 0]), summary.get("wires", [0, 0])
    parts = []
    for count, sign, word in ((n_add, "+", "node"), (n_rem, "−", "node"), (w_add, "+", "wire"), (w_rem, "−", "wire")):
        if count:
            parts.append(f"{sign}{count} {word}{'s' if count != 1 else ''}")
    if n_chg:
        parts.append(f"{n_chg} changed")
    return ", ".join(parts) if parts else "settings only"


def validate_branch_name(name: str) -> str:
    """The cleaned-up name, or raises HistoryError."""
    name = name.strip()
    if not name:
        raise HistoryError("A branch needs a name.")
    if len(name) > MAX_BRANCH_NAME:
        raise HistoryError(f"Branch names can be at most {MAX_BRANCH_NAME} characters.")
    if name.startswith("/") or name.endswith("/"):
        raise HistoryError("A branch name can't start or end with “/”.")
    if any(c in name for c in "\n\r\t"):
        raise HistoryError("A branch name can't contain line breaks or tabs.")
    return name


class ProjectHistory:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.branches: dict[str, dict[str, str | None]] = {DEFAULT_BRANCH: {"head": None, "draft": None}}
        self.current = DEFAULT_BRANCH

    # -- Snapshots ----------------------------------------------------------

    def _put(self, data: bytes, store: bool = True) -> str:
        key = _hash(data)
        if store:
            self.objects.setdefault(key, data)
        return key

    def _get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise HistoryError(f"The project history is missing object {key[:10]}.") from None

    def snapshot(self, project: dict, packages: Packages, store: bool = True) -> str:
        """Store a project state and return its hash. Equal states get equal hashes.
        With store=False only the hash is computed (to compare states)."""
        entry = {
            "project": _normalize({k: v for k, v in project.items() if k not in ("format", "version")}),
            "packages": {
                nid: {"json": self._put(json_text.encode("utf-8"), store),
                      "files": {rel: self._put(content, store) for rel, content in files.items()}}
                for nid, (json_text, files) in packages.items()
            },
        }
        return self._put(_canonical(entry), store)

    def load_snapshot(self, key: str) -> tuple[dict, Packages]:
        entry = json.loads(self._get(key))
        packages = {
            nid: (self._get(info["json"]).decode("utf-8"),
                  {rel: self._get(blob) for rel, blob in info.get("files", {}).items()})
            for nid, info in entry.get("packages", {}).items()
        }
        return entry["project"], packages

    def snapshot_project(self, key: str | None) -> dict | None:
        """Just the project dict of a snapshot (no node files), or None."""
        return json.loads(self._get(key))["project"] if key else None

    # -- Commits ------------------------------------------------------------

    def head(self, branch: str | None = None) -> str | None:
        return self._branch(branch or self.current)["head"]

    def head_snapshot(self, branch: str | None = None) -> str | None:
        head = self.head(branch)
        return self.commits[head]["snapshot"] if head else None

    def commit(self, snapshot: str, message: str) -> str:
        """Commit a snapshot on the current branch. Returns the new commit's id."""
        message = message.strip()
        if not message:
            raise HistoryError("A commit needs a message.")
        parent = self.head()
        if parent and self.commits[parent]["snapshot"] == snapshot:
            raise HistoryError("Nothing changed since the last commit.")
        now = time.time()
        commit_id = _hash(_canonical([parent, snapshot, message, now]))[:12]
        self.commits[commit_id] = {
            "parent": parent,
            "message": message,
            "time": now,
            "snapshot": snapshot,
            "summary": summarize(self.snapshot_project(self.head_snapshot()), self.snapshot_project(snapshot)),
        }
        self.branches[self.current] = {"head": commit_id, "draft": None}
        return commit_id

    def log(self, branch: str | None = None) -> list[dict[str, Any]]:
        """The branch's commits, newest first, each with its "id"."""
        result, commit_id = [], self.head(branch)
        while commit_id:
            result.append({"id": commit_id, **self.commits[commit_id]})
            commit_id = self.commits[commit_id]["parent"]
        return result

    def commit_info(self, commit_id: str) -> dict[str, Any]:
        if commit_id not in self.commits:
            raise HistoryError(f"There is no commit “{commit_id}”.")
        return {"id": commit_id, **self.commits[commit_id]}

    # -- Branches -----------------------------------------------------------

    def _branch(self, name: str) -> dict[str, str | None]:
        if name not in self.branches:
            raise HistoryError(f"There is no branch “{name}”.")
        return self.branches[name]

    def _new_name(self, name: str) -> str:
        name = validate_branch_name(name)
        if name in self.branches:
            raise HistoryError(f"There already is a branch “{name}”.")
        return name

    def create_branch(self, name: str, head: str | None, draft: str | None = None) -> str:
        name = self._new_name(name)
        if head is not None and head not in self.commits:
            raise HistoryError(f"There is no commit “{head}”.")
        self.branches[name] = {"head": head, "draft": draft}
        return name

    def rename_branch(self, old: str, new: str) -> str:
        self._branch(old)
        if validate_branch_name(new) == old:
            return old
        new = self._new_name(new)
        # Keep the order, so the branch stays where it was in lists.
        self.branches = {(new if k == old else k): v for k, v in self.branches.items()}
        if self.current == old:
            self.current = new
        return new

    def delete_branch(self, name: str):
        self._branch(name)
        if name == self.current:
            raise HistoryError("The current branch can't be deleted. Switch to another branch first.")
        del self.branches[name]
        self._drop_unreachable_commits()

    def set_draft(self, branch: str, draft: str | None):
        self._branch(branch)["draft"] = draft

    def working_snapshot(self, branch: str) -> str | None:
        """What to load when switching to the branch: its draft, else its head."""
        info = self._branch(branch)
        return info["draft"] or self.head_snapshot(branch)

    # -- Storage ------------------------------------------------------------

    def _drop_unreachable_commits(self):
        reachable: set[str] = set()
        for info in self.branches.values():
            commit_id = info["head"]
            while commit_id and commit_id not in reachable:
                reachable.add(commit_id)
                commit_id = self.commits[commit_id]["parent"]
        self.commits = {k: v for k, v in self.commits.items() if k in reachable}

    def _reachable_objects(self, extra: list[str]) -> set[str]:
        roots = [c["snapshot"] for c in self.commits.values()]
        roots += [b["draft"] for b in self.branches.values() if b["draft"]]
        roots += extra
        keys: set[str] = set()
        for root in roots:
            if root in keys or root not in self.objects:
                continue
            keys.add(root)
            entry = json.loads(self.objects[root])
            for info in entry.get("packages", {}).values():
                keys.add(info["json"])
                keys.update(info.get("files", {}).values())
        return keys

    def state(self) -> list:
        """Everything about the history that counts as an unsaved change."""
        return [self.current, self.branches, sorted(self.commits)]

    def is_empty(self) -> bool:
        return not self.commits and list(self.branches) == [DEFAULT_BRANCH]

    def write(self, archive: zipfile.ZipFile):
        """Write history/ into an open project archive (only objects still in use)."""
        self._drop_unreachable_commits()
        archive.writestr(HISTORY_ENTRY, json.dumps(
            {"current": self.current, "branches": self.branches, "commits": self.commits}, indent=1) + "\n")
        for key in sorted(self._reachable_objects([])):
            archive.writestr(OBJECTS_PREFIX + key, self.objects[key])
        # Forget objects nothing uses any more (e.g. drafts that were committed).
        keep = self._reachable_objects([])
        self.objects = {k: v for k, v in self.objects.items() if k in keep}

    @classmethod
    def read(cls, archive: zipfile.ZipFile) -> "ProjectHistory":
        """Read history/ from a project archive. Files without one get an empty history."""
        history = cls()
        try:
            raw = json.loads(archive.read(HISTORY_ENTRY).decode("utf-8"))
        except KeyError:
            return history
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"{HISTORY_ENTRY} is not valid JSON: {e}") from None
        if not isinstance(raw, dict) or not isinstance(raw.get("branches"), dict) or not raw["branches"]:
            raise ValueError(f"{HISTORY_ENTRY} is damaged.")

        history.commits = {str(k): dict(v) for k, v in (raw.get("commits") or {}).items() if isinstance(v, dict)}
        history.branches = {
            str(name): {"head": info.get("head") if info.get("head") in history.commits else None,
                        "draft": info.get("draft")}
            for name, info in raw["branches"].items() if isinstance(info, dict)
        }
        current = raw.get("current")
        history.current = current if current in history.branches else next(iter(history.branches))
        for name in archive.namelist():
            if name.startswith(OBJECTS_PREFIX) and not name.endswith("/"):
                history.objects[name[len(OBJECTS_PREFIX):]] = archive.read(name)
        return history
