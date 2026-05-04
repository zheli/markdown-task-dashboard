import base64
import json
import urllib.error

import pytest

import dashboard


def test_load_config_uses_default_and_repo_branch_overrides(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
github:
  default_branch: main
repositories:
  - name: owner/one
  - name: owner/two
    branch: develop
""",
        encoding="utf-8",
    )

    config = dashboard.load_config(config_path)

    assert config.default_branch == "main"
    assert config.repositories == [
        dashboard.RepositoryConfig(name="owner/one", branch="main"),
        dashboard.RepositoryConfig(name="owner/two", branch="develop"),
    ]


def test_load_config_defaults_to_main(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
repositories:
  - name: owner/repo
""",
        encoding="utf-8",
    )

    config = dashboard.load_config(config_path)

    assert config.default_branch == "main"
    assert config.repositories[0].branch == "main"


def test_load_config_rejects_invalid_repo_name(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
repositories:
  - name: owner
""",
        encoding="utf-8",
    )

    with pytest.raises(dashboard.ConfigError, match="Invalid repository name"):
        dashboard.load_config(config_path)


def test_github_project_url_uses_resolved_branch():
    url = dashboard.github_project_url("owner/repo", "release/v1")

    assert url == "https://api.github.com/repos/owner/repo/contents/docs/PROJECT.md?ref=release%2Fv1"


def test_parse_project_markdown_handles_bold_and_emoji_statuses():
    markdown = """
# Example

## Tasks & Epics

| ID | Type | Title | Status | File |
|----|------|-------|--------|------|
| 001 | Epic | First Epic | **🚧 In progress** | [001-EPIC-first.md](001-EPIC-first.md) |
| 002 | Task | Done Task | **✅ Complete** | [002-TASK-done.md](002-TASK-done.md) |
| 003 | Task | Later Task | ⏳ Not started | [003-TASK-later.md](003-TASK-later.md) |
| 004 | Task | Strange Task | Blocked | [004-TASK-strange.md](004-TASK-strange.md) |
"""

    tasks = dashboard.parse_project_markdown(markdown, "owner/repo", "main")

    assert [task["status"] for task in tasks] == [
        "in_progress",
        "complete",
        "not_started",
        "unknown",
    ]
    assert tasks[0]["url"] == "https://github.com/owner/repo/blob/main/docs/001-EPIC-first.md"


def test_parse_project_markdown_rejects_missing_table():
    with pytest.raises(ValueError, match="Tasks & Epics table"):
        dashboard.parse_project_markdown("# No table", "owner/repo", "main")


def test_fetch_project_markdown_decodes_github_content(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            content = base64.b64encode(b"# Project").decode("utf-8")
            return json.dumps({"type": "file", "content": content}).encode("utf-8")

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", lambda request, timeout: Response())

    assert dashboard.fetch_project_markdown("owner/repo", "main", "token") == ("# Project", "docs/PROJECT.md")


def test_fetch_project_markdown_falls_back_to_lowercase_projects(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            content = base64.b64encode(b"# Lowercase").decode("utf-8")
            return json.dumps({"type": "file", "content": content}).encode("utf-8")

    def urlopen(request, timeout):
        calls.append(request.full_url)
        if "docs/PROJECT.md" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return Response()

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", urlopen)

    assert dashboard.fetch_project_markdown("owner/repo", "main", "token") == ("# Lowercase", "docs/projects.md")
    assert len(calls) == 2


def test_fetch_project_markdown_returns_clear_not_found_error(monkeypatch):
    def raise_404(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", raise_404)

    with pytest.raises(dashboard.GitHubError, match="not found"):
        dashboard.fetch_project_markdown("owner/repo", "main", "token")


def test_build_status_keeps_repo_level_errors():
    config = dashboard.AppConfig(
        default_branch="main",
        repositories=[dashboard.RepositoryConfig(name="owner/repo", branch="main")],
    )

    payload = dashboard.build_status(config, token=None)

    assert payload["repositories"][0]["status"] == "error"
    assert payload["repositories"][0]["error"] == "GITHUB_TOKEN is required."


def test_mock_data_builds_demo_dashboard_without_token():
    config = dashboard.AppConfig(
        default_branch="main",
        repositories=[dashboard.RepositoryConfig(name="zheli/canton-infra", branch="main")],
    )

    payload = dashboard.build_status(config, token=None, use_mock_data=True)

    assert payload["summary"]["tasks"] == 18
    assert payload["summary"]["complete"] == 9
    assert payload["summary"]["in_progress"] == 6
    assert payload["summary"]["not_started"] == 3
    assert payload["repositories"][0]["source"] == "docs/projects.md"
    assert payload["repositories"][0]["tasks"][0]["url"].endswith(
        "/blob/main/docs/tasks/001-EPIC-devnet-validator-deployment.md"
    )
