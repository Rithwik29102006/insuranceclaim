"""Automated test suite verifying the fact vocabulary registry against the rule engine.

Uses Python AST analysis to statically inspect every fact name accessed in
src/engine/rule_engine.py and confirms 100% coverage in src/fact_vocabulary.py.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from src.fact_vocabulary import FACT_VOCABULARY, FactDefinition, list_registered_fact_names

ENGINE_FILE = Path(__file__).resolve().parent.parent / "src" / "engine" / "rule_engine.py"


def _extract_engine_accessed_fact_names() -> set[str]:
    """Parse src/engine/rule_engine.py AST and extract all fact names queried by the engine."""
    with open(ENGINE_FILE, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(ENGINE_FILE))

    accessed_names = set()

    for node in ast.walk(tree):
        # Look for facts_by_name.get("literal")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "facts_by_name" and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        accessed_names.add(first_arg.value)

        # Look for facts_by_name["literal"]
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == "facts_by_name":
                slice_node = node.slice
                if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                    accessed_names.add(slice_node.value)

    return accessed_names


def test_every_engine_accessed_fact_is_registered_in_vocabulary():
    """Verify that every fact name accessed in rule_engine.py exists in FACT_VOCABULARY."""
    accessed_facts = _extract_engine_accessed_fact_names()
    assert len(accessed_facts) >= 6, f"Expected at least 6 accessed facts, found: {accessed_facts}"

    registered_facts = set(FACT_VOCABULARY.keys())
    missing = accessed_facts - registered_facts

    assert not missing, (
        f"The following fact names are accessed in src/engine/rule_engine.py "
        f"but are missing from src/fact_vocabulary.py: {missing}"
    )


def test_fact_definitions_have_valid_structure():
    """Verify that every definition in FACT_VOCABULARY has non-empty fields and examples."""
    assert len(FACT_VOCABULARY) >= 8

    for name, defn in FACT_VOCABULARY.items():
        assert isinstance(defn, FactDefinition)
        assert defn.name == name
        assert len(defn.data_type) > 0
        assert len(defn.meaning) > 10
        assert defn.example_value is not None


def test_list_registered_fact_names():
    """Verify helper function returns sorted names."""
    names = list_registered_fact_names()
    assert names == sorted(FACT_VOCABULARY.keys())
