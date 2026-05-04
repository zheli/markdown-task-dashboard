# GitHub Markdown Task Dashboard

Local dashboard for checking markdown task status across GitHub repositories.
It reads `docs/PROJECT.md` or `docs/projects.md` from each configured repository
and branch, then shows task totals and per-repository status in a browser.
Use the status filter buttons to narrow the task table. Click a task title to
open its markdown detail file on GitHub.

## Configuration

Edit `config.yaml`:

```yaml
github:
  default_branch: main

repositories:
  - name: owner/repo
  - name: owner/another-repo
    branch: develop
```

Repository entries use `github.default_branch` unless they define `branch`.

## GitHub Token

Create a GitHub token with read access to the configured repositories and set:

```bash
export GITHUB_TOKEN=...
```

Do not commit tokens or `.env` files.

## Run Locally

```bash
uv sync
uv run dashboard.py
```

Open `http://127.0.0.1:8000`.

Override the backend port:

```bash
BACKEND_PORT=9000 uv run dashboard.py
```

## Run With Docker Compose

Create a local `.env` from `.env.example`, then set `GITHUB_TOKEN`.

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080`.

Override ports:

```bash
FRONTEND_PORT=9090 BACKEND_PORT=9000 docker compose up --build
```

Run the embedded demo data without a real token:

```bash
MOCK_DATA=true GITHUB_TOKEN=dummy docker compose up --build
```

## API

```http
GET /api/status
```

The response includes a generated timestamp, default branch, overall counts,
per-repository counts, repo-level errors, and task links to GitHub.
