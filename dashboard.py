from __future__ import annotations

import base64
import dataclasses
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_HOST = "127.0.0.1"
PROJECT_PATHS = ("docs/PROJECT.md", "docs/projects.md")
STATUSES = ("not_started", "in_progress", "complete", "unknown")
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MOCK_MARKDOWN = """# Canton Infra - Project Tracking

## Tasks & Epics

| ID | Type | Title | Status | File |
|----|------|-------|--------|------|
| 001 | Epic | DevNet Validator Deployment | ✅ **Complete** | [001-EPIC-devnet-validator-deployment.md](tasks/001-EPIC-devnet-validator-deployment.md) |
| 002 | Task | GitHub Action Redeployment | ⏳ Not started | [002-TASK-github-action-redeployment.md](tasks/002-TASK-github-action-redeployment.md) |
| 003 | Epic | TestNet Deployment | 🚧 **In progress** | [003-EPIC-testnet-deployment.md](tasks/003-EPIC-testnet-deployment.md) |
| 004 | Epic | MainNet Deployment | 🚧 **In progress** | [004-EPIC-mainnet-deployment.md](tasks/004-EPIC-mainnet-deployment.md) |
| 005 | Task | Monitoring & Alerting | ⏳ Not started | [005-TASK-monitoring-alerting.md](tasks/005-TASK-monitoring-alerting.md) |
| 006 | Task | Node Identity Backup | ✅ **Complete** | [006-TASK-node-identity-backup.md](tasks/006-TASK-node-identity-backup.md) |
| 007 | Task | Secure Validator Auth | 🚧 **In progress** | [007-TASK-secure-validator-auth.md](tasks/007-TASK-secure-validator-auth.md) |
| 008 | Task | TLS & Public Access | 🚧 **In progress** | [008-TASK-tls-public-access.md](tasks/008-TASK-tls-public-access.md) |
| 009 | Task | AMM DEX Auth Setup | 🚧 **In progress** | [009-TASK-amm-dex-auth-setup.md](tasks/009-TASK-amm-dex-auth-setup.md) |
| 010 | Task | Fix CORS Headers for dApp Access | ✅ **Complete** | [010-TASK-fix-cors-headers.md](tasks/010-TASK-fix-cors-headers.md) |
| 011 | Epic | Canton dApp Manager | ⏳ Not started | [011-EPIC-dapp-manager.md](tasks/011-EPIC-dapp-manager.md) |
| 012 | Task | Nginx Upload Body Size Limit | ✅ **Complete** | [012-TASK-nginx-upload-body-size.md](tasks/012-TASK-nginx-upload-body-size.md) |
| 013 | Task | Expose gRPC Ledger API Publicly | ✅ **Complete** | [013-TASK-expose-grpc-endpoint.md](tasks/013-TASK-expose-grpc-endpoint.md) |
| 014 | Task | Bump Validator Image Tags (2026-03-09) | ✅ **Complete** | [014-TASK-bump-image-tags.md](tasks/014-TASK-bump-image-tags.md) |
| 015 | Task | Enable Daml-LF 2.dev on DevNet | ✅ **Complete** | [015-TASK-enable-2-dev-daml-lf.md](tasks/015-TASK-enable-2-dev-daml-lf.md) |
| 016 | Task | DevNet Auth0 Migration | ✅ **Complete** | [016-TASK-devnet-auth0-migration.md](tasks/016-TASK-devnet-auth0-migration.md) |
| 017 | Task | DevNet DA Utilities Setup | 🚧 **In progress** | [017-TASK-devnet-utilities-setup.md](tasks/017-TASK-devnet-utilities-setup.md) |
| 018 | Task | MainNet DEX Party Onboarding | ✅ **Complete** | [018-TASK-mainnet-dex-party-onboarding.md](tasks/018-TASK-mainnet-dex-party-onboarding.md) |
"""


@dataclasses.dataclass(frozen=True)
class RepositoryConfig:
    name: str
    branch: str


@dataclasses.dataclass(frozen=True)
class AppConfig:
    default_branch: str
    repositories: list[RepositoryConfig]


class ConfigError(ValueError):
    pass


class GitHubError(RuntimeError):
    pass


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping.")

    github = raw.get("github") or {}
    if not isinstance(github, dict):
        raise ConfigError("github must be a mapping when provided.")

    default_branch = github.get("default_branch") or "main"
    if not isinstance(default_branch, str) or not default_branch.strip():
        raise ConfigError("github.default_branch must be a non-empty string.")
    default_branch = default_branch.strip()

    repositories = raw.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ConfigError("repositories must be a non-empty list.")

    parsed_repositories: list[RepositoryConfig] = []
    for index, repo in enumerate(repositories, start=1):
        if isinstance(repo, str):
            name = repo.strip()
            branch = default_branch
        elif isinstance(repo, dict):
            name_value = repo.get("name")
            branch_value = repo.get("branch") or default_branch
            if not isinstance(name_value, str):
                raise ConfigError(f"repositories[{index}].name must be a string.")
            if not isinstance(branch_value, str):
                raise ConfigError(f"repositories[{index}].branch must be a string.")
            name = name_value.strip()
            branch = branch_value.strip()
        else:
            raise ConfigError(f"repositories[{index}] must be a mapping or string.")

        if not REPO_NAME_RE.match(name):
            raise ConfigError(f"Invalid repository name at repositories[{index}]: {name!r}")
        if not branch:
            raise ConfigError(f"repositories[{index}].branch must be non-empty.")
        parsed_repositories.append(RepositoryConfig(name=name, branch=branch))

    return AppConfig(default_branch=default_branch, repositories=parsed_repositories)


def github_project_url(repo_name: str, branch: str, path: str = PROJECT_PATHS[0]) -> str:
    quoted_path = urllib.parse.quote(path)
    quoted_ref = urllib.parse.quote(branch, safe="")
    return f"https://api.github.com/repos/{repo_name}/contents/{quoted_path}?ref={quoted_ref}"


def github_blob_url(repo_name: str, branch: str, path: str) -> str:
    quoted_branch = urllib.parse.quote(branch, safe="")
    quoted_path = urllib.parse.quote(path)
    return f"https://github.com/{repo_name}/blob/{quoted_branch}/{quoted_path}"


def fetch_github_markdown_file(repo_name: str, branch: str, path: str, token: str) -> str:
    request = urllib.request.Request(
        github_project_url(repo_name, branch, path),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "github-markdown-task-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == HTTPStatus.NOT_FOUND:
            raise GitHubError(f"{path} not found on branch {branch!r}") from error
        raise GitHubError(f"GitHub API returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise GitHubError(f"GitHub API request failed: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise GitHubError("GitHub API returned invalid JSON") from error

    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise GitHubError(f"GitHub API did not return a file for {path}")

    encoded_content = payload.get("content")
    if not isinstance(encoded_content, str):
        raise GitHubError(f"GitHub API response for {path} has no content")

    try:
        return base64.b64decode(encoded_content).decode("utf-8")
    except ValueError as error:
        raise GitHubError(f"GitHub API response for {path} is not valid base64") from error
    except UnicodeDecodeError as error:
        raise GitHubError(f"{path} is not UTF-8") from error


def fetch_project_markdown(repo_name: str, branch: str, token: str) -> tuple[str, str]:
    errors: list[str] = []
    for path in PROJECT_PATHS:
        try:
            return fetch_github_markdown_file(repo_name, branch, path, token), path
        except GitHubError as error:
            errors.append(str(error))

    raise GitHubError("; ".join(errors))


def normalize_status(raw_status: str) -> str:
    status = re.sub(r"[*_`]", "", raw_status).strip().lower()
    status = re.sub(r"\s+", " ", status)
    if "complete" in status or "✅" in raw_status:
        return "complete"
    if "in progress" in status or "🚧" in raw_status:
        return "in_progress"
    if "not started" in status or "⏳" in raw_status:
        return "not_started"
    return "unknown"


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def extract_link_target(raw_file: str) -> str | None:
    match = re.search(r"\[[^\]]+\]\(([^)]+)\)", raw_file)
    if not match:
        return None
    target = match.group(1).strip()
    if not target or target.startswith(("http://", "https://")):
        return target or None
    return f"docs/{target.lstrip('./')}"


def parse_project_markdown(markdown: str, repo_name: str, branch: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    tasks_heading_index = next(
        (index for index, line in enumerate(lines) if re.match(r"^#{2,}\s+Tasks\s*&\s*Epics\s*$", line.strip(), re.I)),
        -1,
    )
    search_lines = lines[tasks_heading_index + 1 :] if tasks_heading_index >= 0 else lines

    header_index = -1
    headers: list[str] = []
    for index, line in enumerate(search_lines):
        if not line.strip().startswith("|"):
            continue
        cells = split_table_row(line)
        normalized = [cell.lower() for cell in cells]
        if {"id", "type", "title", "status"}.issubset(set(normalized)):
            header_index = index
            headers = normalized
            break

    if header_index < 0:
        raise ValueError("Could not find a Tasks & Epics table.")

    column_indexes = {name: headers.index(name) for name in ("id", "type", "title", "status") if name in headers}
    file_index = headers.index("file") if "file" in headers else None

    tasks: list[dict[str, Any]] = []
    for line in search_lines[header_index + 1 :]:
        if not line.strip().startswith("|"):
            if tasks:
                break
            continue

        cells = split_table_row(line)
        if is_separator_row(cells):
            continue
        if len(cells) < len(headers):
            continue

        raw_file = cells[file_index] if file_index is not None else ""
        file_path = extract_link_target(raw_file)
        source_url = github_blob_url(repo_name, branch, file_path) if file_path and not file_path.startswith("http") else file_path
        tasks.append(
            {
                "id": cells[column_indexes["id"]],
                "type": cells[column_indexes["type"]],
                "title": re.sub(r"[*_`]", "", cells[column_indexes["title"]]).strip(),
                "status": normalize_status(cells[column_indexes["status"]]),
                "status_label": re.sub(r"[*_`]", "", cells[column_indexes["status"]]).strip(),
                "file": file_path,
                "url": source_url,
            }
        )

    return tasks


def empty_counts() -> dict[str, int]:
    return {status: 0 for status in STATUSES}


def count_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = empty_counts()
    for task in tasks:
        counts[task.get("status", "unknown")] = counts.get(task.get("status", "unknown"), 0) + 1
    return counts


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            os.environ.setdefault(key, value)


def dashboard_url() -> str:
    port = os.environ.get("FRONTEND_PORT") or os.environ.get("BACKEND_PORT") or str(DEFAULT_BACKEND_PORT)
    return f"http://{DEFAULT_FRONTEND_HOST}:{port}"


def build_status(config: AppConfig, token: str | None, use_mock_data: bool = False) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {"repositories": len(config.repositories), "tasks": 0, **empty_counts()}
    repositories: list[dict[str, Any]] = []

    for repo in config.repositories:
        source_path = PROJECT_PATHS[1] if use_mock_data else PROJECT_PATHS[0]
        repo_result: dict[str, Any] = {
            "name": repo.name,
            "branch": repo.branch,
            "source": source_path,
            "source_url": github_blob_url(repo.name, repo.branch, source_path),
            "status": "ok",
            "error": None,
            "counts": empty_counts(),
            "tasks": [],
        }

        if use_mock_data:
            markdown = MOCK_MARKDOWN
        elif not token:
            repo_result["status"] = "error"
            repo_result["error"] = "GITHUB_TOKEN is required."
            repositories.append(repo_result)
            continue
        else:
            markdown = None

        try:
            if markdown is None:
                markdown, source_path = fetch_project_markdown(repo.name, repo.branch, token)
                repo_result["source"] = source_path
                repo_result["source_url"] = github_blob_url(repo.name, repo.branch, source_path)
            tasks = parse_project_markdown(markdown, repo.name, repo.branch)
            counts = count_tasks(tasks)
            repo_result["tasks"] = tasks
            repo_result["counts"] = counts
            summary["tasks"] += len(tasks)
            for status in STATUSES:
                summary[status] += counts[status]
        except (GitHubError, ValueError) as error:
            repo_result["status"] = "error"
            repo_result["error"] = str(error)

        repositories.append(repo_result)

    return {
        "generated_at": generated_at,
        "default_branch": config.default_branch,
        "summary": summary,
        "repositories": repositories,
    }


def render_index() -> bytes:
    template_path = Path(__file__).parent / "templates" / "index.html"
    return template_path.read_bytes()


class DashboardHandler(BaseHTTPRequestHandler):
    config_path = os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", file=sys.stderr)

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_index())
            return

        if self.path == "/api/status":
            self.handle_status()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_status(self) -> None:
        try:
            config_path = os.environ.get("CONFIG_PATH", self.config_path)
            config = load_config(config_path)
            payload = build_status(config, os.environ.get("GITHUB_TOKEN"), truthy_env("MOCK_DATA"))
            status = HTTPStatus.OK
        except ConfigError as error:
            payload = {"error": str(error)}
            status = HTTPStatus.BAD_REQUEST

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    load_dotenv()
    port_value = os.environ.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT))
    try:
        port = int(port_value)
    except ValueError:
        raise SystemExit(f"BACKEND_PORT must be an integer, got {port_value!r}")

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Serving dashboard on {dashboard_url()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
