"""Lesson 09: the registry rejects bad calls with errors the model can act on."""
from typing import Literal

import pytest

from harness.messages import ToolCall
from harness.tools.base import tool
from harness.tools.registry import ToolRegistry, signature, truncate, validate_arguments


@tool(read_only=True)
def grep(pattern: str, limit: int = 10, mode: Literal["files", "lines"] = "files",
         ignore_case: bool = False, globs: list[str] | None = None) -> str:
    """Search."""
    return f"{pattern}|{limit}|{mode}|{ignore_case}|{globs}"


@tool(read_only=True)
def boom() -> str:
    """Always fails."""
    raise RuntimeError("disk on fire")


@pytest.fixture
def registry():
    return ToolRegistry([grep, boom])


def resolve(registry, name, **args):
    return registry.resolve(ToolCall("1", name, args))


def test_unknown_tool_lists_the_real_ones(registry):
    tool, error = resolve(registry, "search_files", pattern="x")
    assert tool is None
    assert error == "Error: unknown tool 'search_files'. Available tools: grep, boom"


def test_missing_and_unknown_arguments_show_the_signature(registry):
    _, error = resolve(registry, "grep", query="x")
    assert "missing required argument 'pattern'" in error
    assert "unknown argument 'query'" in error
    assert ('Expected: grep(pattern: string, limit: integer = 10, mode: "files"|"lines" = "files", '
            'ignore_case: boolean = false, globs: array = null)') in error


def test_wrong_types_and_enum(registry):
    _, error = resolve(registry, "grep", pattern="x", limit="ten", mode="words")
    assert "'limit' must be an integer, got str 'ten'" in error
    assert "'mode' must be one of ['files', 'lines'], got 'words'" in error
    _, error = resolve(registry, "grep", pattern="x", limit=True)
    assert "'limit' must be an integer, got bool" in error     # True is not a number in JSON
    _, error = resolve(registry, "grep", pattern="x", globs=["*.py", 3])
    assert "'globs[1]' must be a string" in error


def test_quoted_scalars_are_coerced_exactly(registry):
    call = ToolCall("1", "grep", {"pattern": "x", "limit": "30", "ignore_case": "TRUE"})
    tool, error = registry.resolve(call)
    assert error is None
    assert call.arguments == {"pattern": "x", "limit": 30, "ignore_case": True}
    assert registry.invoke(tool, call.arguments) == "x|30|files|True|None"
    for bad in ["", "3.5", "1e3", " 3"]:
        assert validate_arguments({"pattern": "x", "limit": bad}, grep.parameters), bad


def test_null_means_default_for_optional_arguments(registry):
    call = ToolCall("1", "grep", {"pattern": "x", "globs": None})
    tool, error = registry.resolve(call)
    assert error is None and "globs" not in call.arguments
    _, error = resolve(registry, "grep", pattern=None)
    assert "'pattern' must not be null" in error


def test_exceptions_become_text(registry):
    tool, _ = resolve(registry, "boom")
    assert registry.invoke(tool, {}) == "Error: RuntimeError: disk on fire"


def test_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([grep, grep])


def test_truncate_keeps_head_and_tail():
    text = "".join(f"line {i}\n" for i in range(10_000))
    out = truncate(text, 1000)
    assert out.startswith("line 0\n") and out.endswith("line 9999\n")
    assert "characters cut" in out and f"{len(text):,}" in out
    assert truncate("short", 1000) == "short"


def test_signature():
    assert signature(boom) == "boom()"
