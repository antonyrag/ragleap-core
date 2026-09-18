"""
ragleap_tools.calculator

Safe arithmetic expression evaluation - deliberately NOT using eval()
or exec(). Parses the expression into a real Python AST, then walks it
recursively, rejecting anything that isn't an explicitly whitelisted
node type (numbers, basic binary/unary math operators, and a small
fixed set of math functions/constants). No name lookups beyond that
fixed set, no attribute access, no function calls beyond the
whitelist, no comprehensions, no imports - none of eval()'s real
attack surface exists here at all.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Dict

from ragleap_tools.base import Tool, ToolResult

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
}

_ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


class UnsafeExpressionError(ValueError):
    """Raised when the expression contains anything outside the
    explicit whitelist - not a math error, a rejected-input error."""


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise UnsafeExpressionError(f"Constant type not allowed: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise UnsafeExpressionError(f"Operator not allowed: {op_type.__name__}")
        return _ALLOWED_BINOPS[op_type](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARYOPS:
            raise UnsafeExpressionError(f"Unary operator not allowed: {op_type.__name__}")
        return _ALLOWED_UNARYOPS[op_type](_eval_node(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_CONSTANTS:
            return _ALLOWED_CONSTANTS[node.id]
        raise UnsafeExpressionError(f"Name not allowed: {node.id!r}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            raise UnsafeExpressionError("Only whitelisted functions may be called")
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCTIONS[node.func.id](*args)
    raise UnsafeExpressionError(f"Expression node type not allowed: {type(node).__name__}")


def safe_eval_expression(expression: str) -> float:
    """Parses and evaluates a math expression using only the
    whitelisted grammar above. Raises UnsafeExpressionError for
    anything outside that whitelist, SyntaxError for invalid syntax,
    ZeroDivisionError/ValueError/OverflowError for real math errors -
    the caller (calculate()) catches all of these and returns a
    ToolResult rather than letting them propagate."""
    if not expression or not expression.strip():
        raise ValueError("Expression is empty")
    if len(expression) > 200:
        raise UnsafeExpressionError("Expression too long (max 200 characters)")
    parsed = ast.parse(expression, mode="eval")
    return _eval_node(parsed)


def calculate(expression: str) -> ToolResult:
    try:
        result = safe_eval_expression(expression)
        return ToolResult(success=True, result=result)
    except (UnsafeExpressionError, SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


CALCULATOR_TOOL = Tool(
    name="calculator",
    description=(
        "Evaluate a mathematical expression. Supports +, -, *, /, //, %, ** "
        "and the functions abs, round, min, max, sqrt, sin, cos, tan, log, "
        "log10, log2, exp, floor, ceil, plus the constants pi and e. "
        "No variables, no string operations, no other Python syntax."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A math expression, e.g. '2 + 2 * sqrt(16)'",
            },
        },
        "required": ["expression"],
    },
    handler=calculate,
)
