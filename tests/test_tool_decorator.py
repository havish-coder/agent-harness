"""Lesson 08: schemas generated from type hints and docstrings; fail-closed safety flags."""
from typing import Literal

import pytest

from harness.tools.base import Tool, parameters_schema, tool


def test_schema_from_hints_and_docstring():
    @tool(read_only=True)
    def search(pattern: str, limit: int = 10, mode: Literal["files", "lines"] = "files",
               case: bool | None = None, tags: list[str] | None = None) -> str:
        """Search the workspace.

        Second paragraph of the description.

        Args:
            pattern: Regular expression to look for.
            limit: Maximum results,
                counted per file.
        """
        return ""

    assert isinstance(search, Tool)
    assert search.name == "search"
    assert search.description == "Search the workspace.\n\nSecond paragraph of the description."
    assert search.parameters == {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to look for."},
            "limit": {"type": "integer", "description": "Maximum results, counted per file.", "default": 10},
            "mode": {"type": "string", "enum": ["files", "lines"], "default": "files"},
            "case": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["pattern"],
    }


def test_flags_default_to_the_unsafe_value():
    @tool
    def anything(x: str) -> str:
        """Do something."""
        return x

    assert not anything.is_read_only({})
    assert not anything.is_concurrency_safe({})
    assert not anything.is_destructive({})   # unknown, but approval is already required by read_only=False


def test_flags_can_depend_on_arguments():
    @tool(read_only=lambda args: args["command"].startswith("ls"))
    def shell(command: str) -> str:
        """Run a command."""
        return ""

    assert shell.is_read_only({"command": "ls -la"})
    assert not shell.is_read_only({"command": "rm -rf x"})
    assert not shell.is_read_only({})        # the flag function crashed → fail closed


def test_missing_docstring_or_hint_fails_at_definition_time():
    with pytest.raises(TypeError, match="docstring"):
        @tool
        def nodoc(x: str) -> str:
            return x

    def nohint(x) -> str:
        """Doc."""
    with pytest.raises(TypeError, match="type hint"):
        parameters_schema(nohint)


def test_unions_and_kwargs_are_rejected():
    def union(x: int | str) -> str:
        """Doc."""
    def kwargs(**kw: str) -> str:
        """Doc."""
    with pytest.raises(TypeError, match="unions"):
        parameters_schema(union)
    with pytest.raises(TypeError, match="kwargs"):
        parameters_schema(kwargs)


def test_custom_name():
    @tool(name="read", read_only=True)
    def read_file_impl(path: str) -> str:
        """Read."""
        return path
    assert read_file_impl.name == "read"
    assert read_file_impl.fn("a") == "a"
