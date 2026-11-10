#!/usr/bin/env python3
"""Resolve the narrow, expected conflicts from merging a stable release to main.

Only release metadata conflicts with an explicit safe policy are resolved:
version assignments are set to the next development version, the main changelog
is combined with the new release section, and the main OpenWolf handoff wins.
All other conflicts are left untouched for manual review.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

VERSION_ASSIGNMENTS = {
    "pyproject.toml": re.compile(
        r"(?m)^(?P<prefix>[ \t]*version[ \t]*=[ \t]*)"
        r"(?P<quote>['\"])(?P<version>[^'\"\r\n]+)(?P=quote)"
        r"(?P<suffix>[ \t]*)$"
    ),
    "src/ai_guardian/__init__.py": re.compile(
        r"(?m)^(?P<prefix>[ \t]*__version__[ \t]*=[ \t]*)"
        r"(?P<quote>['\"])(?P<version>[^'\"\r\n]+)(?P=quote)"
        r"(?P<suffix>[ \t]*)$"
    ),
    "rust/openshell-middleware/Cargo.toml": re.compile(
        r"(?m)^(?P<prefix>[ \t]*version[ \t]*=[ \t]*)"
        r"(?P<quote>[\"])(?P<version>[^\"\r\n]+)(?P=quote)"
        r"(?P<suffix>[ \t]*)$"
    ),
    "rust/openshell-middleware/Cargo.lock": re.compile(
        r"(?m)^(?P<prefix>[ \t]*version[ \t]*=[ \t]*)"
        r"(?P<quote>[\"])(?P<version>[^\"\r\n]+)(?P=quote)"
        r"(?P<suffix>[ \t]*)$"
    ),
}
KNOWN_CONFLICTS = set(VERSION_ASSIGNMENTS) | {"CHANGELOG.md", ".wolf/STATUS.md"}

CONFLICT_BLOCK = re.compile(
    r"(?ms)^<<<<<<<[^\r\n]*\r?\n"
    r"(?P<ours>.*?)^=======[ \t]*\r?\n"
    r"(?P<theirs>.*?)^>>>>>>>[^\r\n]*(?:\r?\n|$)"
)
CHANGELOG_HEADING = re.compile(r"(?m)^## \[([^\]\r\n]+)\][^\r\n]*$")
REFERENCE_LINK = re.compile(r"(?m)^\[([^\]\r\n]+)\]:[ \t]*(\S+)[ \t]*$")


class MergeResolutionError(ValueError):
    """Raised when an automatic conflict resolution would be unsafe."""


def resolve_version_conflicts(content: str, path: str, version: str) -> str:
    """Resolve version-only merge hunks and reject any broader file conflict."""
    pattern = VERSION_ASSIGNMENTS[path]
    matches = list(CONFLICT_BLOCK.finditer(content))
    if not matches:
        raise MergeResolutionError(f"No standard merge conflict found in {path}")

    resolved = content
    for match in reversed(matches):
        side_texts = []
        replacement_texts = []
        for side in (match.group("ours"), match.group("theirs")):
            assignments = list(pattern.finditer(side))
            if len(assignments) != 1:
                raise MergeResolutionError(
                    f"Expected one version assignment per side in {path}"
                )
            canonical = pattern.sub(
                lambda item: (
                    f"{item.group('prefix')}{item.group('quote')}<VERSION>"
                    f"{item.group('quote')}{item.group('suffix')}"
                ),
                side,
                count=1,
            )
            side_texts.append(canonical)
            replacement_texts.append(
                pattern.sub(
                    lambda item: (
                        f"{item.group('prefix')}{item.group('quote')}{version}"
                        f"{item.group('quote')}{item.group('suffix')}"
                    ),
                    side,
                    count=1,
                )
            )

        if side_texts[0] != side_texts[1]:
            raise MergeResolutionError(
                f"Conflict in {path} includes changes beyond the version value"
            )
        resolved = (
            resolved[: match.start()] + replacement_texts[0] + resolved[match.end() :]
        )

    if re.search(r"(?m)^(<<<<<<<|=======|>>>>>>>)", resolved):
        raise MergeResolutionError(f"Unresolved conflict markers remain in {path}")
    return resolved


def _split_changelog(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    headings = list(CHANGELOG_HEADING.finditer(text))
    if not headings:
        raise MergeResolutionError("CHANGELOG.md has no version headings")
    preamble = text[: headings[0].start()].rstrip()
    sections = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append((heading.group(1), text[heading.start() : end].strip()))
    return preamble, sections


def _remove_reference_links(text: str) -> Tuple[str, Dict[str, str]]:
    references: Dict[str, str] = {}
    lines = text.splitlines()
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1

    start = end
    while start:
        match = REFERENCE_LINK.fullmatch(lines[start - 1])
        if not match:
            break
        key, url = match.groups()
        if key in references and references[key] != url:
            raise MergeResolutionError(f"Conflicting duplicate changelog link: {key}")
        references[key] = url
        start -= 1
        while start and not lines[start - 1].strip():
            start -= 1

    references = dict(reversed(list(references.items())))
    body = "\n".join(lines[:start]).rstrip() if references else text.rstrip()
    return body, references


def merge_release_changelog(main_text: str, release_text: str, version: str) -> str:
    """Keep main's Unreleased notes and insert the release branch's version entry."""
    main_body, main_links = _remove_reference_links(main_text)
    release_body, release_links = _remove_reference_links(release_text)
    main_preamble, main_sections = _split_changelog(main_body)
    _, release_sections = _split_changelog(release_body)

    release_entry = next(
        (section for key, section in release_sections if key == version), None
    )
    if release_entry is None:
        raise MergeResolutionError(
            f"Release changelog has no section for version {version}"
        )

    existing_index = next(
        (index for index, (key, _) in enumerate(main_sections) if key == version),
        None,
    )
    if existing_index is None:
        unreleased_index = next(
            (
                index
                for index, (key, _) in enumerate(main_sections)
                if key == "Unreleased"
            ),
            None,
        )
        if unreleased_index is None:
            raise MergeResolutionError("Main changelog has no [Unreleased] section")
        main_sections.insert(unreleased_index + 1, (version, release_entry))
    elif main_sections[existing_index][1] != release_entry:
        raise MergeResolutionError(
            f"Main changelog already has a different section for version {version}"
        )

    body = main_preamble + "\n\n" + "\n\n".join(section for _, section in main_sections)

    links = dict(main_links)
    for key in ("Unreleased", version):
        if key in release_links:
            links[key] = release_links[key]
    for key, url in release_links.items():
        links.setdefault(key, url)

    ordered_keys = [key for key in ("Unreleased", version) if key in links]
    ordered_keys.extend(key for key in main_links if key not in ordered_keys)
    ordered_keys.extend(key for key in release_links if key not in ordered_keys)
    if ordered_keys:
        body += "\n\n" + "\n".join(f"[{key}]: {links[key]}" for key in ordered_keys)
    return body.rstrip() + "\n"


def _git_output(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise MergeResolutionError(detail or f"git {' '.join(args)} failed")
    return result.stdout


def resolve_release_merge(repo: Path, version: str, next_dev_version: str) -> List[str]:
    """Resolve only validated release metadata conflicts in the active merge."""
    repo = repo.resolve()
    paths = [
        path.decode("utf-8")
        for path in _git_output(
            repo, "diff", "--name-only", "--diff-filter=U", "-z"
        ).split(b"\0")
        if path
    ]
    if not paths:
        return []

    unexpected = sorted(set(paths) - KNOWN_CONFLICTS)
    if unexpected:
        raise MergeResolutionError(
            "Unexpected merge conflicts require manual resolution: "
            + ", ".join(unexpected)
        )

    resolutions: Dict[str, str] = {}
    for path in paths:
        if path == ".wolf/STATUS.md":
            resolutions[path] = _git_output(repo, "show", f":2:{path}").decode("utf-8")
        elif path == "CHANGELOG.md":
            main_changelog = _git_output(repo, "show", ":2:CHANGELOG.md").decode(
                "utf-8"
            )
            release_changelog = _git_output(repo, "show", ":3:CHANGELOG.md").decode(
                "utf-8"
            )
            resolutions[path] = merge_release_changelog(
                main_changelog, release_changelog, version
            )
        else:
            conflicted = (repo / path).read_text(encoding="utf-8")
            resolutions[path] = resolve_version_conflicts(
                conflicted, path, next_dev_version
            )

    for path, content in resolutions.items():
        (repo / path).write_text(content, encoding="utf-8")
        _git_output(repo, "add", "--", path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--next-dev-version", required=True)
    args = parser.parse_args()

    try:
        resolved = resolve_release_merge(
            args.repo, args.release_version, args.next_dev_version
        )
    except (MergeResolutionError, OSError) as error:
        print(f"Release merge conflict resolution stopped: {error}", file=sys.stderr)
        return 1

    if resolved:
        print("Resolved known release metadata conflicts: " + ", ".join(resolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
