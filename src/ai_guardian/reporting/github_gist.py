"""User-owned diagnostic Gists, with separate native upload consent and receipts."""

import json
import logging
import os
import re
import uuid
from pathlib import Path
from time import monotonic

from ai_guardian.reporting import github_support as github
from ai_guardian.ui.support_review import diagnostic_sort_key

logger = logging.getLogger(__name__)
JOURNAL_FILE = ".github-gist.json"
UPLOAD_WARNING = (
    "Upload the reviewed files to an unlisted Gist owned by your authenticated GitHub account. "
    "Unlisted is not private: anyone with the link can read it. A later public Discussion will expose that link. "
    "You can manage or delete your Gist, but deletion cannot retract copies or forks. "
    "Nothing is uploaded until you explicitly approve this step."
)
UNCERTAIN_MESSAGE = (
    "Gist upload outcome is uncertain. Check your own GitHub Gists before retrying; "
    "automatic re-upload is blocked. No Discussion was created by this attempt."
)


def valid_url(url) -> bool:
    return (
        isinstance(url, str)
        and re.fullmatch(
            r"https://gist\.github\.com/[A-Za-z0-9-]{1,39}/[a-f0-9]{5,64}", url
        )
        is not None
    )


def receipt(bundle: dict) -> dict | None:
    """Read only bounded regular metadata; incomplete mutations block re-upload."""
    path = Path(bundle["temp_path"]) / JOURNAL_FILE
    url = ""
    try:
        state = github._read_journal(path)
        if state is None:
            return None
        if valid_url(state.get("url")):
            url = state["url"]
        if (
            state.get("status") != "ready"
            or not isinstance(state.get("id"), str)
            or not re.fullmatch(r"[a-f0-9]{5,64}", state["id"])
            or not isinstance(state.get("login"), str)
            or state.get("url")
            != f"https://gist.github.com/{state['login']}/{state['id']}"
            or not valid_url(state.get("url"))
            or not isinstance(state.get("account_id"), str)
            or not isinstance(state.get("fingerprint"), str)
        ):
            raise ValueError("Unverified receipt")
        return state
    except (OSError, ValueError, TypeError):
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True, gist_url=url
        ) from None


def recovery_url(bundle: dict) -> str:
    """Recover only safe receipt metadata when a later unexpected step fails."""
    if not bundle.get("temp_path"):
        return ""
    try:
        saved = receipt(bundle)
        return saved["url"] if saved else ""
    except github.GitHubError as exc:
        return exc.gist_url


def uploaded_notice(url: str) -> str:
    return (
        f"\nDiagnostic Gist already uploaded: {url}. Open it to manage or delete it; "
        "deleting cannot retract copies or forks. This workflow does not delete your Gist."
        if valid_url(url)
        else ""
    )


def prepare_files(
    files: dict[str, bytes], client: github.GitHubClient
) -> tuple[dict, list]:
    """Create inert, collision-free filenames and exact sanitized text to review."""
    payload: dict[str, dict[str, str]] = {}
    summary = []
    for name in sorted(files, key=diagnostic_sort_key):
        if name == github.CONTEXT_FILE:
            continue
        raw = files[name]
        text, count = github._publication_text(client, raw.decode("utf-8"))
        label, label_count = github._publication_text(client, name)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", label)[:120].strip(".") or "diagnostic"
        if Path(safe).suffix.lower() not in {
            ".txt",
            ".log",
            ".json",
            ".jsonl",
            ".toml",
            ".yaml",
            ".yml",
        }:
            safe += ".txt"
        gist_name = f"{len(payload) + 1:03d}-{safe}"
        payload[gist_name] = {"content": text}
        summary.append(
            {"name": name, "gist_name": gist_name, "redactions": count + label_count}
        )
    if (
        not payload
        or len(payload) > 100
        or sum(len(item["content"].encode("utf-8")) for item in payload.values())
        > github.MAX_INPUT_BYTES
    ):
        raise github.GitHubError(github.MANUAL_MESSAGE, code="manual_required")
    return payload, summary


def description(bundle_id: str, client: github.GitHubClient) -> str:
    return (
        f"AI Guardian support bundle {github._publication_text(client, bundle_id)[0]}"
    )


def validate(
    data: dict, identity: dict, description: str, files: dict, *, gist_id: str = ""
) -> dict:
    """Do not trust a returned URL, owner, visibility, truncated or changed files."""
    if not isinstance(data, dict):
        raise github.GitHubError(
            "The Gist API response could not be verified.", code="changed"
        )
    owner = data.get("owner")
    identifier = data.get("id")
    actual = data.get("files")
    if (
        not isinstance(identifier, str)
        or not re.fullmatch(r"[a-f0-9]{5,64}", identifier)
        or (gist_id and identifier != gist_id)
        or data.get("html_url")
        != f"https://gist.github.com/{identity['login']}/{identifier}"
        or not isinstance(owner, dict)
        or owner.get("node_id") != identity["account_id"]
        or owner.get("login") != identity["login"]
        or owner.get("type") != "User"
    ):
        raise github.GitHubError(
            "The diagnostic Gist owner or URL could not be verified. Check your own GitHub Gists before retrying.",
            code="changed",
        )
    if (
        data.get("public") is not False
        or data.get("description") != description
        or data.get("truncated", False) is not False
        or not isinstance(actual, dict)
        or set(actual) != set(files)
        or any(
            not isinstance(item, dict)
            or item.get("truncated", False) is not False
            or item.get("content") != files[name]["content"]
            for name, item in actual.items()
        )
    ):
        raise github.GitHubError(
            "The Gist visibility or exact uploaded files could not be verified. Check your Gists manually before retrying.",
            code="changed",
            gist_url=data["html_url"],
        )
    return {"id": identifier, "url": data["html_url"]}


def verify(
    client: github.GitHubClient,
    state: dict,
    identity: dict,
    description: str,
    files: dict,
) -> None:
    validate(
        client.gist_request("GET", state["id"]),
        identity,
        description,
        files,
        gist_id=state["id"],
    )


def ensure_gist(
    bundle_id: str,
    bundle: dict,
    files: dict[str, bytes],
    client: github.GitHubClient,
    identity: dict,
    request: dict,
) -> tuple[dict, dict, list]:
    """Upload only on native approval, or verify and reuse an exact saved Gist."""
    payload, summary = prepare_files(files, client)
    for item in summary:
        item["redactions"] += next(
            (
                f.get("redactions", 0)
                for f in bundle.get("files", [])
                if f["name"] == item["name"]
            ),
            0,
        )
    gist_description = description(bundle_id, client)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    diagnostics = {
        name: raw for name, raw in files.items() if name != github.CONTEXT_FILE
    }
    fingerprint = github._fingerprint(
        identity, "", gist_description, encoded, diagnostics
    )
    saved = receipt(bundle)
    if saved:
        if (
            saved["fingerprint"] != fingerprint
            or saved["account_id"] != identity["account_id"]
            or saved["login"] != identity["login"]
        ):
            raise github.GitHubError(
                "The saved Gist does not match this account or selected files. Manage or delete the existing Gist and prepare a new bundle for changed files.",
                code="changed",
                gist_url=saved["url"],
            )
        verify(client, saved, identity, gist_description, payload)
        return saved, payload, summary
    preview = (
        f"Gist description: {gist_description}\nVisibility: unlisted (not private)\n\n"
    )
    for name, item in payload.items():
        preview += f"### {name}\n{github._fenced(item['content'])}\n\n"
    deadline = github._approval_deadline(bundle)
    upload_request = {
        **request,
        "mode": "upload",
        "request_id": uuid.uuid4().hex,
        "destination": f"https://gist.github.com/{identity['login']} (unlisted Gist)",
        "warning": UPLOAD_WARNING,
        "title": gist_description,
        "body": preview,
        "category": "Unlisted Gist upload",
        "files": summary,
        "context_redactions": 0,
    }
    reply = github.review_dialog(upload_request)
    if reply is None or reply.get("approved") is not True:
        raise github.GitHubError(
            "Gist upload cancelled. No files were uploaded and no Discussion was created.",
            code="cancelled",
        )
    if reply.get("request_id") != upload_request["request_id"]:
        raise github.GitHubError(
            "The Gist upload approval could not be verified.", code="changed"
        )
    current = github._read_files(bundle)
    github.Approval(fingerprint, deadline).consume(
        github._fingerprint(
            client.discover(),
            "",
            gist_description,
            encoded,
            {name: raw for name, raw in current.items() if name != github.CONTEXT_FILE},
        )
    )
    path = Path(bundle["temp_path"]) / JOURNAL_FILE
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True
        ) from None
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"status": "submitting"}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if monotonic() >= deadline:
            raise github.GitHubError(
                "Gist upload approval expired. Review again.", code="changed"
            )
        data = client.gist_request(
            "POST",
            payload={
                "description": gist_description,
                "public": False,
                "files": payload,
            },
        )
    except github.GitHubError as exc:
        if not exc.uncertain:
            path.unlink()
            raise
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True
        ) from None
    except (OSError, ValueError, TypeError):
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True
        ) from None
    try:
        state = {
            **validate(data, identity, gist_description, payload),
            "status": "ready",
            "fingerprint": fingerprint,
            "account_id": identity["account_id"],
            "login": identity["login"],
        }
    except github.GitHubError as exc:
        if exc.gist_url:
            try:
                github._write_journal(
                    path, {"status": "uncertain", "url": exc.gist_url}
                )
            except (OSError, ValueError):
                logger.error("Unverified support Gist receipt could not be saved")
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True, gist_url=exc.gist_url
        ) from None
    try:
        github._write_journal(path, state)
    except (OSError, ValueError):
        logger.error("Uploaded support Gist receipt could not be saved")
        raise github.GitHubError(
            UNCERTAIN_MESSAGE, code="uncertain", uncertain=True, gist_url=state["url"]
        ) from None
    return state, payload, summary
