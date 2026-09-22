#!/usr/bin/env python3
"""
Skill Directory Discovery

Automatically discover skills from GitHub/GitLab directory URLs.

Features:
- GitHub directory listing via API
- GitLab directory listing via API
- Skill name extraction
- Caching with TTL
- Rate limiting handling
- Authentication support
"""

import hashlib
import importlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Set, Tuple, cast
from urllib.parse import urlparse



class _YamlModule(Protocol):
    def safe_load(self, stream: str) -> Any:
        ...


yaml = cast(_YamlModule, importlib.import_module("yaml"))

logger = logging.getLogger(__name__)

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.warning("requests library not installed - skill discovery not available")


def _parse_skill_frontmatter(content: str) -> Optional[str]:
    """
    Parse SKILL.md frontmatter and extract the skill name.

    Args:
        content: SKILL.md file content

    Returns:
        str or None: Skill name from frontmatter, or None if not found
    """
    try:
        # Check for YAML frontmatter delimiters
        if not content.startswith("---\n"):
            return None

        # Find the closing delimiter
        end_marker = content.find("\n---\n", 4)
        if end_marker == -1:
            # Try alternative ending (--- at end of file)
            end_marker = content.find("\n---", 4)
            if end_marker == -1:
                return None

        # Extract frontmatter YAML
        frontmatter_yaml = content[4:end_marker]

        # Parse YAML
        frontmatter = yaml.safe_load(frontmatter_yaml)

        if not isinstance(frontmatter, dict):
            return None

        # Extract name field
        name = frontmatter.get("name")
        if name and isinstance(name, str):
            return name.strip()

        return None

    except Exception as e:
        logger.debug(f"Error parsing skill frontmatter: {e}")
        return None


class SkillDiscovery:
    """
    Discover skills from GitHub/GitLab directory URLs.

    Supports:
    - GitHub: https://github.com/org/repo/tree/branch/path
    - GitLab: https://gitlab.com/org/repo/-/tree/branch/path
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize skill discovery.

        Args:
            cache_dir: Optional cache directory. If None, uses XDG_CACHE_HOME.
        """
        if cache_dir is None:
            cache_home = os.environ.get(
                "XDG_CACHE_HOME", os.path.expanduser("~/.cache")
            )
            cache_dir = Path(cache_home) / "ai-guardian" / "skill-directories"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def discover_skills(
        self,
        directory_url: str,
        cache_ttl_hours: int = 24,
        token_env: Optional[str] = None,
    ) -> Set[str]:
        """
        Discover skills from a directory URL.

        Args:
            directory_url: GitHub or GitLab directory URL
            cache_ttl_hours: Cache TTL in hours (default: 24)
            token_env: Optional environment variable name for authentication token
                      (e.g., "GITHUB_AI_SKILL_TOKEN")

        Returns:
            set: Set of skill names (e.g., {"Skill:daf-active", "Skill:gh-cli"})
        """
        if not HAS_REQUESTS:
            logger.warning(
                f"Cannot discover skills from {directory_url}: requests library not installed"
            )
            return set()

        # Check cache first
        cached_skills, cache_age_hours = self._get_cached_skills(directory_url)

        if cached_skills is not None and cache_age_hours < cache_ttl_hours:
            logger.debug(
                f"Using cached skills for {directory_url} (age: {cache_age_hours:.1f}h)"
            )
            return cached_skills

        # Check if it's a local filesystem path
        if not directory_url.startswith("http://") and not directory_url.startswith(
            "https://"
        ):
            # Local filesystem path
            skills = self._discover_local_skills(directory_url)
            if skills:
                self._save_to_cache(directory_url, skills)
                logger.info(
                    f"Discovered {len(skills)} skills from local path {directory_url}"
                )
            return skills

        # Parse directory URL (GitHub/GitLab)
        parsed = self._parse_directory_url(directory_url)
        if parsed is None:
            logger.error(f"Invalid directory URL: {directory_url}")
            return set()

        platform, hostname, owner, repo, branch, path = parsed

        # Discover skills from API
        if platform == "github":
            skills = self._discover_github_skills(
                hostname, owner, repo, branch, path, token_env
            )
        elif platform == "gitlab":
            skills = self._discover_gitlab_skills(
                hostname, owner, repo, branch, path, token_env
            )
        else:
            logger.error(f"Unknown platform: {platform}")
            return set()

        if skills:
            # Cache successful discoveries
            self._save_to_cache(directory_url, skills)
            logger.info(f"Discovered {len(skills)} skills from {directory_url}")
        else:
            logger.warning(f"No skills discovered from {directory_url}")

        return skills

    def _parse_directory_url(
        self, url: str
    ) -> Optional[Tuple[str, str, str, str, str, str]]:
        """
        Parse GitHub/GitLab directory URL.

        Args:
            url: Directory URL

        Returns:
            tuple or None: (platform, hostname, owner, repo, branch, path) or None if invalid
        """
        try:
            # GitHub: https://github.com/org/repo/tree/branch/path/to/dir
            # GitLab: https://gitlab.com/org/repo/-/tree/branch/path/to/dir

            parsed_url = urlparse(url)
            hostname = parsed_url.netloc

            # Determine platform
            if "github.com" in hostname:
                platform = "github"
            elif "gitlab" in hostname:
                platform = "gitlab"
            else:
                return None

            path_parts = parsed_url.path.strip("/").split("/")

            if platform == "github":
                # GitHub format: /org/repo/tree/branch/path/to/dir
                if len(path_parts) < 4 or path_parts[2] != "tree":
                    return None

                owner = path_parts[0]
                repo = path_parts[1]
                branch = path_parts[3]
                dir_path = "/".join(path_parts[4:]) if len(path_parts) > 4 else ""

            else:  # gitlab
                # GitLab format: /org/repo/-/tree/branch/path/to/dir
                # Or multi-level: /org/subgroup/repo/-/tree/branch/path

                # Find the "-/tree" separator
                try:
                    tree_index = path_parts.index("-")
                    if (
                        tree_index + 1 >= len(path_parts)
                        or path_parts[tree_index + 1] != "tree"
                    ):
                        return None
                except ValueError:
                    return None

                # Everything before "-" is the project path
                project_path = "/".join(path_parts[:tree_index])
                # Split project path into owner and repo
                # For simplicity, treat entire path as project identifier
                # GitLab API uses "org%2Fsubgroup%2Frepo" format

                # Get last part as repo, rest as owner
                if tree_index < 2:
                    return None

                repo = path_parts[tree_index - 1]
                owner = (
                    "/".join(path_parts[: tree_index - 1])
                    if tree_index > 1
                    else path_parts[0]
                )

                # Branch and path after "-/tree"
                if tree_index + 2 >= len(path_parts):
                    return None

                branch = path_parts[tree_index + 2]
                dir_path = (
                    "/".join(path_parts[tree_index + 3 :])
                    if len(path_parts) > tree_index + 3
                    else ""
                )

            return platform, hostname, owner, repo, branch, dir_path

        except Exception as e:
            logger.error(f"Error parsing directory URL {url}: {e}")
            return None

    def _discover_github_skills(
        self,
        hostname: str,
        owner: str,
        repo: str,
        branch: str,
        path: str,
        token_env: Optional[str] = None,
    ) -> Set[str]:
        """
        Discover skills from GitHub directory.

        Args:
            hostname: GitHub hostname (e.g., "github.com")
            owner: Repository owner
            repo: Repository name
            branch: Branch name
            path: Directory path
            token_env: Optional environment variable name for authentication token

        Returns:
            set: Set of skill names
        """
        try:
            # GitHub API endpoint
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"

            # Prepare headers
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            # Add authentication if available
            # Check custom token environment variable first, then fall back to GITHUB_TOKEN
            github_token = None
            token_source = None

            if token_env:
                github_token = os.environ.get(token_env)
                if github_token:
                    token_source = token_env
                    logger.debug(f"Using {token_env} for authentication")

            if not github_token:
                github_token = os.environ.get("GITHUB_TOKEN")
                if github_token:
                    token_source = "GITHUB_TOKEN"
                    logger.debug("Using GITHUB_TOKEN for authentication")

            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"

            # Fetch directory listing
            logger.debug(f"Fetching GitHub directory: {api_url}")
            response = requests.get(api_url, headers=headers, timeout=10)

            # Handle errors
            if response.status_code == 401:
                logger.error("GitHub authentication failed (401)")
                return set()
            elif response.status_code == 403:
                logger.error("GitHub rate limit exceeded or access forbidden (403)")
                return set()
            elif response.status_code == 404:
                logger.error(f"GitHub directory not found (404): {owner}/{repo}/{path}")
                return set()
            elif response.status_code != 200:
                logger.error(f"GitHub API error {response.status_code}")
                return set()

            # Parse response
            items = response.json()

            if not isinstance(items, list):
                logger.error("Unexpected GitHub API response format")
                return set()

            # Extract skill directories
            skills = set()
            for item in items:
                if item.get("type") == "dir":
                    dir_name = item.get("name", "")
                    # Skip hidden directories and common non-skill dirs
                    if (
                        dir_name
                        and not dir_name.startswith(".")
                        and dir_name not in ["__pycache__", "node_modules"]
                    ):
                        # Try to read SKILL.md frontmatter to get canonical name
                        skill_name = self._get_skill_name_from_github(
                            hostname,
                            owner,
                            repo,
                            branch,
                            f"{path}/{dir_name}" if path else dir_name,
                            dir_name,
                            headers,
                        )
                        skills.add(skill_name)
                        logger.debug(f"Found skill: {skill_name}")

            return skills

        except requests.exceptions.Timeout:
            logger.error("Timeout fetching GitHub directory")
            return set()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching GitHub directory: {e}")
            return set()
        except Exception as e:
            logger.error(f"Unexpected error discovering GitHub skills: {e}")
            return set()

    def _get_skill_name_from_github(
        self,
        hostname: str,
        owner: str,
        repo: str,
        branch: str,
        skill_path: str,
        dir_name: str,
        headers: Dict[str, str],
    ) -> str:
        """
        Get skill name from SKILL.md frontmatter on GitHub.

        Args:
            hostname: GitHub hostname
            owner: Repository owner
            repo: Repository name
            branch: Branch name
            skill_path: Path to skill directory
            dir_name: Directory name (fallback)
            headers: Request headers with authentication

        Returns:
            str: Skill name in format "Skill:name"
        """
        try:
            # Fetch SKILL.md file
            skill_md_path = f"{skill_path}/SKILL.md"
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{skill_md_path}?ref={branch}"

            logger.debug(f"Fetching SKILL.md: {api_url}")
            response = requests.get(api_url, headers=headers, timeout=10)

            if response.status_code == 200:
                file_data = response.json()
                # GitHub API returns base64-encoded content
                import base64

                content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

                # Parse frontmatter
                skill_name = _parse_skill_frontmatter(content)
                if skill_name:
                    logger.debug(
                        f"Using frontmatter name '{skill_name}' for directory '{dir_name}'"
                    )
                    return f"Skill:{skill_name}"
                else:
                    logger.warning(
                        f"No valid frontmatter name found in {skill_md_path}, using directory name"
                    )
            else:
                logger.warning(
                    f"SKILL.md not found for {skill_path} (HTTP {response.status_code}), using directory name"
                )

        except Exception as e:
            logger.debug(f"Error reading SKILL.md for {skill_path}: {e}")

        # Fallback to directory name
        return f"Skill:{dir_name}"

    def _discover_gitlab_skills(
        self,
        hostname: str,
        owner: str,
        repo: str,
        branch: str,
        path: str,
        token_env: Optional[str] = None,
    ) -> Set[str]:
        """
        Discover skills from GitLab directory.

        Args:
            hostname: GitLab hostname (e.g., "gitlab.com", "gitlab.example.com")
            owner: Repository owner/group
            repo: Repository name
            branch: Branch name
            path: Directory path
            token_env: Optional environment variable name for authentication token

        Returns:
            set: Set of skill names
        """
        try:
            # GitLab uses project ID or "owner%2Frepo" format
            # For multi-level groups: "org%2Fsubgroup%2Frepo"
            project_path = f"{owner}/{repo}" if owner else repo
            encoded_project = project_path.replace("/", "%2F")
            encoded_path = path.replace("/", "%2F") if path else ""

            # GitLab API endpoint
            # https://docs.gitlab.com/ee/api/repositories.html#list-repository-tree
            api_url = (
                f"https://{hostname}/api/v4/projects/{encoded_project}/repository/tree"
            )

            params = {
                "ref": branch,
                "per_page": 100,
            }

            if path:
                params["path"] = path

            # Prepare headers
            headers = {}

            # Add authentication if available
            # Check custom token environment variable first, then fall back to GITLAB_TOKEN
            gitlab_token = None
            token_source = None

            if token_env:
                gitlab_token = os.environ.get(token_env)
                if gitlab_token:
                    token_source = token_env
                    logger.debug(f"Using {token_env} for authentication")

            if not gitlab_token:
                gitlab_token = os.environ.get("GITLAB_TOKEN")
                if gitlab_token:
                    token_source = "GITLAB_TOKEN"
                    logger.debug("Using GITLAB_TOKEN for authentication")

            if gitlab_token:
                headers["PRIVATE-TOKEN"] = gitlab_token

            # Fetch directory listing
            logger.debug(f"Fetching GitLab directory: {api_url}")
            response = requests.get(api_url, headers=headers, params=params, timeout=10)

            # Handle errors
            if response.status_code == 401:
                logger.error("GitLab authentication failed (401)")
                return set()
            elif response.status_code == 403:
                logger.error("GitLab access forbidden (403)")
                return set()
            elif response.status_code == 404:
                logger.error(f"GitLab directory not found (404): {project_path}/{path}")
                return set()
            elif response.status_code != 200:
                logger.error(f"GitLab API error {response.status_code}")
                return set()

            # Parse response
            items = response.json()

            if not isinstance(items, list):
                logger.error("Unexpected GitLab API response format")
                return set()

            # Extract skill directories
            skills = set()
            for item in items:
                if item.get("type") == "tree":  # GitLab uses "tree" for directories
                    dir_name = item.get("name", "")
                    # Skip hidden directories and common non-skill dirs
                    if (
                        dir_name
                        and not dir_name.startswith(".")
                        and dir_name not in ["__pycache__", "node_modules"]
                    ):
                        # Try to read SKILL.md frontmatter to get canonical name
                        skill_name = self._get_skill_name_from_gitlab(
                            hostname,
                            project_path,
                            branch,
                            f"{path}/{dir_name}" if path else dir_name,
                            dir_name,
                            headers,
                        )
                        skills.add(skill_name)
                        logger.debug(f"Found skill: {skill_name}")

            return skills

        except requests.exceptions.Timeout:
            logger.error("Timeout fetching GitLab directory")
            return set()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching GitLab directory: {e}")
            return set()
        except Exception as e:
            logger.error(f"Unexpected error discovering GitLab skills: {e}")
            return set()

    def _get_skill_name_from_gitlab(
        self,
        hostname: str,
        project_path: str,
        branch: str,
        skill_path: str,
        dir_name: str,
        headers: Dict[str, str],
    ) -> str:
        """
        Get skill name from SKILL.md frontmatter on GitLab.

        Args:
            hostname: GitLab hostname
            project_path: Project path (owner/repo)
            branch: Branch name
            skill_path: Path to skill directory
            dir_name: Directory name (fallback)
            headers: Request headers with authentication

        Returns:
            str: Skill name in format "Skill:name"
        """
        try:
            # Fetch SKILL.md file
            skill_md_path = f"{skill_path}/SKILL.md"
            encoded_project = project_path.replace("/", "%2F")
            encoded_file_path = skill_md_path.replace("/", "%2F")

            api_url = f"https://{hostname}/api/v4/projects/{encoded_project}/repository/files/{encoded_file_path}/raw"
            params = {"ref": branch}

            logger.debug(f"Fetching SKILL.md: {api_url}")
            response = requests.get(api_url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                content = response.text

                # Parse frontmatter
                skill_name = _parse_skill_frontmatter(content)
                if skill_name:
                    logger.debug(
                        f"Using frontmatter name '{skill_name}' for directory '{dir_name}'"
                    )
                    return f"Skill:{skill_name}"
                else:
                    logger.warning(
                        f"No valid frontmatter name found in {skill_md_path}, using directory name"
                    )
            else:
                logger.warning(
                    f"SKILL.md not found for {skill_path} (HTTP {response.status_code}), using directory name"
                )

        except Exception as e:
            logger.debug(f"Error reading SKILL.md for {skill_path}: {e}")

        # Fallback to directory name
        return f"Skill:{dir_name}"

    def _discover_local_skills(self, directory_path: str) -> Set[str]:
        """
        Discover skills from local filesystem directory.

        Args:
            directory_path: Local filesystem path to skills directory

        Returns:
            set: Set of skill names (e.g., {"Skill:arc", "Skill:foo"})
        """
        try:
            dir_path = Path(directory_path).expanduser().resolve()

            if not dir_path.exists():
                logger.error(f"Local directory does not exist: {directory_path}")
                return set()

            if not dir_path.is_dir():
                logger.error(f"Path is not a directory: {directory_path}")
                return set()

            logger.debug(f"Scanning local directory: {dir_path}")

            # Extract skill directories
            skills = set()
            for item in dir_path.iterdir():
                if item.is_dir():
                    dir_name = item.name
                    # Skip hidden directories and common non-skill dirs
                    if (
                        dir_name
                        and not dir_name.startswith(".")
                        and dir_name not in ["__pycache__", "node_modules"]
                    ):
                        # Try to read SKILL.md frontmatter to get canonical name
                        skill_md_file = item / "SKILL.md"
                        skill_name = dir_name  # Default to directory name

                        if skill_md_file.exists() and skill_md_file.is_file():
                            try:
                                content = skill_md_file.read_text(encoding="utf-8")
                                frontmatter_name = _parse_skill_frontmatter(content)
                                if frontmatter_name:
                                    skill_name = frontmatter_name
                                    logger.debug(
                                        f"Using frontmatter name '{skill_name}' for directory '{dir_name}'"
                                    )
                                else:
                                    logger.warning(
                                        f"No valid frontmatter name in {skill_md_file}, using directory name"
                                    )
                            except Exception as e:
                                logger.debug(
                                    f"Error reading SKILL.md for {dir_name}: {e}"
                                )
                        else:
                            logger.warning(
                                f"SKILL.md not found in {item}, using directory name"
                            )

                        skill_name_formatted = f"Skill:{skill_name}"
                        skills.add(skill_name_formatted)
                        logger.debug(f"Found skill: {skill_name_formatted}")

            return skills

        except Exception as e:
            logger.error(f"Error discovering local skills from {directory_path}: {e}")
            return set()

    def _get_cached_skills(
        self, directory_url: str
    ) -> Tuple[Optional[Set[str]], float]:
        """
        Get cached skills if available.

        Args:
            directory_url: Directory URL that was cached

        Returns:
            tuple: (skills set or None, cache age in hours)
        """
        cache_file = self._get_cache_path(directory_url)

        if not cache_file.exists():
            return None, 0.0

        try:
            # Load cache
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            cached_at = cache_data.get("cached_at", 0)
            cached_skills = set(cache_data.get("skills", []))

            # Calculate cache age
            now = time.time()
            cache_age_seconds = now - cached_at
            cache_age_hours = cache_age_seconds / 3600.0

            return cached_skills, cache_age_hours

        except Exception as e:
            logger.warning(f"Error reading skill cache for {directory_url}: {e}")
            return None, 0.0

    def _save_to_cache(self, directory_url: str, skills: Set[str]) -> None:
        """
        Save discovered skills to cache.

        Args:
            directory_url: Directory URL being cached
            skills: Set of skill names
        """
        try:
            cache_file = self._get_cache_path(directory_url)

            # Create cache data
            cache_data = {
                "url": directory_url,
                "cached_at": time.time(),
                "skills": list(skills),
            }

            # Write to cache
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Saved {len(skills)} skills to cache for {directory_url}")

        except Exception as e:
            logger.warning(f"Error saving skill cache for {directory_url}: {e}")

    def _get_cache_path(self, directory_url: str) -> Path:
        """
        Get cache file path for a directory URL.

        Args:
            directory_url: Directory URL

        Returns:
            Path: Cache file path
        """
        # Create a hash of the URL for the filename
        url_hash = hashlib.sha256(directory_url.encode()).hexdigest()[:16]

        # Extract platform and owner for readable prefix
        parsed = self._parse_directory_url(directory_url)
        if parsed:
            platform, hostname, owner, repo, _, _ = parsed
            prefix = f"{platform}_{owner}_{repo}".replace("/", "_").replace(".", "_")
        else:
            prefix = "unknown"

        filename = f"{prefix}_{url_hash}.json"
        return self.cache_dir / filename

    def clear_cache(self, directory_url: Optional[str] = None) -> None:
        """
        Clear cached skill discoveries.

        Args:
            directory_url: Optional URL to clear. If None, clears all caches.
        """
        try:
            if directory_url is not None:
                # Clear specific URL
                cache_file = self._get_cache_path(directory_url)
                if cache_file.exists():
                    cache_file.unlink()
                    logger.info(f"Cleared skill cache for {directory_url}")
            else:
                # Clear all caches
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
                logger.info("Cleared all skill directory caches")

        except Exception as e:
            logger.error(f"Error clearing skill cache: {e}")

    def get_cache_stats(self) -> Dict:
        """
        Get skill cache statistics.

        Returns:
            dict: Cache statistics
        """
        stats: Dict[str, Any] = {
            "cache_dir": str(self.cache_dir),
            "total_cached": 0,
            "cache_files": [],
        }

        try:
            for cache_file in self.cache_dir.glob("*.json"):
                stats["total_cached"] += 1

                # Load cache metadata
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)

                cached_at = cache_data.get("cached_at", 0)
                url = cache_data.get("url", "unknown")
                skills = cache_data.get("skills", [])

                # Calculate age
                now = time.time()
                age_hours = (now - cached_at) / 3600.0

                stats["cache_files"].append(
                    {
                        "url": url,
                        "cached_at": cached_at,
                        "age_hours": age_hours,
                        "skill_count": len(skills),
                        "skills": skills,
                        "file": str(cache_file),
                    }
                )

        except Exception as e:
            logger.error(f"Error getting skill cache stats: {e}")

        return stats
