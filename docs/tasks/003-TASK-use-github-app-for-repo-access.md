# 003 — Use GitHub App for repo access

**Type:** Task
**Status:** ⏳ Not started
**Created:** 2025-07-15
**Updated:** 2025-07-15
**Blocked by:** 002 — Deploy dashboard to tasks.z12z.org (server `.env` update requires the server to exist)

## Goal

Replace the `GITHUB_TOKEN` personal access token with a GitHub App for fetching
repo task status. This improves security: permissions are scoped to specific
repos and actions, tokens are short-lived (1 hour), and auth is not tied to any
personal account.

## Pre-requisites (manual)

- [ ] Task 002 complete (server deployed)
- [ ] GitHub account/org admin access to create a GitHub App

## Progress

### 1. Create GitHub App
- [ ] Go to GitHub Settings → Developer settings → GitHub Apps → New GitHub App
- [ ] Set name, homepage URL (e.g. `https://tasks.z12z.org`)
- [ ] Disable webhooks
- [ ] Permissions: Repository permissions → Contents → **Read-only**; all others: None
- [ ] Set "Where can this GitHub App be installed?" → Only on this account
- [ ] Create the app; note the **App ID**
- [ ] Generate a **private key** (`.pem` file); store securely

### 2. Install app on target repos
- [ ] Install the app on each repo tracked by the dashboard
- [ ] Note the **Installation ID** (visible in the app installation URL:
  `https://github.com/settings/installations/<INSTALLATION_ID>`)

### 3. Add token generation to `dashboard.py`
- [ ] Add `PyJWT` and `cryptography` to `pyproject.toml` dependencies
- [ ] Implement a `get_installation_token(app_id, private_key_pem, installation_id) -> str` helper:
  - Build a JWT signed with RS256 (iat, exp, iss=app_id); valid max 10 minutes
  - POST to `https://api.github.com/app/installations/{installation_id}/access_tokens`
    with `Authorization: Bearer <jwt>`
  - Return the `token` field from the response (valid 1 hour)
- [ ] Cache the token and refresh when within 5 minutes of expiry
- [ ] Replace `Authorization: Bearer $GITHUB_TOKEN` in `fetch_github_markdown_file`
  with the installation token

### 4. Update environment variables
- [ ] Remove `GITHUB_TOKEN` from `dashboard.py`, `.env.example`, and `docker-compose.yml`
- [ ] Add the following vars:
  ```
  GITHUB_APP_ID=<app-id>
  GITHUB_APP_INSTALLATION_ID=<installation-id>
  GITHUB_APP_PRIVATE_KEY=<base64-encoded-pem-contents>
  ```
  Base64-encode the PEM for safe env var storage:
  ```bash
  base64 -w 0 private-key.pem
  ```
  Decode in `dashboard.py` with `base64.b64decode(os.environ["GITHUB_APP_PRIVATE_KEY"])`

### 5. Update docker-compose.yml
- [ ] Replace `GITHUB_TOKEN` env var with `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`,
  `GITHUB_APP_PRIVATE_KEY` in the `dashboard` service environment block

### 6. Update server `.env`
- [ ] SSH into `ubuntu@89.167.111.224`
- [ ] Remove `GITHUB_TOKEN` from `/home/ubuntu/markdown-task-dashboard/.env`
- [ ] Add the three new vars
- [ ] Restart the stack: `docker compose up -d`

### 7. Test
- [ ] Run locally with new env vars and verify dashboard fetches repo data
- [ ] Run tests: `uv run pytest`
- [ ] Verify on `https://tasks.z12z.org` after server update

## Notes

- Private key must never be committed to the repo. Use `.gitignore` if storing
  the `.pem` locally during development.
- `GITHUB_APP_PRIVATE_KEY` should be stored in a secrets manager in production;
  the `.env` approach on the server is acceptable for now but should be noted
  as a future improvement.
- Token caching avoids hitting rate limits on the installations API.
- The app only needs `Contents: read` — do not grant broader permissions.

## Next Steps

Complete task 002 first, then start with steps 1–2 (manual GitHub setup) before
touching code.
