# 001 — Extract HTML template from dashboard.py

**Type:** Task
**Status:** ✅ Complete
**Created:** 2025-07-14
**Updated:** 2025-07-14

## Goal

Extract the `INDEX_HTML` inline string (dashboard.py lines 386–678) into a
separate `templates/index.html` file, and update `render_index()` to load it
from disk relative to the Python file's location using `Path(__file__).parent`.

## Progress

- [x] Create `templates/index.html` with the extracted HTML/CSS/JS
- [x] Update `render_index()` to read from `Path(__file__).parent / "templates" / "index.html"`
- [x] Remove `INDEX_HTML` constant from `dashboard.py`

## Notes

- `Path` is already imported in `dashboard.py`
- Template is loaded relative to `__file__` so it works regardless of working directory
- No caching — read from disk on every request (acceptable for a dashboard)

## Next Steps

Done — all steps complete.
