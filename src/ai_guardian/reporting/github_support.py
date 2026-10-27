"""Public support Discussions with backend-enforced, user-only review.

No caller-provided approval, identity, repository, URL, or category ID is accepted.
Authentication is pinned for the whole review. The native dialog is the only
approval issuer; neither terminal input nor an HTTP approval endpoint is used.
"""

import hashlib
import json
import logging
import os
import re
import stat
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from types import MappingProxyType
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ai_guardian.ui.support_review import diagnostic_sort_key

logger = logging.getLogger(__name__)

DESTINATION = "github-discussions"
REPOSITORY = "RedHatProductSecurity/ai-guardian"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
CATEGORIES = MappingProxyType({"bug-reports": "Bug Reports", "q-a": "Q&A"})
CONTEXT_FILE = "support-context.json"
JOURNAL_FILE = ".github-submission.json"
MAX_BODY_BYTES = 60_000
MAX_INPUT_BYTES = 1_000_000
APPROVAL_SECONDS = 300
PUBLIC_WARNING = (
    "This repository is public. Sanitization is not a guarantee of confidentiality. "
    "Publishing exposes your message and the diagnostic Gist link; unlisted is not private. "
    "Review the exact title, body, and selected diagnostic files before proceeding."
)
MANUAL_MESSAGE = (
    "No discussion was created. The selected complete files cannot be uploaded as "
    "bounded UTF-8 Gist diagnostics (1,000,000 input bytes and at most 100 files). "
    "Uncheck files and review again, or run support send again and choose Create ZIP only for a separately arranged private support channel. "
    "No files were shortened during sending or embedded automatically."
)

_DISCOVERY = """query {
  viewer { id login __typename }
  repository(owner: "RedHatProductSecurity", name: "ai-guardian") {
    id nameWithOwner url hasDiscussionsEnabled
    discussionCategories(first: 100) {
      pageInfo { hasNextPage }
      nodes { id slug isAnswerable repository { id nameWithOwner } }
    }
  }
}"""
_CREATE = """mutation($input: CreateDiscussionInput!) {
  createDiscussion(input: $input) {
    discussion { url author { login } repository { id nameWithOwner }
      category { id slug } }
  }
}"""


class GitHubError(Exception):
    """Only constant, credential-free messages may cross this boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "github",
        uncertain: bool = False,
        gist_url: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain
        self.gist_url = gist_url


def credentials_available() -> bool:
    """Check configured credentials locally, without login or network requests.

    GitHub validates the pinned credential during discovery, before any upload.
    Never use ``auth status`` here: it performs remote authentication checks and
    would make the credential-free local ZIP path depend on connectivity.
    """
    try:
        return bool(_credential())
    except GitHubError:
        return False


def _credential() -> str:
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GitHubError(
            "GitHub authentication is unavailable. Install GitHub CLI and authenticate your own account for github.com.",
            code="authentication",
        ) from None
    token = result.stdout.strip() if result.returncode == 0 else ""
    if not token or any(c.isspace() for c in token):
        raise GitHubError(
            "Authenticate your own GitHub CLI account for github.com with permission to create Gists and write public Discussions.",
            code="authentication",
        )
    return token


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the authentication header to a redirected destination.
        return None


class GitHubClient:
    """User-authorized gh credentials, kept only in memory and never logged."""

    def __init__(self):
        self._token = _credential()
        self._opener = build_opener(_NoRedirect())
        self._gist_scope: bool | None = None

    def scrub(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED]")

    def check_gist_permission(self) -> None:
        # Classic/OAuth tokens advertise granted scopes. Other credential types
        # may omit that header; GitHub still enforces permissions on the upload.
        # Never refresh credentials or request additional scopes automatically.
        if getattr(self, "_gist_scope", None) is False:
            raise GitHubError(
                "Your GitHub credential lacks Gist permission. Use your own account with Gist and Discussions write access, or choose Create ZIP only. No new files were uploaded by this attempt.",
                code="permissions",
            )

    def gist_request(
        self, method: str, gist_id: str = "", *, payload: dict | None = None
    ) -> dict:
        if not (
            (method == "POST" and not gist_id)
            or (method == "GET" and re.fullmatch(r"[a-f0-9]{5,64}", gist_id))
        ):
            raise GitHubError("An invalid Gist operation was rejected.", code="files")
        request = Request(
            "https://api.github.com/gists" + (f"/{gist_id}" if gist_id else ""),
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "ai-guardian-support",
            },
            method=method,
        )
        mutation = method == "POST"
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(MAX_INPUT_BYTES * 8 + 1)
            if len(raw) > MAX_INPUT_BYTES * 8:
                raise ValueError("Response too large")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            return data
        except HTTPError as exc:
            message = "GitHub rejected the Gist request. Check Gist availability, content limits and account permissions."
            if exc.code == 401:
                message = "GitHub authentication failed. Authenticate your own account before uploading diagnostics."
            elif exc.code in (403, 404, 429):
                message = "GitHub denied Gist access. Your authenticated account needs Gist write permission; check credentials and rate limits."
            raise GitHubError(
                message, code="gist", uncertain=mutation and exc.code >= 500
            ) from None
        except (OSError, URLError, HTTPException, ValueError):
            raise GitHubError(
                "The Gist API response could not be verified.",
                code="gist",
                uncertain=mutation,
            ) from None

    def _graphql(self, query: str, variables=None, *, mutation=False) -> dict:
        request = Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": variables or {}}).encode(
                "utf-8"
            ),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "ai-guardian-support",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                scopes = response.headers.get("X-OAuth-Scopes")
                if isinstance(scopes, str):
                    self._gist_scope = "gist" in {
                        scope.strip() for scope in scopes.split(",")
                    }
                raw = response.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("Response too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Invalid response")
        except HTTPError as exc:
            if exc.code == 401:
                message = "GitHub authentication failed. Re-authenticate your own account for github.com."
            elif exc.code in (403, 429):
                message = "GitHub denied the request: check Discussions write permission and API rate limits before retrying."
            elif exc.code == 422:
                message = "GitHub rejected the discussion content. Check the title and content-size limits."
            else:
                message = "GitHub API request failed. Check GitHub availability before retrying."
            raise GitHubError(message, uncertain=mutation and exc.code >= 500) from None
        except (OSError, URLError, HTTPException, ValueError):
            raise GitHubError(
                "GitHub network/API response failed. Check connectivity and GitHub availability.",
                uncertain=mutation,
            ) from None
        errors = payload.get("errors")
        if errors:
            kinds = (
                {
                    e["type"]
                    for e in errors
                    if isinstance(e, dict) and isinstance(e.get("type"), str)
                }
                if isinstance(errors, list)
                else set()
            )
            message = "GitHub rejected the request. Check Discussions availability and account permissions."
            if "RATE_LIMITED" in kinds:
                message = "GitHub API rate limit reached. Wait for the limit to reset before retrying."
            elif "FORBIDDEN" in kinds:
                message = "GitHub denied publication. Your authenticated account needs Discussions write permission."
            # Partial GraphQL results must not be mistaken for a safe retry.
            certain_rejection = (
                not payload.get("data")
                and kinds
                and kinds <= {"FORBIDDEN", "RATE_LIMITED", "UNAUTHORIZED"}
            )
            raise GitHubError(message, uncertain=mutation and not certain_rejection)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GitHubError(
                "GitHub returned an invalid API response.", uncertain=mutation
            )
        return data

    def discover(self) -> dict:
        data = self._graphql(_DISCOVERY)
        viewer = data.get("viewer") or {}
        repo = data.get("repository") or {}
        if (
            viewer.get("__typename") != "User"
            or not isinstance(viewer.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", viewer.get("login", ""))
        ):
            raise GitHubError(
                "GitHub must identify an authenticated individual user account.",
                code="authentication",
            )
        if (
            repo.get("nameWithOwner") != REPOSITORY
            or repo.get("url") != REPOSITORY_URL
            or not repo.get("id")
        ):
            raise GitHubError(
                "The canonical AI Guardian support repository could not be verified.",
                code="repository",
            )
        if repo.get("hasDiscussionsEnabled") is not True:
            raise GitHubError(
                "Discussions are unavailable in the canonical support repository.",
                code="categories",
            )
        connection = repo.get("discussionCategories") or {}
        if connection.get("pageInfo", {}).get("hasNextPage") is not False:
            raise GitHubError(
                "Support category discovery was incomplete; no publication is allowed.",
                code="categories",
            )
        categories = {}
        for category in connection.get("nodes", []):
            if not isinstance(category, dict) or category.get("slug") not in CATEGORIES:
                continue
            owner = category.get("repository") or {}
            slug = category["slug"]
            if (
                owner.get("id") != repo["id"]
                or owner.get("nameWithOwner") != REPOSITORY
                or not category.get("id")
                or slug in categories
            ):
                raise GitHubError(
                    "A support category does not match the canonical repository.",
                    code="categories",
                )
            if slug == "q-a" and category.get("isAnswerable") is not True:
                raise GitHubError(
                    "The Q&A support category must support accepted answers.",
                    code="categories",
                )
            categories[slug] = category["id"]
        if set(categories) != set(CATEGORIES) or len(set(categories.values())) != len(
            CATEGORIES
        ):
            raise GitHubError(
                "Bug Reports and Q&A must both be available in the canonical support repository.",
                code="categories",
            )
        return {
            "account_id": viewer["id"],
            "login": viewer["login"],
            "repository_id": repo["id"],
            "categories": categories,
        }

    def create(self, identity: dict, category: str, title: str, body: str) -> str:
        if category not in CATEGORIES:
            raise GitHubError(
                "Only Bug Reports and Q&A are supported.", code="categories"
            )
        data = self._graphql(
            _CREATE,
            {
                "input": {
                    "repositoryId": identity["repository_id"],
                    "categoryId": identity["categories"][category],
                    "title": title,
                    "body": body,
                }
            },
            mutation=True,
        )
        creation = data.get("createDiscussion")
        if not isinstance(creation, dict) or not isinstance(
            creation.get("discussion"), dict
        ):
            raise GitHubError(
                "GitHub publication could not be verified.", uncertain=True
            )
        discussion = creation["discussion"]
        repo = discussion.get("repository") or {}
        selected = discussion.get("category") or {}
        author = discussion.get("author") or {}
        if not all(isinstance(item, dict) for item in (repo, selected, author)):
            raise GitHubError(
                "GitHub publication could not be verified.", uncertain=True
            )
        url = discussion.get("url", "")
        if (
            not _valid_url(url)
            or repo.get("id") != identity["repository_id"]
            or repo.get("nameWithOwner") != REPOSITORY
            or selected.get("id") != identity["categories"][category]
            or selected.get("slug") != category
            or author.get("login") != identity["login"]
        ):
            raise GitHubError(
                "GitHub publication could not be verified.", uncertain=True
            )
        return url


def _valid_url(url) -> bool:
    return (
        isinstance(url, str)
        and re.fullmatch(re.escape(REPOSITORY_URL) + r"/discussions/[1-9][0-9]*", url)
        is not None
    )


def public_text(text: str) -> tuple[str, int]:
    """Normalize/neutralize threats, then fully remove secret and PII spans."""
    from ai_guardian.scanners.secret_redactor import SecretRedactor
    from ai_guardian.scanners.sanitizer import sanitize_text

    sanitized = sanitize_text(text, no_secrets=True, no_pii=True)
    text = sanitized["sanitized_text"]
    result = SecretRedactor(
        config={"enabled": True, "log_redactions": False}, pii_config={"enabled": True}
    ).redact(text)
    for redaction in sorted(
        result["redactions"], key=lambda r: r["position"], reverse=True
    ):
        start = redaction["position"]
        text = (
            text[:start] + "[REDACTED]" + text[start + redaction["original_length"] :]
        )
    return text, len(result["redactions"]) + sanitized["stats"]["total"]


def support_context(
    title: str, description: str, category: str, *, draft: bool = False
) -> tuple[dict, int]:
    if category not in CATEGORIES:
        raise GitHubError("Only Bug Reports and Q&A are supported.", code="categories")
    if (
        not isinstance(title, str)
        or not isinstance(description, str)
        or len(title) > 256
        or len(description.encode("utf-8")) > MAX_BODY_BYTES
    ):
        raise GitHubError(
            "Use a title of 1–256 characters and a bounded support description.",
            code="context",
        )
    title, title_count = public_text(title)
    description, description_count = public_text(description)
    if (not draft and not title.strip()) or any(
        ord(c) < 32 or ord(c) == 127 for c in title
    ):
        raise GitHubError(
            "A non-empty, single-line support title is required.", code="context"
        )
    if not draft and not description.strip():
        raise GitHubError("A support message is required.", code="context")
    return {
        "title": title,
        "description": description,
        "category": category,
    }, title_count + description_count


def _read_files(bundle: dict) -> dict[str, bytes]:
    root = Path(bundle["temp_path"])
    if root.is_symlink() or not root.is_dir():
        raise GitHubError("The reviewed bundle directory is unavailable.", code="files")
    allowed = {item["name"] for item in bundle.get("files", [])}
    included = bundle.get("include_files")
    if included is not None and (
        not isinstance(included, list)
        or any(not isinstance(name, str) or name not in allowed for name in included)
    ):
        raise GitHubError("The reviewed file selection is invalid.", code="files")
    files = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GitHubError(
                "Linked files or directories cannot be published as diagnostics.",
                code="files",
            )
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if path.name == ".ai-read-deny" or name in {JOURNAL_FILE, ".github-gist.json"}:
            continue
        if name not in allowed or not path.is_file() or path.stat().st_nlink > 1:
            raise GitHubError(
                "The bundle contains unreviewed or unsupported files. Prepare and review a new bundle.",
                code="files",
            )
        if included is not None and name not in included and name != CONTEXT_FILE:
            continue
        # A bounded read also protects against files growing between stat/read.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            attributes = os.fstat(stream.fileno())
            if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
                raise GitHubError(
                    "Only regular reviewed diagnostic files can be published.",
                    code="files",
                )
            raw = stream.read(MAX_INPUT_BYTES + 1)
        total += len(raw)
        if total > MAX_INPUT_BYTES:
            raise GitHubError(MANUAL_MESSAGE, code="manual_required")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise GitHubError(MANUAL_MESSAGE, code="manual_required") from None
        if b"\x00" in raw:
            raise GitHubError(MANUAL_MESSAGE, code="manual_required")
        files[name] = raw
    return files


def _context(files: dict[str, bytes]) -> dict:
    try:
        context = json.loads(files[CONTEXT_FILE])
        if not isinstance(context, dict) or set(context) != {
            "title",
            "description",
            "category",
        }:
            raise ValueError("Invalid context fields")
        return support_context(**context, draft=True)[0]
    except (KeyError, TypeError, ValueError):
        raise GitHubError(
            "Review a valid support-context.json containing only title, description, and an approved category.",
            code="context",
        ) from None


def _fenced(text: str) -> str:
    fence = "`" * max(3, max((len(m) + 1 for m in re.findall(r"`+", text)), default=3))
    return f"{fence}text\n{text}\n{fence}"


def _publication(
    bundle_id: str, gist_url: str, context: dict, client: GitHubClient
) -> tuple[str, str]:
    from ai_guardian.reporting.github_gist import valid_url

    if not valid_url(gist_url):
        raise GitHubError(
            "The diagnostic Gist link could not be verified.", code="files"
        )
    title = client.scrub(context["title"])
    body = (
        f"## Troubleshooting context\n{_fenced(client.scrub(context['description']))}\n\n"
        f"Bundle reference: `{_publication_text(client, bundle_id)[0]}`\n\n"
        "GitHub authentication identifies the submitting account. It does not prove "
        "diagnostic authenticity or official maintainer endorsement.\n\n"
        f"## Diagnostics\n[Reviewed files in the submitting user's Gist]({gist_url})\n\n"
        "The submitting user owns this Gist and can manage or delete it. Unlisted does not mean private.\n"
    )
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise GitHubError(
            "The Discussion message exceeds the 60,000-byte limit. Shorten the message; diagnostic files will not be embedded.",
            code="context",
        )
    return title, body


def _publication_text(client: GitHubClient, text: str) -> tuple[str, int]:
    scrubbed = client.scrub(text)
    sanitized, count = public_text(scrubbed)
    # Normalization can join an obfuscated authentication credential. Scrub
    # again after transformation and count credential removal as a redaction.
    final = client.scrub(sanitized)
    return final, count + int(scrubbed != text) + int(final != sanitized)


def _fingerprint(
    identity: dict, category: str, title: str, body: str, files: dict[str, bytes]
) -> str:
    payload = {
        "identity": identity,
        "repository": REPOSITORY,
        "category": category,
        "title": title,
        "body": body,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass
class Approval:
    """Private, in-memory capability: never returned to a CLI/MCP caller."""

    fingerprint: str
    expires_at: float
    used: bool = False

    def consume(self, fingerprint: str) -> None:
        used = self.used
        self.used = True
        if used or monotonic() >= self.expires_at or self.fingerprint != fingerprint:
            raise GitHubError(
                "Publication approval changed, expired, or was already used. Review and confirm again.",
                code="changed",
            )


def review_dialog(request: dict) -> dict | None:
    """A native child owns the UI event loop; no stdin/HTTP approval fallback."""
    import sys
    from ai_guardian.ui.display import get_preferred_ui, _ensure_tcl_library

    public_review = request.get("mode") in ("edit", "upload", "approve")
    if get_preferred_ui() == "headless" or os.environ.get("AI_GUARDIAN_NO_TKINTER"):
        raise GitHubError(
            (
                "Public publication requires the native user review dialog on your desktop. No discussion was created; retain the local bundle for manual review."
                if public_review
                else "Support review requires a native desktop dialog."
            ),
            code="review_unavailable",
        )
    try:
        _ensure_tcl_library()
        result = subprocess.run(
            # Anchor the approval issuer to our installed source, not a module
            # in the project cwd/PYTHONPATH. Isolated mode ignores Python env
            # overrides and user-site/cwd imports. Failure stays fail-closed.
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve().parents[1] / "ui" / "support_review.py"),
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=None if request.get("mode") == "result" else APPROVAL_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("Review unavailable")
        reply = json.loads(result.stdout)
        if reply is None:
            return None
        if (
            not isinstance(reply, dict)
            or reply.get("request_id") != request["request_id"]
        ):
            raise ValueError("Invalid review response")
        return reply
    except (OSError, subprocess.SubprocessError, ValueError):
        raise GitHubError(
            (
                "The native user review dialog is unavailable or timed out. No discussion was created; retain the bundle and review again on your desktop."
                if public_review
                else "The support dialog is unavailable or timed out."
            ),
            code="review_unavailable",
        ) from None


def _receipt(path: Path) -> dict | None:
    gist_url = ""
    try:
        receipt = _read_journal(path)
        if receipt is None:
            return None
        from ai_guardian.reporting.github_gist import valid_url

        if isinstance(receipt, dict) and valid_url(receipt.get("gist_url")):
            gist_url = receipt["gist_url"]
        if receipt.get("status") == "sent" and _valid_url(
            receipt.get("discussion_url")
        ):
            return {
                **receipt,
                "already_submitted": True,
                "message": "Discussion already created; no new diagnostics were sent.",
            }
    except (OSError, ValueError, AttributeError):
        logger.warning("Support publication receipt could not be validated")
    raise GitHubError(
        "Publication outcome is uncertain. Check the repository Discussions manually; automatic retry is blocked.",
        code="uncertain",
        gist_url=gist_url,
    )


def _read_journal(path: Path) -> dict | None:
    """Bounded, nonblocking reads of private regular mutation journals only."""
    if path.is_symlink():
        raise ValueError("Linked support receipt")
    try:
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
            raise ValueError("Unsupported support receipt")
        raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("Oversized support receipt")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid support receipt")
        return data


def _write_journal(path: Path, data: dict) -> None:
    """Update our existing receipt without following links or truncating first."""
    if path.is_symlink():
        raise ValueError("Linked support receipt")
    fd = os.open(
        path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
            raise ValueError("Unsupported support receipt")
        json.dump(data, stream)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def _approval_deadline(bundle: dict) -> float:
    expires = datetime.fromisoformat(bundle["created"]) + timedelta(
        minutes=bundle.get("ttl_minutes", 30)
    )
    remaining = (expires - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise GitHubError(
            "The bundle expired during review. Prepare a new bundle before publication.",
            code="expired",
        )
    return monotonic() + min(APPROVAL_SECONDS, remaining)


def send_discussion(bundle_id: str, bundle: dict) -> dict[str, Any]:
    """Review and publish once. All failure paths retain the reviewed artifacts."""
    from ai_guardian.reporting import github_gist

    path = Path(bundle["temp_path"]) / JOURNAL_FILE
    gist_url = ""
    try:
        if bundle.get("destination") != DESTINATION or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", bundle_id
        ):
            raise GitHubError(
                "The canonical support destination could not be verified.",
                code="repository",
            )
        previous = _receipt(path)
        if previous:
            return previous
        existing_gist = github_gist.receipt(bundle)
        if existing_gist:
            gist_url = existing_gist["url"]
        from ai_guardian.reporting.support_bundle import (
            _review_file_paths,
            _set_file_selection,
        )

        # Build the proposal before reading diagnostic contents. This lets users
        # exclude large/binary files instead of failing before the chooser opens.
        files = _read_files(
            {
                **bundle,
                "include_files": [
                    item["name"]
                    for item in bundle.get("files", [])
                    if item["name"] == CONTEXT_FILE
                ],
            }
        )
        context = (
            _context(files)
            if CONTEXT_FILE in files
            else support_context("", "", "bug-reports", draft=True)[0]
        )
        available = _review_file_paths(bundle)
        included = bundle.get("include_files")
        if included is None:
            included = [name for name in available if name == "doctor.json"]
        if not credentials_available():
            raise GitHubError(
                "Gist + Discussion requires authenticated GitHub credentials. Authenticate your own GitHub CLI account and reopen support, or choose Create ZIP only.",
                code="authentication",
            )
        client = GitHubClient()
        identity = client.discover()
        client.check_gist_permission()
        request = {
            "mode": "edit",
            "source": bundle.get("source", "Local tray host"),
            "request_id": uuid.uuid4().hex,
            "account": identity["login"],
            "repository": REPOSITORY,
            "destination": f"{REPOSITORY_URL}/discussions",
            "warning": PUBLIC_WARNING,
            "context": context,
            "temp_path": bundle["temp_path"],
            "files": sorted(
                (
                    f
                    for f in bundle.get("files", [])
                    if f["name"] in available and f["name"] != CONTEXT_FILE
                ),
                key=lambda item: diagnostic_sort_key(item["name"]),
            ),
            "include_files": included,
            "categories": dict(CATEGORIES),
        }
        reply = review_dialog(request)
        if reply is None:
            raise GitHubError(
                "Publication cancelled. No discussion was created; the reviewed bundle remains local.",
                code="cancelled",
            )
        if reply.get("request_id") != request["request_id"]:
            raise GitHubError("The user review could not be verified.", code="changed")
        context, context_redactions = support_context(
            reply.get("title", ""),
            reply.get("description", ""),
            reply.get("category", ""),
        )
        selection = reply.get("include_files")
        if not isinstance(selection, list) or not selection:
            raise GitHubError(
                "Select at least one diagnostic file before sending.", code="files"
            )
        _set_file_selection(bundle_id, bundle, selection)
        files = _read_files(bundle)  # honor removals made before the final preview
        if not (files.keys() - {CONTEXT_FILE}):
            raise GitHubError(
                "Select at least one diagnostic file before sending.", code="files"
            )
        # Validate the bounded message before uploading anything. The actual
        # returned Gist URL is substituted only in the final exact preview.
        _publication(
            bundle_id,
            f"https://gist.github.com/{identity['login']}/{'0' * 64}",
            context,
            client,
        )
        gist, gist_files, summary = github_gist.ensure_gist(
            bundle_id, bundle, files, client, identity, request
        )
        gist_url = gist["url"]
        title, body = _publication(bundle_id, gist_url, context, client)
        fingerprint = _fingerprint(identity, context["category"], title, body, files)
        deadline = _approval_deadline(bundle)
        request = {
            **request,
            "mode": "approve",
            "request_id": uuid.uuid4().hex,
            "category": CATEGORIES[context["category"]],
            "title": title,
            "body": body,
            "files": summary,
            "context_redactions": context_redactions,
            "gist_url": gist_url,
        }
        reply = review_dialog(request)
        if reply is None or reply.get("approved") is not True:
            raise GitHubError(
                "Publication cancelled. No discussion was created; the reviewed bundle remains local.",
                code="cancelled",
            )
        if reply.get("request_id") != request["request_id"]:
            raise GitHubError(
                "The user approval could not be verified.", code="changed"
            )
        approval = Approval(fingerprint, deadline)
        current_identity = client.discover()
        current_files = _read_files(bundle)
        approval.consume(
            _fingerprint(
                current_identity, context["category"], title, body, current_files
            )
        )
        github_gist.verify(
            client,
            gist,
            current_identity,
            github_gist.description(bundle_id, client),
            gist_files,
        )
        # Persist intent BEFORE the non-idempotent mutation. O_EXCL serializes
        # concurrent processes. clientMutationId is not an idempotency guarantee.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return _receipt(path) or {}
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"status": "submitting", "gist_url": gist_url}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if monotonic() >= deadline:
                raise GitHubError(
                    "Publication approval expired. Review and confirm again.",
                    code="changed",
                )
            url = client.create(identity, context["category"], title, body)
        except GitHubError as exc:
            if not exc.uncertain:
                path.unlink()  # only our own, definitively rejected attempt
                raise
            raise GitHubError(
                "Publication outcome is uncertain. Check the repository Discussions manually; automatic retry is blocked.",
                code="uncertain",
            ) from None
        except (OSError, ValueError, TypeError):
            raise GitHubError(
                "Publication outcome is uncertain. Check the repository Discussions manually; automatic retry is blocked.",
                code="uncertain",
            ) from None
        result = {
            "status": "sent",
            "destination": DESTINATION,
            "discussion_url": url,
            "gist_url": gist_url,
            "delivery_status": "complete",
            "message": f"Discussion created: {url}\nYou own the diagnostic Gist and can manage or delete it: {gist_url}",
        }
        try:
            # A crash during this write leaves an unreadable receipt, which also
            # blocks retries. Never remove the journal after successful creation.
            _write_journal(path, result)
        except (OSError, ValueError):
            logger.error(
                "Support discussion created but its receipt could not be saved"
            )
        return result
    except GitHubError as exc:
        gist_url = exc.gist_url or gist_url or github_gist.recovery_url(bundle)
        return {
            "status": "error",
            "destination": DESTINATION,
            "message": str(exc) + github_gist.uploaded_notice(gist_url),
            "error_code": exc.code,
            "delivery_status": (
                "uncertain"
                if exc.uncertain or exc.code == "uncertain"
                else "gist_only" if gist_url else "not_published"
            ),
            "temp_path": bundle["temp_path"],
            **({"gist_url": gist_url} if gist_url else {}),
        }
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("Support publication could not validate the reviewed artifacts")
        gist_url = gist_url or github_gist.recovery_url(bundle)
        return {
            "status": "error",
            "destination": DESTINATION,
            "message": "The reviewed bundle could not be validated. Review again before publishing."
            + (
                github_gist.uploaded_notice(gist_url)
                if gist_url
                else " Files remain local."
            ),
            "error_code": "files",
            "delivery_status": "gist_only" if gist_url else "not_published",
            "temp_path": bundle["temp_path"],
            **({"gist_url": gist_url} if gist_url else {}),
        }
