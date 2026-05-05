# Markdown Task Dashboard — Project Tracking

This file is the main index for the project. It contains project context and a
table of all tracked epics and tasks. Read this file at the start of a session.

For detailed progress, notes, and history, see the individual epic/task files
linked in the table below.

## Context

| Key | Value |
|-----|-------|
| Repository | `zheli/markdown-task-dashboard` |

## Current Status

Task 001 complete. Two new tasks planned: deploy the dashboard to production
(`tasks.z12z.org`) and replace the GitHub PAT with a GitHub App for repo access.
Task 004 (dark mode toggle) is complete.

## Tasks & Epics

| ID | Type | Title | Status | File |
|----|------|-------|--------|------|
| 001 | Task | Extract HTML template from dashboard.py | **✅ Complete** | [001-TASK-extract-html-template.md](tasks/001-TASK-extract-html-template.md) |
| 002 | Task | Deploy dashboard to tasks.z12z.org | ⏳ Not started | [002-TASK-deploy-to-ubuntu-server.md](tasks/002-TASK-deploy-to-ubuntu-server.md) |
| 003 | Task | Use GitHub App for repo access | ⏳ Not started | [003-TASK-use-github-app-for-repo-access.md](tasks/003-TASK-use-github-app-for-repo-access.md) |
| 004 | Task | Add dark mode toggle to dashboard | **✅ Complete** | [004-TASK-dark-mode-toggle.md](tasks/004-TASK-dark-mode-toggle.md) |

## How to Add a New Task or Epic

1. Find the next available ID by checking the table above.
2. Create a new file: `docs/tasks/{ID}-{EPIC|TASK}-{kebab-case-title}.md`
3. Use the epic/task file template.
4. Add a row to the **Tasks & Epics** table above.
