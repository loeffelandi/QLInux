# Agent notes for QLInux

## Language
- Commit messages, PR titles and PR descriptions are written in English.
- Code comments, docstrings, UI strings and the German docs keep the existing
  German convention, unless the user asks otherwise.

## Workflow
- Work on a feature branch. Never commit directly to `main`.
- Do not commit, push or open a PR unless the user asks for it.
- Run `.venv/bin/python -m pytest -q` before committing and report any failure.
- After changing the app icons, regenerate them with
  `.venv/bin/python packaging/make_icon.py`.

## Code
- Match the style and structure of the surrounding code.
- Keep comments sparse and only where the behaviour is not obvious.
- Put tests next to related tests in `tests/test_*.py`.
- Every keyboard modifier (Ctrl, Shift, Alt, Cmd) a user can use for a
  mouse or key action must be listed in the "Modifier keys on the canvas"
  table in `README.md`. Add it there in the same change.
- The AppImage is built with `packaging/build_appimage.sh`.

## Cursor Cloud specific instructions

- Use Python 3.12. On Linux, PySide6 6.12 aborts the suite under Python 3.10
  (`SIGABRT` while deallocating `None`). Ubuntu 24.04's `python3` is 3.12.
- Qt's offscreen and xcb plugins need system libraries that are not in the
  base image: `python3-venv`, `libegl1`, `libgl1`, `libxkbcommon0`,
  `libdbus-1-3`, `libfontconfig1`, `libglib2.0-0t64`, `libxcb-cursor0`,
  `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-xkb1`, and `libxkbcommon-x11-0`.
- `bash scripts/bootstrap_venv.sh` creates `.venv`, installs
  `requirements-dev.txt`, and patches `brother_ql`. Running it again is safe.
- `.venv/bin/python -X faulthandler -m pytest -q` is the test command.
  `tests/conftest.py` forces the offscreen Qt platform, so do not point pytest
  at a real display.
- Start the editor with `.venv/bin/python -m ql_editor` on the desktop
  (`QT_QPA_PLATFORM=xcb`). There is no dev server to boot.
