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
    return INDEX_HTML.encode("utf-8")


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
            config = load_config(self.config_path)
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


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Markdown Task Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #65758b;
      --line: #d9e0e8;
      --accent: #136f63;
      --warn: #b7791f;
      --done: #2f855a;
      --danger: #c53030;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header, main { max-width: 1180px; margin: 0 auto; padding: 24px; }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 24px; font-weight: 700; }
    .meta { color: var(--muted); font-size: 14px; margin-top: 4px; }
    button {
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      border-radius: 6px;
      padding: 9px 13px;
      font: inherit;
      cursor: pointer;
      min-width: 92px;
    }
    button:disabled { opacity: .7; cursor: wait; }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 12px;
      margin: 24px 0;
    }
    .metric, .repo {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .metric span { display: block; color: var(--muted); font-size: 13px; }
    .metric strong { display: block; font-size: 28px; line-height: 1.2; margin-top: 4px; }
    .repos { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 24px; }
    .repo h2 { font-size: 16px; margin: 0 0 4px; }
    .repo a { color: var(--accent); text-decoration: none; }
    .counts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; font-size: 12px; background: #fbfcfd; }
    .error { color: var(--danger); margin-top: 10px; font-size: 13px; }
    .toolbar {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin: 0 0 12px;
      flex-wrap: wrap;
    }
    .filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .filter {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 999px;
      padding: 7px 10px;
      min-width: auto;
    }
    .filter[aria-pressed="true"] {
      border-color: var(--accent);
      background: #e7f3f0;
      color: var(--accent);
    }
    .table-wrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    table { border-collapse: collapse; width: 100%; min-width: 800px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; font-size: 14px; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; background: #fbfcfd; }
    tr:last-child td { border-bottom: 0; }
    td a { color: var(--accent); text-decoration: none; }
    .status-complete { color: var(--done); font-weight: 650; }
    .status-in_progress { color: var(--warn); font-weight: 650; }
    .status-not_started { color: var(--muted); font-weight: 650; }
    .status-unknown { color: var(--danger); font-weight: 650; }
    @media (max-width: 640px) {
      header { align-items: flex-start; flex-direction: column; }
      header, main { padding: 18px; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Markdown Task Dashboard</h1>
      <div class="meta" id="meta">Loading...</div>
    </div>
    <button id="refresh" type="button">Refresh</button>
  </header>
  <main>
    <section class="summary" id="summary"></section>
    <section class="repos" id="repos"></section>
    <section class="toolbar" aria-label="Task filters">
      <div class="filters" id="filters"></div>
      <div class="meta" id="visible-count"></div>
    </section>
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Repo</th>
            <th>Branch</th>
            <th>ID</th>
            <th>Type</th>
            <th>Title</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="tasks"></tbody>
      </table>
    </section>
  </main>
  <script>
    const summaryEl = document.querySelector("#summary");
    const reposEl = document.querySelector("#repos");
    const tasksEl = document.querySelector("#tasks");
    const metaEl = document.querySelector("#meta");
    const refreshButton = document.querySelector("#refresh");
    const filtersEl = document.querySelector("#filters");
    const visibleCountEl = document.querySelector("#visible-count");
    let dashboardData = null;
    let activeStatus = "all";

    const labels = {
      repositories: "Repositories",
      tasks: "Tasks",
      not_started: "Not started",
      in_progress: "In progress",
      complete: "Complete",
      unknown: "Unknown"
    };

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function renderSummary(summary) {
      summaryEl.innerHTML = Object.keys(labels).map((key) => `
        <div class="metric">
          <span>${labels[key]}</span>
          <strong>${summary[key] ?? 0}</strong>
        </div>
      `).join("");
    }

    function renderFilters() {
      const filterLabels = { all: "All", ...labels };
      filtersEl.innerHTML = ["all", "not_started", "in_progress", "complete", "unknown"].map((key) => `
        <button class="filter" type="button" data-status="${key}" aria-pressed="${activeStatus === key}">
          ${filterLabels[key]}
        </button>
      `).join("");
    }

    function renderRepos(repositories) {
      reposEl.innerHTML = repositories.map((repo) => `
        <article class="repo">
          <h2><a href="${escapeHtml(repo.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(repo.name)}</a></h2>
          <div class="meta">${escapeHtml(repo.branch)} · ${escapeHtml(repo.source)}</div>
          <div class="counts">
            ${Object.keys(labels).filter((key) => !["repositories", "tasks"].includes(key)).map((key) => `
              <span class="pill">${labels[key]}: ${repo.counts?.[key] ?? 0}</span>
            `).join("")}
          </div>
          ${repo.error ? `<div class="error">${escapeHtml(repo.error)}</div>` : ""}
        </article>
      `).join("");
    }

    function renderTasks(repositories) {
      const rows = repositories.flatMap((repo) => (repo.tasks || []).map((task) => ({ repo, task })));
      const visibleRows = activeStatus === "all" ? rows : rows.filter(({ task }) => task.status === activeStatus);
      visibleCountEl.textContent = `${visibleRows.length} of ${rows.length} tasks shown`;
      tasksEl.innerHTML = visibleRows.length ? visibleRows.map(({ repo, task }) => `
        <tr>
          <td><a href="${escapeHtml(repo.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(repo.name)}</a></td>
          <td>${escapeHtml(repo.branch)}</td>
          <td>${escapeHtml(task.id)}</td>
          <td>${escapeHtml(task.type)}</td>
          <td>${task.url ? `<a href="${escapeHtml(task.url)}" target="_blank" rel="noreferrer">${escapeHtml(task.title)}</a>` : escapeHtml(task.title)}</td>
          <td class="status-${escapeHtml(task.status)}">${escapeHtml(task.status_label || labels[task.status] || task.status)}</td>
        </tr>
      `).join("") : `<tr><td colspan="6">No tasks match this filter.</td></tr>`;
    }

    function renderDashboard(data) {
      renderSummary(data.summary);
      renderRepos(data.repositories);
      renderFilters();
      renderTasks(data.repositories);
      metaEl.textContent = `Generated ${new Date(data.generated_at).toLocaleString()} · default branch ${data.default_branch}`;
    }

    async function refresh() {
      refreshButton.disabled = true;
      refreshButton.textContent = "Loading";
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || `Request failed with ${response.status}`);
        }
        dashboardData = data;
        renderDashboard(data);
      } catch (error) {
        summaryEl.innerHTML = "";
        reposEl.innerHTML = `<article class="repo"><div class="error">${escapeHtml(error.message)}</div></article>`;
        tasksEl.innerHTML = `<tr><td colspan="6">Unable to load dashboard.</td></tr>`;
        metaEl.textContent = "Load failed";
      } finally {
        refreshButton.disabled = false;
        refreshButton.textContent = "Refresh";
      }
    }

    filtersEl.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-status]");
      if (!button || !dashboardData) return;
      activeStatus = button.dataset.status;
      renderDashboard(dashboardData);
    });

    refreshButton.addEventListener("click", refresh);
    refresh();
  </script>
</body>
</html>
"""


def main() -> None:
    port_value = os.environ.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT))
    try:
        port = int(port_value)
    except ValueError:
        raise SystemExit(f"BACKEND_PORT must be an integer, got {port_value!r}")

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Serving dashboard on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
