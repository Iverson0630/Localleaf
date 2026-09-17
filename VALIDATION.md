# Validation — 2026-09-04

- Python source compilation, JavaScript syntax, and zsh launcher syntax: passed.
- 7 core tests passed with network access restricted: English and Chinese typesetting, all three LaTeX engines, BibTeX and Biber, failed-build PDF retention, nested main files, ZIP traversal/size checks, symlink checks.
- 5 HTTP integration tests passed using temporary projects and a temporary loopback port: autosave revisions, history recovery, new/rename/delete, deleted-file conflicts, ZIP round trip, binary upload, settings, token/origin/host boundaries, local static assets.
- Default project compiled successfully and local HTTP service responded after restart.
- Browser screenshot and interaction QA was not performed. The optional WebMCP read-only tool was not validated in a supported browser context.
- Runtime: TinyTeX 2026.09 for macOS with CTeX/XeCJK/Fandol installed, approximately 804 MB.
