"""
Tiny parser/evaluator for the closed grammar used in BoE/EBA assertion `test` strings.

Supports:
  function calls      iaf:numeric-add(a,b)  iaf:sum(x)  iaf:abs(x)  mfn:exp(x,lo,hi) ...
  variables           $v0
  numbers / strings   123   12.5   "^[0-9]{6,8}$"
  infix operators     + - * ,  >= <= > < = != ,  and or
  conditionals        if (cond) then (a) else (b)

Returns an AST of tuples. The evaluator takes a dict {varname: number-or-list} and a
helper for sequences. It is used both to EVALUATE a test and to SOLVE simple equalities
(set the single-variable side equal to the other side).
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>-?\d+\.?\d*)
    | (?P<str>"[^"]*"|'[^']*')
    | (?P<var>\$[A-Za-z_]\w*)
    | (?P<name>[A-Za-z_][\w\-]*(?::[A-Za-z_][\w\-]*)?)
    | (?P<op>>=|<=|!=|[=<>+\-*(),])
    )
""", re.VERBOSE)

KEYWORDS = {"if", "then", "else", "and", "or", "true", "false"}


def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m or m.end() == i:
            if s[i].isspace():
                i += 1
                continue
            raise ValueError(f"bad token at {i}: {s[i:i+20]!r}")
        i = m.end()
        kind = m.lastgroup
        val = m.group(m.lastgroup)
        toks.append((kind, val))
    toks.append(("eof", None))
    return toks


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, val):
        k, v = self.next()
        if v != val:
            raise ValueError(f"expected {val!r} got {v!r}")

    def parse(self):
        node = self.expr()
        return node

    # expr -> or_expr
    def expr(self):
        return self.bool_or()

    def bool_or(self):
        left = self.bool_and()
        while self.peek() == ("name", "or"):
            self.next()
            right = self.bool_and()
            left = ("or", left, right)
        return left

    def bool_and(self):
        left = self.comparison()
        while self.peek() == ("name", "and"):
            self.next()
            right = self.comparison()
            left = ("and", left, right)
        return left

    def comparison(self):
        left = self.add()
        k, v = self.peek()
        if k == "op" and v in (">=", "<=", ">", "<", "=", "!="):
            self.next()
            right = self.add()
            return ("cmp", v, left, right)
        return left

    def add(self):
        left = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            right = self.mul()
            left = ("bin", op, left, right)
        return left

    def mul(self):
        left = self.atom()
        while self.peek()[0] == "op" and self.peek()[1] == "*":
            self.next()
            right = self.atom()
            left = ("bin", "*", left, right)
        return left

    def atom(self):
        k, v = self.peek()
        if k == "op" and v == "(":
            self.next()
            first = self.expr()
            if self.peek() == ("op", ","):     # XPath sequence (a, b, c)
                items = [first]
                while self.peek() == ("op", ","):
                    self.next()
                    items.append(self.expr())
                self.expect(")")
                return ("seq", items)
            self.expect(")")
            return first
        if k == "name" and v == "if":
            return self.cond()
        if k == "num":
            self.next()
            return ("num", float(v))
        if k == "str":
            self.next()
            return ("str", v[1:-1])
        if k == "var":
            self.next()
            return ("var", v[1:])
        if k == "name":
            self.next()
            if v in ("true", "false"):
                # XPath spells these as function calls true()/false() — consume the parens.
                if self.peek() == ("op", "("):
                    self.next()
                    self.expect(")")
                return ("bool", v == "true")
            # function call?
            if self.peek() == ("op", "("):
                self.next()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.expr())
                    while self.peek() == ("op", ","):
                        self.next()
                        args.append(self.expr())
                self.expect(")")
                return ("call", v, args)
            return ("nameref", v)
        raise ValueError(f"unexpected token {k}:{v}")

    def cond(self):
        self.expect("if")
        # condition may be wrapped in parens by atom()
        cond = self.atom() if self.peek() == ("op", "(") else self.expr()
        self.expect_name("then")
        then = self.atom() if self.peek() == ("op", "(") else self.expr()
        self.expect_name("else")
        els = self.atom() if self.peek() == ("op", "(") else self.expr()
        return ("if", cond, then, els)

    def expect_name(self, name):
        k, v = self.next()
        if not (k == "name" and v == name):
            raise ValueError(f"expected {name} got {v!r}")


def parse(test: str):
    return Parser(tokenize(test)).parse()


# ---- evaluation -------------------------------------------------------------
def _num(x):
    if isinstance(x, list):
        return sum(_num(v) for v in x)
    return float(x) if x is not None else 0.0


def _coerce(x):
    """Normalize a value for = / != comparison (bool, number, or string)."""
    if isinstance(x, bool):
        return x
    if isinstance(x, list):
        return tuple(_coerce(v) for v in x)
    if x is None:
        return None
    s = str(x).strip()
    if s in ("true", "false"):
        return s == "true"
    try:
        return float(s)
    except ValueError:
        return s


def _flat(x, acc):
    """Flatten a value (possibly a nested list/sequence) into acc as floats."""
    if isinstance(x, list):
        for v in x:
            _flat(v, acc)
    elif x is not None:
        acc.append(float(x))
    return acc


def _argvals(args, env):
    """Evaluate call args and flatten into a single list of floats (handles sequences)."""
    out = []
    for a in args:
        _flat(evaluate(a, env), out)
    return out


def evaluate(node, env):
    """env: varname -> float | list[float] | str. Returns float/bool/str."""
    t = node[0]
    if t == "num":
        return node[1]
    if t == "str":
        return node[1]
    if t == "bool":
        return node[1]
    if t == "var":
        return env.get(node[1])
    if t == "seq":
        out = []
        for it in node[1]:
            _flat(evaluate(it, env), out)
        return out
    if t == "bin":
        a, b = evaluate(node[2], env), evaluate(node[3], env)
        if node[1] == "+":
            return _num(a) + _num(b)
        if node[1] == "-":
            return _num(a) - _num(b)
        if node[1] == "*":
            return _num(a) * _num(b)
    if t == "cmp":
        a, b = evaluate(node[2], env), evaluate(node[3], env)
        op = node[1]
        if op in ("=", "!="):                # may compare booleans/strings
            ca, cb = _coerce(a), _coerce(b)
            return (ca == cb) if op == "=" else (ca != cb)
        a, b = _num(a), _num(b)
        return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]
    if t == "and":
        return bool(evaluate(node[1], env)) and bool(evaluate(node[2], env))
    if t == "or":
        return bool(evaluate(node[1], env)) or bool(evaluate(node[2], env))
    if t == "if":
        return evaluate(node[2], env) if evaluate(node[1], env) else evaluate(node[3], env)
    if t == "call":
        fn = node[1].split(":")[-1]
        args = node[2]
        if fn == "sum":
            return sum(_argvals(args, env))
        if fn in ("numeric-add",):
            return _num(evaluate(args[0], env)) + _num(evaluate(args[1], env))
        if fn == "numeric-subtract":
            return _num(evaluate(args[0], env)) - _num(evaluate(args[1], env))
        if fn == "numeric-multiply":
            return _num(evaluate(args[0], env)) * _num(evaluate(args[1], env))
        if fn == "numeric-divide":
            d = _num(evaluate(args[1], env))
            return _num(evaluate(args[0], env)) / d if d else 0.0
        if fn == "abs":
            return abs(_num(evaluate(args[0], env)))
        if fn in ("max", "imax"):
            vals = _argvals(args, env)
            return max(vals) if vals else 0.0
        if fn in ("min", "imin"):
            vals = _argvals(args, env)
            return min(vals) if vals else 0.0
        if fn == "exp":      # mfn:exp(value, lo, hi) tolerance interval -> use value
            return _num(evaluate(args[0], env))
        if fn == "count":
            v = evaluate(args[0], env)
            return float(len(v)) if isinstance(v, list) else (1.0 if v is not None else 0.0)
        if fn in ("numeric-equal",):
            return _num(evaluate(args[0], env)) == _num(evaluate(args[1], env))
        if fn == "numeric-less-equal-than":
            return _num(evaluate(args[0], env)) <= _num(evaluate(args[1], env))
        if fn == "numeric-greater-equal-than":
            return _num(evaluate(args[0], env)) >= _num(evaluate(args[1], env))
        if fn == "numeric-less-than":
            return _num(evaluate(args[0], env)) < _num(evaluate(args[1], env))
        if fn == "numeric-greater-than":
            return _num(evaluate(args[0], env)) > _num(evaluate(args[1], env))
        if fn == "matches":
            import re as _re
            return bool(_re.search(evaluate(args[1], env), str(evaluate(args[0], env) or "")))
        if fn in ("empty",):
            v = evaluate(args[0], env)
            return v is None or (isinstance(v, list) and not v)
        if fn in ("not",):
            return not bool(evaluate(args[0], env))
        if fn == "QName":          # QName(ns, local) -> Clark notation '{ns}local'
            ns = str(evaluate(args[0], env) or "")
            local = str(evaluate(args[1], env) or "")
            return f"{{{ns}}}{local}"
    raise ValueError(f"cannot evaluate node {node!r}")
