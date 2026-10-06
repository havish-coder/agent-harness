"""Lesson 08: a tool = a Python function + a JSON Schema the model reads + safety metadata.

The `@tool` decorator builds the schema from the function's type hints and docstring, so the
code and its description can't drift apart. Safety flags are *fail-closed*: a tool that
doesn't declare itself read-only is treated as one that changes things.
"""
import inspect
import re
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

# A flag can be fixed (True/False) or depend on the call's arguments: shell("ls") is
# read-only, shell("rm x") is not.
Flag = bool | Callable[[dict], bool]

DEFAULT_MAX_RESULT_CHARS = 8_000   # ~2-3K tokens: a quarter of an 8K context (Lesson 09)


@dataclass
class Tool:
    name: str
    description: str        # a prompt: tells the model WHEN and HOW to use the tool
    parameters: dict        # JSON Schema for the arguments
    fn: Callable[..., str]  # the real function; must return text for the model to read
    # Safety metadata. Defaults assume the worst (fail-closed): forgetting a flag can make a
    # tool slower or ask more often, never more dangerous.
    read_only: Flag = False         # True = never changes anything (files, processes, the world)
    concurrency_safe: Flag = False  # True = may run at the same time as other calls
    destructive: Flag = False       # True = may destroy data (overwrite, delete)
    max_result_chars: int = DEFAULT_MAX_RESULT_CHARS  # longer results are cut (Lesson 09)
    preview: Callable[..., str] | None = None  # shows what a call would do, for approvals (Lesson 12)

    def schema(self) -> dict:
        """The provider-neutral description sent to the model."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def is_read_only(self, args: dict) -> bool:
        return _resolve(self.read_only, args)

    def is_concurrency_safe(self, args: dict) -> bool:
        return _resolve(self.concurrency_safe, args)

    def is_destructive(self, args: dict) -> bool:
        return _resolve(self.destructive, args)


def _resolve(flag: Flag, args: dict) -> bool:
    if callable(flag):
        try:
            return bool(flag(args))
        except Exception:
            return False  # a broken flag function must not grant anything
    return bool(flag)


def tool(fn: Callable | None = None, *, name: str | None = None, read_only: Flag = False,
         concurrency_safe: Flag = False, destructive: Flag = False,
         max_result_chars: int = DEFAULT_MAX_RESULT_CHARS) -> Any:
    """Turn a function into a `Tool`. Use as `@tool` or `@tool(read_only=True, ...)`.

    - name: the function name (or `name=`)
    - description: the docstring text before `Args:`
    - parameters: built from type hints; arguments without a default are required;
      per-argument descriptions come from the docstring's `Args:` section
    """
    def build(f: Callable) -> Tool:
        description, arg_docs = parse_docstring(f)
        if not description:
            raise TypeError(f"tool '{f.__name__}' needs a docstring: it is the model's only manual")
        return Tool(
            name=name or f.__name__,
            description=description,
            parameters=parameters_schema(f, arg_docs),
            fn=f,
            read_only=read_only,
            concurrency_safe=concurrency_safe,
            destructive=destructive,
            max_result_chars=max_result_chars,
        )

    return build(fn) if fn is not None else build


def parse_docstring(f: Callable) -> tuple[str, dict[str, str]]:
    """Google-style docstring → (description, {arg: description})."""
    doc = inspect.getdoc(f) or ""
    head, _, args_part = doc.partition("\nArgs:\n")
    arg_docs: dict[str, str] = {}
    current = None
    for line in args_part.splitlines():
        m = re.match(r"^\s{2,}(\w+)(?:\s*\([^)]*\))?:\s*(.*)$", line)
        if m:
            current = m.group(1)
            arg_docs[current] = m.group(2).strip()
        elif current and line.strip():
            arg_docs[current] += " " + line.strip()   # continuation line
        elif not line.strip():
            current = None
    return head.strip(), arg_docs


def parameters_schema(f: Callable, arg_docs: dict[str, str] | None = None) -> dict:
    """Build a JSON Schema object for f's parameters from its type hints."""
    arg_docs = arg_docs or {}
    hints = get_type_hints(f)
    properties, required = {}, []
    for p in inspect.signature(f).parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise TypeError(f"{f.__name__}: *args/**kwargs can't be described to a model")
        if p.name not in hints:
            raise TypeError(f"{f.__name__}: argument '{p.name}' needs a type hint")
        prop = type_schema(hints[p.name], where=f"{f.__name__}({p.name})")
        if p.name in arg_docs:
            prop["description"] = arg_docs[p.name]
        if p.default is inspect.Parameter.empty:
            required.append(p.name)
        elif p.default is not None:
            prop["default"] = p.default
        properties[p.name] = prop
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_SIMPLE = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}


def type_schema(t: Any, where: str = "") -> dict:
    """One Python type → its JSON Schema. Unsupported types fail loudly at import time."""
    if t in _SIMPLE:
        return {"type": _SIMPLE[t]}
    origin, args = get_origin(t), get_args(t)
    if origin is Literal:
        kinds = {type(a) for a in args}
        if len(kinds) != 1 or next(iter(kinds)) not in _SIMPLE:
            raise TypeError(f"{where}: Literal values must all be one simple type")
        return {"type": _SIMPLE[next(iter(kinds))], "enum": list(args)}
    if origin in (Union, types.UnionType):
        real = [a for a in args if a is not type(None)]
        if len(real) == 1:          # Optional[X] / X | None: "not required" is expressed by a default
            return type_schema(real[0], where)
        raise TypeError(f"{where}: unions of several types confuse models; use one type")
    if origin is list:
        return {"type": "array", "items": type_schema(args[0], where) if args else {}}
    if origin is dict:
        return {"type": "object"}
    raise TypeError(f"{where}: unsupported type {t!r}")
