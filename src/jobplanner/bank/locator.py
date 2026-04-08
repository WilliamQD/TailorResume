"""Find line numbers in experience.yaml for a given source_id + bullet_index.

Used by the Bank Health UI to jump from a suggestion card directly to the
offending bullet in the user's editor.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_ID_RE = re.compile(r'^\s*-?\s*id:\s*["\']?([\w-]+)["\']?\s*$')
_DESC_RE = re.compile(r'^\s*-\s*description:')


def find_bullet_line(bank_path: Path, source_id: str, bullet_index: int) -> int | None:
    """Return 1-based line number of the Nth bullet under the entry with ``id: source_id``.

    Returns ``None`` if the source_id is not found in the file. Falls back to the
    line of the matching ``id:`` itself if the bullet count is short. The scan
    is a structural pattern match against the existing convention of an ``id:``
    line followed by a ``bullets:`` block of ``- description:`` entries — it
    does not parse YAML.
    """
    if not bank_path.exists():
        return None
    lines = bank_path.read_text(encoding="utf-8").splitlines()

    id_line: int | None = None
    for i, line in enumerate(lines):
        m = _ID_RE.match(line)
        if m and m.group(1) == source_id:
            id_line = i + 1  # 1-based
            break
    if id_line is None:
        return None

    # Walk forward from id_line, counting `- description:` matches.
    bullet_count = 0
    for j in range(id_line, len(lines)):
        # Stop at the next sibling `- id:` so we don't bleed into another entry.
        if j > id_line - 1 and j != id_line - 1 and _ID_RE.match(lines[j]):
            break
        if _DESC_RE.match(lines[j]):
            if bullet_count == bullet_index:
                return j + 1
            bullet_count += 1
    return id_line  # fall back to the id line if the bullet wasn't found


def open_in_vscode(file_path: Path, line: int) -> bool:
    """Best-effort open of file_path at line in VS Code. Returns True on success.

    Uses ``shutil.which`` to find ``code`` (Mac/Linux) or ``code.cmd`` (Windows)
    on the PATH. Non-blocking — VS Code opens in a new window or focuses an
    existing one.
    """
    code_cmd = shutil.which("code") or shutil.which("code.cmd")
    if not code_cmd:
        return False
    try:
        subprocess.Popen([code_cmd, "-g", f"{file_path}:{line}"])
        return True
    except Exception:
        return False
