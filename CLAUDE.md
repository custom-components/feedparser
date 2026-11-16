# CLAUDE.md

Guidance for working on `sensor.feedparser`, a Home Assistant custom integration (HACS) that turns RSS/Atom feeds into sensors. Python, config-flow based, with YAML import for legacy setups.

## Layout

- `custom_components/feedparser/` — the integration
  - `config_flow.py`, `yaml_import.py` — UI setup and legacy YAML import
  - `coordinator.py`, `fetch.py`, `reader.py`, `source.py` — fetching and parsing feeds
  - `sensor.py` — sensor entities
  - `const.py`, `compat.py`, `manifest.json`, `strings.json`, `translations/` (`en`, `de`, `el`)
- `tests/` — pytest suite; `tests/data/` holds saved feeds (`*.xml` with a matching `*.json` of expected output)
- `hacs.json`, `package.yaml`, `pyproject.toml` — packaging and tooling config
- `test_hass/` and `run-hass.sh` — local Home Assistant for manual testing

## Commands

```bash
scripts/setup                       # pip install -e .[dev]
pre-commit run --all-files          # black, ruff, mypy, xmllint, toml/yaml checks
pytest -sv tests/                   # offline tests (online ones are excluded by default)
pytest -sv -p no:homeassistant -m online tests/   # tests that need real network access
scripts/develop                     # run a local Home Assistant with the integration linked in
```

The Home Assistant pytest plugin blocks DNS, which is why the `online` tests must run with `-p no:homeassistant`.

## Conventions

- Line length 88 (black and ruff). Ruff has a broad rule set (`ANN`, `D`, `PL`, `TRY`, `SIM`, ...), so new code needs type annotations and docstrings.
- **Python versions:** `hacs.json` allows Home Assistant 2025.8, which runs on Python 3.13. Source code under `custom_components/` must stay valid on 3.13 (CI compiles it with 3.13). Tests need 3.14. Don't use 3.14-only syntax in the integration.
- Keep `mypy` clean. Typing stubs for Home Assistant and `voluptuous` are pinned in `pyproject.toml`; keep `homeassistant-stubs` on the same release as `pytest-homeassistant-custom-component`.
- Don't block Home Assistant's event loop. Check how `fetch.py` and `coordinator.py` run network calls before adding new ones.
- Handle malformed, empty and unreachable feeds without raising out of the coordinator, and keep sensors in a sensible unavailable state.

## Changing behavior

- **Config options:** keep the UI flow (`config_flow.py`), the YAML import (`yaml_import.py`), `strings.json`, and every file in `translations/` in sync, and update the README's configuration reference.
- **New feed edge cases:** add a saved feed under `tests/data/` (`.xml` plus the expected `.json`) and register it in `tests/constants.py` rather than mocking around the problem.
- **Releases:** the version lives in `pyproject.toml`, `manifest.json` and `const.py`; `bumpver` keeps them aligned. Don't edit them by hand.

## Pull requests

- Keep PRs focused on one change, and call out follow-up work instead of bundling it.
- CI must pass: "Code Quality (3.14)" (pre-commit and tests), "Python 3.13 syntax", hassfest and HACS validation.
