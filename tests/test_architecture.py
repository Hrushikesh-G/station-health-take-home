"""NFR-04: keep the layers separate so a requirement change stays local.

These tests read the source code (without running it) and check which modules
each file imports. If someone later adds, say, a FastAPI import to the rule in
starvation.py, these tests fail and point at the broken boundary.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Folder holding the application code: <project>/station_health
PACKAGE = Path(__file__).resolve().parent.parent / "station_health"


def imported_roots(module: str) -> set[str]:
    """Names of every module imported by station_health/<module>.py."""
    # Parse the file into a syntax tree, the same structure Python builds
    # before running code.
    tree = ast.parse((PACKAGE / f"{module}.py").read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        # "import hmac" -> "hmac"
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        # "from fastapi import Depends" -> "fastapi"
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    return roots


def test_domain_rule_uses_only_the_standard_library() -> None:
    # Everything starvation.py imports must ship with Python itself.
    # sys.stdlib_module_names lists the standard library's module names.
    third_party_or_local = {
        name
        for name in imported_roots("starvation")
        if name.split(".")[0] not in sys.stdlib_module_names
    }

    assert third_party_or_local == set()


@pytest.mark.parametrize("module", ["starvation", "repository", "dependencies"])
def test_lower_layers_do_not_depend_on_the_web_framework(module: str) -> None:
    # Only the HTTP-facing modules may import FastAPI (or Starlette, which
    # FastAPI is built on).
    framework = {"fastapi", "starlette"}

    assert not {name for name in imported_roots(module) if name.split(".")[0] in framework}


@pytest.mark.parametrize("module", ["starvation", "repository", "schemas", "auth", "dependencies"])
def test_only_the_route_layer_wires_the_others_together(module: str) -> None:
    # Lower layers must never import routes.py; dependencies point one way.
    assert "station_health.routes" not in imported_roots(module)
