"""
Parse and write KtransToGrafana-style `groups/<name>.env` files while
preserving comments, blank lines, and the original ordering of keys.

The .env files in groups/ are line-based KEY=VALUE with shell-style
comments. We treat each line as either a comment, blank, or assignment.
On write-back, existing assignment lines get their value replaced in
place; new keys append to the end with a blank line separator.
"""
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Return all KEY=VALUE pairs as a flat dict. Comments and blanks are ignored.

    Trailing inline comments (e.g. `KEY=value  # comment`) are stripped
    from the value side.
    """
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if "#" in value:
            value = value.split("#", 1)[0]
        out[key.strip()] = value.strip()
    return out


def write_env_file(path: Path, changes: dict[str, str]) -> None:
    """Apply `changes` to the file in place, preserving structure.

    For each assignment line whose key is in `changes`, the value is
    replaced. Keys that don't already exist in the file are appended at
    the end. Blank lines and comments are preserved unchanged.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = raw.partition("=")[0].strip()
        if key in changes:
            lines[i] = f"{key}={changes[key]}"
            seen.add(key)

    new_keys = [k for k in changes if k not in seen]
    if new_keys:
        if lines and lines[-1].strip():
            lines.append("")
        for k in new_keys:
            lines.append(f"{k}={changes[k]}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
