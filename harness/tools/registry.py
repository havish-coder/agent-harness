"""Lesson 09: the tool registry. Finds tools, checks arguments, runs them, caps their output.

Everything a model sends is untrusted input: the tool name may not exist, arguments may be
missing, misspelled or the wrong type. The registry turns each of those into a clear error
the model can fix on its next step, before the tool's code ever runs.
"""
import json
import re

from harness.messages import ToolCall
from harness.tools.base import Tool

_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
               "array": list, "object": dict}
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


class ToolRegistry:
    def __init__(self, tools: list[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.add(t)

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name '{tool.name}'")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self):
        return len(self._tools)

    def clearable_names(self) -> set[str]:
        """The tools whose old results may be replaced by a note (Lesson 38)."""
        return {t.name for t in self._tools.values() if t.clearable}

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def resolve(self, call: ToolCall) -> tuple[Tool | None, str | None]:
        """Find the tool and validate (and gently coerce) the call's arguments in place.

        Returns (tool, None) when the call can run, or (None, error text for the model).
        """
        tool = self._tools.get(call.name)
        if tool is None:
            return None, f"Error: unknown tool '{call.name}'. Available tools: {', '.join(self._tools)}"
        errors = validate_arguments(call.arguments, tool.parameters)
        if errors:
            return None, (f"Error: invalid arguments for {tool.name}: {'; '.join(errors)}.\n"
                          f"Expected: {signature(tool)}")
        return tool, None

    def invoke(self, tool: Tool, args: dict) -> str:
        """Run a resolved tool. Exceptions become error text; long results are cut."""
        try:
            result = str(tool.fn(**args))
        except Exception as e:
            result = f"Error: {type(e).__name__}: {e}"
        return truncate(result, tool.max_result_chars)


def validate_arguments(args: dict, schema: dict) -> list[str]:
    """Check args against a tool's (simple) JSON Schema. Coerces "5" → 5 and "true" → True."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    errors = [f"missing required argument '{n}'" for n in required if n not in args]
    for name in list(args):
        if name not in props:
            errors.append(f"unknown argument '{name}'")
            continue
        if args[name] is None:
            if name in required:
                errors.append(f"'{name}' must not be null")
            else:
                del args[name]   # null for an optional argument means "use the default"
            continue
        value, error = check_value(args[name], props[name], name)
        if error:
            errors.append(error)
        else:
            args[name] = value
    return errors


def check_value(value, schema: dict, where: str):
    """Return (possibly coerced value, None) or (value, error message)."""
    kind = schema.get("type")
    value = _coerce(value, kind)
    expected = _JSON_TYPES.get(kind)
    # bool is a subclass of int in Python, but true is not a number in JSON
    wrong_bool = isinstance(value, bool) and kind in ("integer", "number")
    if expected and (not isinstance(value, expected) or wrong_bool):
        return value, f"'{where}' must be {_article(kind)} {kind}, got {type(value).__name__} {value!r:.40}"
    if "enum" in schema and value not in schema["enum"]:
        return value, f"'{where}' must be one of {schema['enum']}, got {value!r}"
    if kind == "array" and "items" in schema:
        for i, item in enumerate(value):
            item_value, error = check_value(item, schema["items"], f"{where}[{i}]")
            if error:
                return value, error
            value[i] = item_value
    return value, None


def _coerce(value, kind):
    """Models sometimes quote scalars ("30", "true"). Fix only exact, unambiguous cases."""
    if isinstance(value, str):
        if kind in ("integer", "number") and _DECIMAL.match(value):
            number = float(value)
            return int(number) if kind == "integer" and number.is_integer() else number
        if kind == "boolean" and value.lower() in ("true", "false"):
            return value.lower() == "true"
    return value


def _article(kind: str) -> str:
    return "an" if kind[0] in "aeio" else "a"


def signature(tool: Tool) -> str:
    """A compact, Python-like signature to show the model what a correct call looks like."""
    props = tool.parameters.get("properties", {})
    required = set(tool.parameters.get("required", []))
    parts = []
    for name, p in props.items():
        kind = "|".join(map(json.dumps, p["enum"])) if "enum" in p else p.get("type", "any")
        if name in required:
            parts.append(f"{name}: {kind}")
        else:
            parts.append(f"{name}: {kind} = {json.dumps(p.get('default'))}")   # JSON, as the model writes it
    return f"{tool.name}({', '.join(parts)})"


def truncate(text: str, limit: int) -> str:
    """Keep the start and the end of an over-long result, and say what was cut."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.8)
    tail = limit - head
    cut = len(text) - head - tail
    return (f"{text[:head]}\n\n... [{cut:,} characters cut: the result had {len(text):,} characters, "
            f"the limit is {limit:,}. Narrow the request to see the middle.] ...\n\n{text[-tail:]}")
