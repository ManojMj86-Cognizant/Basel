"""Evaluate/solve the NON-additive BoE validation rules — `if COND then TARGET = EXPR else true()`
shapes that `workbook_rules.parse_expression` deliberately rejects (exp/imax/imin/ratios/conditions).

These are *derivation* rules: a single output cell equals a function of other cells. We parse the
expression, and for each scope position compute `EXPR` from the current (kept) input values and set
the lone TARGET cell — exactly "keep RHS inputs, revise the LHS". Covers e.g.:
  * b0360–b0364  TARGET = exp(Σ (cell·k)², 1, 2)           (√ of weighted sum of squares; exp(x,p,q)=x^(p/q))
  * b0676–b0679  if den≠0 then TARGET = factor · imax(num/den, 1)
Returns {dp_key -> value} overrides; cells are resolved through the same rc-code bridge as the
additive solver, so the keys match the built facts.
"""
from __future__ import annotations

import math
import re

from workbook_rules import CellResolver, _parse_cell, _semi, parse_scope  # noqa: E402

_CELL = re.compile(r"\{[^}]*\}")
# longest-match operator table (i-prefixed instance ops AND bare ops both occur in one expression)
_OPS = ["i<=", "i>=", "i!=", "i+", "i-", "i*", "i/", "i=", "i<", "i>",
        "<=", ">=", "!=", "=", "<", ">", "+", "-", "*", "/", "(", ")", ","]
_OPSET = set(_OPS)
_NORM = {"i+": "+", "i-": "-", "i*": "*", "i/": "/", "i=": "=", "i<=": "<=",
         "i>=": ">=", "i<": "<", "i>": ">", "i!=": "!="}


def _tokenize(expr: str) -> list:
    cells = _CELL.findall(expr)
    expr = _CELL.sub("\x00", expr)            # placeholder per cell, in order
    toks, i, ci, n = [], 0, 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1; continue
        if ch == "\x00":
            toks.append(("cell", _parse_cell(cells[ci][1:-1]))); ci += 1; i += 1; continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            toks.append(("num", float(expr[i:j]))); i = j; continue
        # i-prefixed instance operators (i= i+ i* i/ i<= …) must be matched BEFORE the alpha branch,
        # else the leading 'i' is mis-read as an identifier and the operator is lost.
        if ch == "i" and i + 1 < n and expr[i + 1] in "+-*/=<>!":
            for op in _OPS:
                if expr.startswith(op, i):
                    toks.append(("op", _NORM.get(op, op))); i += len(op); break
            continue
        if ch.isalpha():                       # identifier / keyword
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            toks.append(("id", expr[i:j])); i = j; continue
        for op in _OPS:                        # longest operator match
            if expr.startswith(op, i):
                toks.append(("op", _NORM.get(op, op))); i += len(op); break
        else:
            i += 1                             # skip unknown char
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self, val=None):
        tok = self.t[self.i]; self.i += 1
        return tok

    def parse(self):
        return self._cond()

    def _cond(self):                           # if / If ... then ... [else ...]
        k, v = self.peek()
        if k == "id" and v in ("if", "If"):
            self.eat()
            cond = self._cmp()
            # optional 'then'
            if self.peek() == ("id", "then"):
                self.eat()
            then = self._cmp()
            els = None
            if self.peek() == ("id", "else"):
                self.eat(); els = self._cmp()
            return ("if", cond, then, els)
        return self._cmp()

    def _cmp(self):
        a = self._add()
        k, v = self.peek()
        if k == "op" and v in ("=", "<=", ">=", "<", ">", "!="):
            self.eat(); b = self._add()
            return ("cmp", v, a, b)
        return a

    def _add(self):
        a = self._mul()
        while True:
            k, v = self.peek()
            if k == "op" and v in ("+", "-"):
                self.eat(); a = ("bin", v, a, self._mul())
            else:
                return a

    def _mul(self):
        a = self._un()
        while True:
            k, v = self.peek()
            if k == "op" and v in ("*", "/"):
                self.eat(); a = ("bin", v, a, self._un())
            else:
                return a

    def _un(self):
        k, v = self.peek()
        if k == "op" and v == "-":
            self.eat(); return ("neg", self._un())
        return self._atom()

    def _atom(self):
        k, v = self.peek()
        if k == "op" and v == "(":
            self.eat(); e = self._cond()
            if self.peek() == ("op", ")"):
                self.eat()
            return e
        if k == "cell":
            self.eat(); return ("cell", v)
        if k == "num":
            self.eat(); return ("num", v)
        if k == "id":
            self.eat()
            if self.peek() == ("op", "("):       # function call
                self.eat(); args = []
                if self.peek() != ("op", ")"):
                    args.append(self._cond())
                    while self.peek() == ("op", ","):
                        self.eat(); args.append(self._cond())
                if self.peek() == ("op", ")"):
                    self.eat()
                return ("call", v, args)
            return ("id", v)                      # bare ident (e.g. true with no parens)
        self.eat(); return ("num", 0.0)           # fallback


def _eval(node, getval):
    typ = node[0]
    if typ == "num":
        return node[1]
    if typ == "cell":
        return getval(node[1])
    if typ == "neg":
        return -_eval(node[1], getval)
    if typ == "bin":
        a = _eval(node[2], getval); b = _eval(node[3], getval)
        return a + b if node[1] == "+" else a - b if node[1] == "-" else \
            a * b if node[1] == "*" else (a / b if b else 0.0)
    if typ == "cmp":
        a = _eval(node[2], getval); b = _eval(node[3], getval)
        op = node[1]
        return {"=": a == b, "<=": a <= b, ">=": a >= b, "<": a < b,
                ">": a > b, "!=": a != b}[op]
    if typ == "call":
        name, args = node[1], node[2]
        vals = [_eval(a, getval) for a in args]
        if name == "exp":                         # exp(x, p, q) = x ^ (p/q)
            x = vals[0]; p = vals[1] if len(vals) > 1 else 1.0; q = vals[2] if len(vals) > 2 else 1.0
            return math.pow(x, p / q) if x >= 0 or (q and float(p / q).is_integer()) else 0.0
        if name in ("imax", "max"):
            return max(vals)
        if name in ("imin", "min"):
            return min(vals)
        if name == "isum":
            return sum(vals)
        if name == "true":
            return True
        return 0.0
    if typ == "id":
        return True if node[1] == "true" else 0.0
    if typ == "if":
        return None                               # handled by derive()
    return 0.0


def _target_and_rhs(node):
    """From `[if cond then] (TARGET = RHS) [else ...]` return (cond_node|None, target_cell, rhs_node)
    where TARGET is the lone-cell side of the equality. None if the shape isn't a derivation."""
    cond = None
    if node[0] == "if":
        cond, node = node[1], node[2]
    if node[0] != "cmp" or node[1] != "=":
        return None
    a, b = node[2], node[3]
    if a[0] == "cell":
        return cond, a[1], b
    if b[0] == "cell":
        return cond, b[1], a
    return None


def derive_rule(rule: dict, resolver: "CellResolver", value_of) -> dict:
    """Compute target-cell overrides for one non-additive derivation rule. `value_of(dp)->float`
    returns the current value of a resolved datapoint (0 if absent). Returns {dp_key -> value}."""
    expr = rule.get("expression", "")
    if "{" not in expr:
        return {}
    try:
        ast = _Parser(_tokenize(expr)).parse()
    except Exception:
        return {}
    tr = _target_and_rhs(ast)
    if not tr:
        return {}
    cond_node, target_cell, rhs_node = tr
    sc = parse_scope(rule.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
    out: dict = {}
    for srow in (sc["rows"] or [None]):
        for scol in (sc["cols"] or [None]):
            for sz in (sc["z"] or [None]):
                def resolve_one(celldict):
                    cell = {"table": celldict.get("table") or sc["table"],
                            "r": celldict.get("r") or srow, "c": celldict.get("c") or scol,
                            "z": celldict.get("z") or ([sz] if sz else [])}
                    dps = resolver.resolve(cell)
                    return dps[0] if dps else None

                def getval(celldict):
                    dp = resolve_one(celldict)
                    return value_of(dp) if dp else 0.0

                try:
                    if cond_node is not None and not _eval(cond_node, getval):
                        continue                          # condition false -> rule trivially true
                    tdp = resolve_one(target_cell)
                    if tdp is None:
                        continue
                    val = _eval(rhs_node, getval)
                    if isinstance(val, bool):
                        continue
                    out[(tdp["concept"], tuple(sorted(tdp["dims"].items())))] = val
                except Exception:
                    continue
    return out
