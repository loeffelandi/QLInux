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
- The AppImage is built with `packaging/build_appimage.sh`.
