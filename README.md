# LocalLeaf — Offline LaTeX Paper Editor

LocalLeaf provides an Overleaf-style three-pane layout for project files, LaTeX source, and PDF output. Files, editor assets, fonts, and the compiler are stored locally. The service only listens on `127.0.0.1`, so no account, cloud service, or online CDN is required.

## Getting Started

1. Open this folder in Finder and double-click **LocalLeaf.app** (or **启动 LocalLeaf.command**). When launched through the app, the service runs in the background without opening a Terminal window.
2. Your browser opens the [local workspace](http://127.0.0.1:8787). Keep the launcher running while you work.
3. Edit `main.tex` and press **⌘Enter** to compile. Changes are saved automatically 650 ms after you stop typing; press **⌘S** to save immediately.
4. Click the project name in the top bar to create a project in Chinese or English, or import a project ZIP downloaded from Overleaf.
5. Before quitting, wait for “All changes saved”, then press **Ctrl+C** in the launcher Terminal to stop the service.

TinyTeX and the Chinese CTeX / Fandol fonts are included in `runtime/TinyTeX/`, so LocalLeaf can compile offline. Dependencies may need to be downloaded during initial setup; launching, editing, saving, and compiling with installed packages do not require an Internet connection.

You can also start LocalLeaf from a Terminal:

```sh
cd /Users/sz5380/Phd/Software/localleaf
python3 server.py
```

If the default port is in use, run `python3 server.py --port 8788`.

## Features

- Multiple projects, folders, and file operations (create, upload, rename, and delete), with image and PDF previews.
- Add an existing local folder as a project. LocalLeaf keeps the source files in their original folder and displays the folder path in the project list; it does not copy them into `projects/`.
- Local CodeMirror editor with LaTeX syntax highlighting, line numbers, undo/redo, section outline, find and replace, equation/citation snippets, font-size controls, and split-pane resizing.
- Automatic saving; unsaved-change warnings when closing a page; cached drafts can be restored when reopening the same address in the same browser.
- Concurrent-edit detection based on file content digests. Conflicting edits are rejected instead of overwriting existing files; the current editing copy can be downloaded from the file menu.
- The previous contents of the most recent 200 changes are retained for each project. Deleted files also have recoverable versions. History is a local convenience feature, so back up important papers separately.
- XeLaTeX, pdfLaTeX, and LuaLaTeX; latexmk for multi-pass compilation, cross-references, and BibTeX / Biber.
- Manual or automatic compilation, real PDF preview and download, compilation logs, and ZIP import/export.
- Reverse PDF-to-source navigation: double-click text in the PDF to open the corresponding project file and jump to the related LaTeX line.
- One-click synchronization with Overleaf Git projects. The token is stored in the macOS Keychain and is not written into the paper directory.
- Git projects check the remote branch for new commits when opened; the sync button and a prominent notice show how many remote updates are waiting. Each file also shows its latest local modification time.
- Switch among light, dark, sepia, and ocean color themes, and between Chinese and English interface text. English is the default, and these preferences are saved locally in the browser.
- Project folders use the project name directly; duplicate names receive a `(2)` suffix.
- Compilation uses a project snapshot. If compilation fails, the last successful PDF is kept; a single compilation is stopped after 120 seconds.

## Migrating from Overleaf

Download the project source ZIP from Overleaf. In LocalLeaf, choose **Import ZIP** from the project menu, then open settings to confirm the main `.tex` file and compiler. Choose XeLaTeX for Chinese documents.

ZIP imports are limited to 2,000 files, 80 MB total after extraction, and 20 MB per file. Hidden configuration files are skipped, and a project `.latexmkrc` is not executed. After renaming files, update LaTeX references yourself.

Packages and fonts depend on the template. The bundled distribution covers common writing packages and Chinese/English templates but is not a complete TeX Live installation. If a journal template needs a package that is not installed, install it while online and verify that the project still compiles offline:

```sh
"$PWD/runtime/TinyTeX/bin/universal-darwin/tlmgr" install package-name
```

Run this command from the LocalLeaf folder. Projects that require special scripts or shell escape, such as `minted`, are not supported; use `listings` instead.

## Overleaf Git Synchronization

Overleaf Git is an advanced Overleaf feature. In the online project, open **Integrations → Git** and copy the Git URL. Then generate a Git authentication token in your Overleaf account settings. Click **Connect Overleaf** in LocalLeaf. On the first connection, choose whether to adopt the latest Overleaf version or keep the local version and upload it. Later, **Sync Overleaf** detects the remote `main` or `master` branch, pulls remote changes, commits local edits, and pushes the result. The username is `git`; the token is stored in the macOS Keychain.

## Files and Backups

`projects/<project-name>/` stores the original `.tex`, `.bib`, image, and other files directly, so they can also be opened in another editor. `.localleaf.json` stores project settings, `.history/` stores versions, and `.build/output.pdf` is the last successfully compiled PDF.

For a project added from an existing local folder, the project index is stored under `projects/`, while the source files, build output, and history remain in the selected folder.

**Export project** creates a source ZIP that can be uploaded to Overleaf again. It does not include local history or the PDF. To back up project settings and history, copy the entire `projects/` folder. Do not modify the same project with an external tool while it is compiling.

The compiler and local dependencies are stored in `runtime/` and `static/vendor/`. The current installation is for macOS Universal. When moving LocalLeaf to another Mac, that Mac needs Python 3. Windows and Linux require a platform-specific TeX Live installation; start the server with `python3 server.py`. All frontend static assets are included in the project.

## Verification

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary project directories and do not modify papers. They cover save conflicts, version recovery, path and ZIP validation, project export, keeping the previous PDF after compilation failure, Chinese and English compilation, and bibliography handling. HTTP tests require permission to listen on localhost.

## Sources and Licenses

LocalLeaf is an independent implementation and is not affiliated with Overleaf. Its interaction layout is inspired by the [Overleaf editor layout](https://docs.overleaf.com/navigating-in-the-editor/working-with-the-pdf-viewer/editor-and-pdf-layout-and-sizing).

- [CodeMirror 5.65.16](https://github.com/codemirror/codemirror5/tree/5.65.16): MIT; the license is retained in `static/vendor/LICENSE`.
- [TinyTeX 2026.09](https://github.com/rstudio/tinytex-releases/releases/tag/v2026.09): based on TeX Live; bundled components follow their respective licenses, documented in `runtime/TinyTeX/LICENSE.TL` and the individual package licenses.
- [TinyTeX documentation](https://yihui.org/tinytex/).

## Launcher Icon

Drag `LocalLeaf.app` from Finder into a regular custom item in Tab Launcher. This entry uses the green book icon. Keep the application bundle in this folder. It starts the existing launcher script through Terminal. The app bundle structure, icon files, and local signature have been checked; operation inside Tab Launcher has not been tested directly.
