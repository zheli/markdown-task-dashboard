# 004 — Add dark mode toggle to dashboard

**Type:** Task
**Status:** ✅ Complete
**Created:** 2025-07-15
**Updated:** 2025-07-15

## Goal

Add a dark mode toggle to the dashboard UI. Default to the user's OS preference
(prefers-color-scheme), with a manual override button in the header. Persist the
user's choice in localStorage.

## Progress

- [x] Add `[data-theme="dark"]` CSS variables with dark palette
- [x] Override hard-coded colors (filter active bg, table header bg) for dark theme
- [x] Add toggle control in header (next to Refresh)
- [x] Add JS: detect OS preference, toggle theme, persist in localStorage
- [x] Listen for OS preference changes when no manual override is set

## Notes

- Pure frontend change — no modifications to dashboard.py
- Uses `data-theme` attribute on `<html>` element
- Toggle is a pill-shaped card with a "Dark mode" label and a sliding knob
- No external icon or font dependencies
