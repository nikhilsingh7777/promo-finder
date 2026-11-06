"""Smoke test: every dependency imports and the package loads."""

import importlib

import pytest

MODULES = [
    "litellm", "pydantic", "yaml", "dotenv", "tenacity",
    "diskcache", "pandas", "streamlit", "typer", "rich", "promo_finder",
]


@pytest.mark.parametrize("name", MODULES)
def test_imports(name):
    importlib.import_module(name)


def test_config_loads():
    import yaml

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    assert cfg["promo_rules"]["min_duration_s"] == 20
    assert cfg["promo_rules"]["max_duration_s"] == 60
