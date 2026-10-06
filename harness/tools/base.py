"""Lessons 06-07: a tool = a Python function + a JSON Schema description the model can read.

Schemas are written by hand for now. Lesson 08 generates them from type hints.
"""
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    description: str        # a prompt: tells the model WHEN and HOW to use the tool
    parameters: dict        # JSON Schema for the arguments
    fn: Callable[..., str]  # the real function; must return text for the model to read

    def schema(self) -> dict:
        """The provider-neutral description sent to the model."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}
