#!/usr/bin/env python3
"""Fail-closed preflight for release text, source code and submission attachments.

The rule's search term is encoded to avoid reintroducing the literal into code.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

CHECKED = {".md", ".txt", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".xml", ".yml", ".yaml", ".py", ".sh", ".csv", ".toml", ".rst", ".svg"}
DOCUMENTS = {".pdf", ".pptx", ".docx", ".zip"}
EXCLUDE = {".git", "node_modules", ".venv", "dist", "__pycache__", "vendor", ".next", "build", ".pytest_cache"}
STEM = bytes.fromhex("717565626563").decode("ascii")
MAX_MEMBER = 10_000_000


def prohibited(value: str) -> bool:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c) and c not in ("\u200b", "\u200c", "\u200d", "\ufeff"))
    pattern = "".join(re.escape(c) + r"[\W_]*" for c in STEM)
    return bool(re.search(pattern, normalized))


def extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            output = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("PDF text extraction failed") from exc
        return output.stdout.decode("utf-8", "replace")
    if path.suffix.lower() in {".pptx", ".docx", ".zip"}:
        contents = []
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if Path(member.filename).suffix.lower() not in CHECKED:
                    continue
                if member.file_size > MAX_MEMBER:
                    raise RuntimeError("Text document exceeds permitted inspection size")
                contents.append(archive.read(member).decode("utf-8", "replace"))
        return "\n".join(contents)
    return path.read_text(encoding="utf-8", errors="replace")


def scan(paths: list[Path]) -> tuple[list[str], list[str]]:
    blocked, errors = [], []
    files = set()
    for path in paths:
        if not path.exists():
            errors.append("Missing input: " + str(path))
            continue
        if path.is_file():
            files.add(path)
        else:
            for p in path.rglob("*"):
                if p.is_file() and p.suffix.lower() in CHECKED | DOCUMENTS:
                    if not set(p.relative_to(path).parts) & EXCLUDE:
                        files.add(p)
    for path in sorted(files):
        try:
            if prohibited(extract(path)):
                blocked.append(str(path))
        except Exception as exc:
            errors.append("Could not scan " + str(path) + ": " + type(exc).__name__)
    return blocked, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--extra", action="append", type=Path, default=[], help="A separate Devpost draft, PDF, PPTX, ZIP or document to inspect")
    args = parser.parse_args()
    blocked, errors = scan([args.root, *args.extra])
    for path in blocked:
        print("RELEASE-COPY BLOCKED: " + path, file=sys.stderr)
    for error in errors:
        print("RELEASE-COPY ERROR: " + error, file=sys.stderr)
    if blocked or errors:
        return 1
    print("Release-copy preflight: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
