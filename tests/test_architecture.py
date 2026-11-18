"""NFR-04: keep the layers separate so a requirement change stays local."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "station_health"


def imported_roots(module: str) -> set[str]:
    tree = ast.parse((PACKAGE / f"{module}.py").read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    return roots


def test_domain_rule_uses_only_the_standard_library() -> None:
    third_party_or_local = {
        name
        for name in imported_roots("starvation")
        if name.split(".")[0] not in sys.stdlib_module_names
    }

    assert third_party_or_local == set()


@pytest.mark.parametrize("module", ["starvation", "repository", "dependencies"])
def test_lower_layers_do_not_depend_on_the_web_framework(module: str) -> None:
    framework = {"fastapi", "starlette"}

    assert not {name for name in imported_roots(module) if name.split(".")[0] in framework}


@pytest.mark.parametrize("module", ["starvation", "repository", "schemas", "auth", "dependencies"])
def test_only_the_route_layer_wires_the_others_together(module: str) -> None:
    assert "station_health.routes" not in imported_roots(module)
