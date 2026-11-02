"""The files the agent can see and change.

`Workspace` is the small interface the agent's tools are written against. `LocalWorkspace`
implements it over a folder on disk, which is a mounted volume in the container. A backend for
object storage or a git checkout implements the same methods and nothing in the agent changes.

Only plain-text note files are visible (Markdown and text by default). Paths are relative to the
root, use forward slashes, and can never reach outside it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

DEFAULT_EXTENSIONS = frozenset({".md", ".txt"})
MAX_FILE_BYTES = 1_000_000
MAX_SEARCH_HITS = 20


class WorkspaceError(Exception):
    """A problem the user can be told about in one sentence."""


@dataclass(frozen=True)
class Entry:
    path: str
    is_dir: bool
    size: int = 0


@dataclass(frozen=True)
class Match:
    path: str
    line: int  # 1-based
    text: str


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int  # 1-based


@dataclass(frozen=True)
class Excerpt:
    path: str
    text: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    total_lines: int


class Workspace(Protocol):
    def list(self, folder: str = "") -> list[Entry]: ...
    def search(self, query: str) -> list[Match]: ...
    def read(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> Excerpt: ...
    def headings(self, path: str) -> list[Heading]: ...
    def section(self, path: str, heading: str) -> Excerpt: ...
    def create(self, path: str, content: str) -> None: ...
    def append(self, path: str, content: str) -> None: ...
    def replace(self, path: str, find: str, replacement: str) -> int: ...
    def insert_after_heading(self, path: str, heading: str, content: str) -> None: ...


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class LocalWorkspace:
    """A `Workspace` over one folder on disk."""

    def __init__(
        self, root: str | os.PathLike[str], extensions: frozenset[str] = DEFAULT_EXTENSIONS
    ):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace root {self.root} is not a folder.")
        self.extensions = extensions

    # -- paths -------------------------------------------------------------------------------

    def _resolve(self, path: str, *, must_exist: bool = True, is_dir: bool = False) -> Path:
        clean = path.strip().strip("/").replace("\\", "/")
        pure = PurePosixPath(clean) if clean else PurePosixPath()
        if pure.is_absolute() or any(part in ("..", "") for part in pure.parts if part != "."):
            raise WorkspaceError(f"'{path}' is not a path inside the workspace.")
        if any(part.startswith(".") for part in pure.parts):
            raise WorkspaceError("Hidden files and folders are not available.")
        target = (self.root / Path(*pure.parts)) if pure.parts else self.root
        try:
            resolved = target.resolve()
            resolved.relative_to(self.root)
        except (OSError, ValueError) as e:
            raise WorkspaceError(f"'{path}' is not a path inside the workspace.") from e
        if not is_dir and pure.parts and resolved.suffix.lower() not in self.extensions:
            kinds = ", ".join(sorted(self.extensions))
            raise WorkspaceError(f"Only {kinds} files are available, so '{path}' can't be used.")
        if must_exist and not resolved.exists():
            kind = "folder" if is_dir else "file"
            raise WorkspaceError(f"There is no {kind} called '{path}' in the workspace.")
        return resolved

    def _relative(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def _visible(self, p: Path) -> bool:
        return not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in self.extensions)

    def _read_text(self, p: Path) -> str:
        if p.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"'{self._relative(p)}' is too large to read.")
        return p.read_text(encoding="utf-8", errors="replace")

    def _write_text(self, p: Path, text: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")

    # -- reading -----------------------------------------------------------------------------

    def list(self, folder: str = "") -> list[Entry]:
        base = self._resolve(folder, is_dir=True)
        if not base.is_dir():
            raise WorkspaceError(f"'{folder}' is a file, not a folder.")
        entries = []
        for child in sorted(base.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if self._visible(child):
                size = 0 if child.is_dir() else child.stat().st_size
                entries.append(Entry(self._relative(child), child.is_dir(), size))
        return entries

    def _files(self) -> list[Path]:
        return sorted(
            p
            for p in self.root.rglob("*")
            if p.is_file()
            and self._visible(p)
            and not any(part.startswith(".") for part in p.relative_to(self.root).parts)
        )

    def search(self, query: str) -> list[Match]:
        needle = query.strip().lower()
        if not needle:
            raise WorkspaceError("Say what to search for.")
        hits: list[Match] = []
        for p in self._files():
            if needle in p.name.lower():
                hits.append(Match(self._relative(p), 0, p.name))
            for i, line in enumerate(self._read_text(p).splitlines(), start=1):
                if needle in line.lower():
                    hits.append(Match(self._relative(p), i, line.strip()))
                    if len(hits) >= MAX_SEARCH_HITS:
                        return hits
        return hits

    def read(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> Excerpt:
        p = self._resolve(path)
        lines = self._read_text(p).splitlines()
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or total)
        if total and start > end:
            raise WorkspaceError(
                f"'{path}' has {total} lines, so lines {start} to {end} don't exist."
            )
        text = "\n".join(lines[start - 1 : end])
        return Excerpt(self._relative(p), text, start, end if total else 0, total)

    def headings(self, path: str) -> list[Heading]:
        p = self._resolve(path)
        found = []
        for i, line in enumerate(self._read_text(p).splitlines(), start=1):
            m = _HEADING.match(line)
            if m:
                found.append(Heading(len(m.group(1)), m.group(2), i))
        return found

    def _section_bounds(self, path: str, heading: str) -> tuple[Path, list[str], int, int]:
        """The file, its lines, and the 0-based [start, end) of the section under `heading`."""
        p = self._resolve(path)
        lines = self._read_text(p).splitlines()
        wanted = heading.strip().lstrip("#").strip().lower()
        heads = self.headings(path)
        matches = [h for h in heads if h.title.lower() == wanted] or [
            h for h in heads if wanted in h.title.lower()
        ]
        if not matches:
            names = "; ".join(h.title for h in heads) or "none"
            raise WorkspaceError(
                f"'{path}' has no heading like '{heading}'. Its headings are: {names}."
            )
        if len(matches) > 1 and not all(m.title.lower() == wanted for m in matches):
            names = "; ".join(m.title for m in matches)
            raise WorkspaceError(f"Several headings match '{heading}': {names}. Which one?")
        head = matches[0]
        start = head.line - 1
        end = len(lines)
        for h in heads:
            if h.line > head.line and h.level <= head.level:
                end = h.line - 1
                break
        return p, lines, start, end

    def section(self, path: str, heading: str) -> Excerpt:
        p, lines, start, end = self._section_bounds(path, heading)
        return Excerpt(self._relative(p), "\n".join(lines[start:end]), start + 1, end, len(lines))

    # -- writing -----------------------------------------------------------------------------

    def create(self, path: str, content: str) -> None:
        p = self._resolve(path, must_exist=False)
        if p.exists():
            raise WorkspaceError(f"'{path}' already exists. Append to it or choose another name.")
        self._write_text(p, content.rstrip("\n") + "\n")

    def append(self, path: str, content: str) -> None:
        p = self._resolve(path)
        existing = self._read_text(p)
        sep = (
            ""
            if not existing or existing.endswith("\n\n")
            else ("\n" if existing.endswith("\n") else "\n\n")
        )
        self._write_text(p, existing + sep + content.rstrip("\n") + "\n")

    def replace(self, path: str, find: str, replacement: str) -> int:
        p = self._resolve(path)
        if not find:
            raise WorkspaceError("Say which text to replace.")
        text = self._read_text(p)
        count = text.count(find)
        if count == 0:
            raise WorkspaceError(
                f"'{path}' doesn't contain that text. Read the passage back to get it exactly."
            )
        if count > 1:
            raise WorkspaceError(
                f"That text appears {count} times in '{path}'. "
                "Include more of the surrounding words."
            )
        self._write_text(p, text.replace(find, replacement, 1))
        return 1

    def insert_after_heading(self, path: str, heading: str, content: str) -> None:
        p, lines, start, end = self._section_bounds(path, heading)
        # Drop trailing blank lines of the section so the new text sits with it
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        rest = lines[end:]
        while rest and not rest[0].strip():
            rest.pop(0)
        new = [*lines[:end], "", *content.rstrip("\n").split("\n")]
        if rest:
            new += ["", *rest]
        self._write_text(p, "\n".join(new) + "\n")
