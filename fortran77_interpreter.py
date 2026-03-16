#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file Fortran 77 interpreter (educational, robust subset).
No external imports except sys.
"""
import sys


# =========================
# Errors
# =========================
class FortranError(Exception):
    def __init__(self, message, line=None, col=None):
        where = ""
        if line is not None:
            where += f" (line {line}"
            if col is not None:
                where += f", col {col}"
            where += ")"
        super().__init__(message + where)
        self.message = message
        self.line = line
        self.col = col


# =========================
# Fortran type helpers
# =========================
class FortranTypes:
    INTEGER = "INTEGER"
    REAL = "REAL"
    DOUBLE = "DOUBLE PRECISION"
    COMPLEX = "COMPLEX"
    LOGICAL = "LOGICAL"
    CHARACTER = "CHARACTER"

    @staticmethod
    def default_value(ftype, char_len=1):
        if ftype == FortranTypes.INTEGER:
            return 0
        if ftype in (FortranTypes.REAL, FortranTypes.DOUBLE):
            return 0.0
        if ftype == FortranTypes.COMPLEX:
            return (0.0, 0.0)
        if ftype == FortranTypes.LOGICAL:
            return False
        if ftype == FortranTypes.CHARACTER:
            return " " * max(1, char_len)
        return 0

    @staticmethod
    def cast(value, ftype, char_len=1):
        if ftype == FortranTypes.INTEGER:
            return int(value)
        if ftype in (FortranTypes.REAL, FortranTypes.DOUBLE):
            return float(value)
        if ftype == FortranTypes.LOGICAL:
            return bool(value)
        if ftype == FortranTypes.CHARACTER:
            s = str(value)
            return (s[:char_len]).ljust(char_len)
        if ftype == FortranTypes.COMPLEX:
            if isinstance(value, tuple) and len(value) == 2:
                return (float(value[0]), float(value[1]))
            return (float(value), 0.0)
        return value


# =========================
# Containers
# =========================
class FortranArray:
    def __init__(self, ftype, dims, char_len=1):
        self.ftype = ftype
        self.dims = list(dims)
        self.char_len = char_len
        self._data = self._build(0)

    def _build(self, level):
        n = self.dims[level]
        if level == len(self.dims) - 1:
            return [FortranTypes.default_value(self.ftype, self.char_len) for _ in range(n)]
        return [self._build(level + 1) for _ in range(n)]

    def _check(self, indices):
        if len(indices) != len(self.dims):
            raise FortranError(f"Array rank mismatch: expected {len(self.dims)}, got {len(indices)}")
        for i, idx in enumerate(indices):
            if idx < 1 or idx > self.dims[i]:
                raise FortranError(f"Array index out of bounds at dim {i+1}: {idx} not in 1..{self.dims[i]}")

    def get(self, indices):
        self._check(indices)
        cur = self._data
        for idx in indices[:-1]:
            cur = cur[idx - 1]
        return cur[indices[-1] - 1]

    def set(self, indices, value):
        self._check(indices)
        cur = self._data
        for idx in indices[:-1]:
            cur = cur[idx - 1]
        cur[indices[-1] - 1] = FortranTypes.cast(value, self.ftype, self.char_len)


class SymbolTable:
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}  # name -> dict(type, value, initialized, char_len)

    def define(self, name, ftype, value=None, initialized=False, char_len=1):
        self.vars[name] = {
            "type": ftype,
            "value": value if value is not None else FortranTypes.default_value(ftype, char_len),
            "initialized": initialized,
            "char_len": char_len,
        }

    def has_local(self, name):
        return name in self.vars

    def resolve_table(self, name):
        if name in self.vars:
            return self
        if self.parent:
            return self.parent.resolve_table(name)
        return None

    def get(self, name):
        t = self.resolve_table(name)
        if not t:
            raise FortranError(f"Undefined variable: {name}")
        info = t.vars[name]
        if not info["initialized"]:
            raise FortranError(f"Uninitialized variable: {name}")
        return info["value"]

    def get_info(self, name):
        t = self.resolve_table(name)
        if not t:
            raise FortranError(f"Undefined variable: {name}")
        return t.vars[name]

    def set(self, name, value):
        t = self.resolve_table(name)
        if not t:
            raise FortranError(f"Undefined variable: {name}")
        info = t.vars[name]
        info["value"] = FortranTypes.cast(value, info["type"], info["char_len"])
        info["initialized"] = True


class FortranFunction:
    def __init__(self, name, params, body, return_type):
        self.name = name
        self.params = params
        self.body = body
        self.return_type = return_type


class FortranSubroutine:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body


# =========================
# Lexer
# =========================
class Token:
    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col


class Lexer:
    KEYWORDS = {
        "PROGRAM", "INTEGER", "REAL", "CHARACTER", "LOGICAL", "DIMENSION", "COMMON", "DATA",
        "EQUIVALENCE", "PARAMETER", "IMPLICIT", "FUNCTION", "SUBROUTINE", "ENTRY", "CALL", "RETURN",
        "IF", "THEN", "ELSE", "ENDIF", "END", "DO", "CONTINUE", "GOTO", "STOP", "READ", "WRITE",
        "OPEN", "CLOSE", "FORMAT", "INCLUDE", "BLOCK", "DOUBLE", "PRECISION", "COMPLEX"
    }
    LOGICAL_TOKENS = {
        ".EQ.": "EQ", ".NE.": "NE", ".LT.": "LT", ".LE.": "LE", ".GT.": "GT", ".GE.": "GE",
        ".AND.": "AND", ".OR.": "OR", ".NOT.": "NOT", ".TRUE.": "TRUE", ".FALSE.": "FALSE"
    }

    def __init__(self, source):
        self.source = source

    def preprocess_fixed_form(self):
        logical_lines = []
        pending = None
        pending_line = None
        for ln, raw in enumerate(self.source.splitlines(), 1):
            line = raw.rstrip("\n")
            if not line:
                continue
            ch1 = line[0]
            if ch1 in ("C", "c", "*", "!"):
                continue
            if len(line) < 6:
                line += " " * (6 - len(line))
            label_field = line[:5]
            cont = line[5:6]
            code = line[6:72] if len(line) > 6 else ""
            label = label_field.strip() if label_field.strip() else None
            if label is not None and not label.isdigit():
                raise FortranError("Invalid numeric label", ln, 1)

            code_stripped = code.strip()
            if cont.strip():
                if pending is None:
                    raise FortranError("Continuation line without previous statement", ln, 6)
                pending += " " + code_stripped
            else:
                if pending is not None and pending.strip():
                    logical_lines.append((pending_line, pending))
                pending = code_stripped
                pending_line = ln
                if label:
                    pending = f"__LABEL__{label} " + pending

        if pending is not None and pending.strip():
            logical_lines.append((pending_line, pending))
        return logical_lines

    def _scan_expr(self, text, line):
        i = 0
        out = []
        while i < len(text):
            c = text[i]
            if c in " \t\r":
                i += 1
                continue
            if c == "'":
                j = i + 1
                s = ""
                while j < len(text) and text[j] != "'":
                    s += text[j]
                    j += 1
                if j >= len(text):
                    raise FortranError("Unterminated string literal", line, i + 1)
                out.append(Token("STRING", s, line, i + 1))
                i = j + 1
                continue
            if text.startswith("**", i):
                out.append(Token("POW", "**", line, i + 1))
                i += 2
                continue
            if c in "+-*/,()=":
                out.append(Token(c, c, line, i + 1))
                i += 1
                continue
            if c == ".":
                j = i + 1
                while j < len(text) and text[j] != ".":
                    j += 1
                if j < len(text):
                    maybe = text[i:j + 1].upper()
                    if maybe in self.LOGICAL_TOKENS:
                        out.append(Token(self.LOGICAL_TOKENS[maybe], maybe, line, i + 1))
                        i = j + 1
                        continue
                raise FortranError("Unknown dot-operator", line, i + 1)
            if c.isdigit():
                j = i
                dot = False
                while j < len(text) and (text[j].isdigit() or text[j] == "."):
                    if text[j] == ".":
                        if dot:
                            break
                        dot = True
                    j += 1
                num = text[i:j]
                out.append(Token("REAL" if dot else "INT", num, line, i + 1))
                i = j
                continue
            if c.isalpha() or c == "_":
                j = i
                while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                w = text[i:j].upper()
                out.append(Token("KW" if w in self.KEYWORDS else "ID", w, line, i + 1))
                i = j
                continue
            raise FortranError(f"Unexpected character: {c}", line, i + 1)
        out.append(Token("EOF", "EOF", line, len(text) + 1))
        return out

    def tokenize(self):
        # Parser in this implementation operates on logical lines directly.
        # Keep a token list placeholder per line for diagnostics/extensibility.
        return [(line, text, [Token("LINE", text, line, 1), Token("EOF", "EOF", line, len(text)+1)]) for line, text in self.preprocess_fixed_form()]


# =========================
# Parser
# =========================
class Parser:
    # AST is plain dict nodes for compactness.
    def __init__(self, token_lines):
        self.lines = token_lines
        self.i = 0

    def parse(self):
        program = {"type": "Program", "name": None, "body": [], "functions": {}, "subroutines": {}}
        in_main = True
        while self.i < len(self.lines):
            line, text, _ = self.lines[self.i]
            up = text.upper()
            if up.startswith("PROGRAM "):
                program["name"] = up.split(None, 1)[1].strip()
                self.i += 1
                continue
            if up.startswith("FUNCTION ") or up.startswith("REAL FUNCTION ") or up.startswith("INTEGER FUNCTION ") or up.startswith("DOUBLE PRECISION FUNCTION "):
                fn = self._parse_function()
                program["functions"][fn.name] = fn
                continue
            if up.startswith("SUBROUTINE "):
                sub = self._parse_subroutine()
                program["subroutines"][sub.name] = sub
                continue
            if up == "END":
                in_main = False
                self.i += 1
                continue
            if in_main:
                program["body"].append(self._parse_stmt(text, line))
            self.i += 1
        return program

    def _parse_function(self):
        line, text, _ = self.lines[self.i]
        up = text.upper()
        rtype = FortranTypes.REAL
        sig = up
        if up.startswith("REAL FUNCTION "):
            rtype = FortranTypes.REAL
            sig = up[len("REAL "):]
        elif up.startswith("INTEGER FUNCTION "):
            rtype = FortranTypes.INTEGER
            sig = up[len("INTEGER "):]
        elif up.startswith("DOUBLE PRECISION FUNCTION "):
            rtype = FortranTypes.DOUBLE
            sig = up[len("DOUBLE PRECISION "):]
        name, params = self._parse_signature(sig, "FUNCTION")
        self.i += 1
        body = []
        while self.i < len(self.lines):
            l, t, _ = self.lines[self.i]
            if t.upper() == "END":
                break
            body.append(self._parse_stmt(t, l))
            self.i += 1
        return FortranFunction(name, params, body, rtype)

    def _parse_subroutine(self):
        line, text, _ = self.lines[self.i]
        name, params = self._parse_signature(text.upper(), "SUBROUTINE")
        self.i += 1
        body = []
        while self.i < len(self.lines):
            l, t, _ = self.lines[self.i]
            if t.upper() == "END":
                break
            body.append(self._parse_stmt(t, l))
            self.i += 1
        return FortranSubroutine(name, params, body)

    def _parse_signature(self, s, kind):
        rest = s[len(kind):].strip()
        if "(" in rest:
            name = rest[:rest.index("(")].strip().upper()
            args = rest[rest.index("(") + 1:rest.rindex(")")].strip()
            params = [a.strip().upper() for a in args.split(",") if a.strip()]
        else:
            name = rest.strip().upper()
            params = []
        return name, params

    def _split_csv(self, text):
        out, cur, depth, ins = [], "", 0, False
        i = 0
        while i < len(text):
            c = text[i]
            if c == "'":
                ins = not ins
                cur += c
            elif not ins and c == "(":
                depth += 1
                cur += c
            elif not ins and c == ")":
                depth -= 1
                cur += c
            elif not ins and depth == 0 and c == ",":
                out.append(cur.strip())
                cur = ""
            else:
                cur += c
            i += 1
        if cur.strip():
            out.append(cur.strip())
        return out

    def _parse_stmt(self, text, line):
        if text.startswith("__LABEL__"):
            p = text.split(None, 1)
            label = int(p[0].replace("__LABEL__", ""))
            text = p[1] if len(p) > 1 else "CONTINUE"
        else:
            label = None
        up = text.upper().strip()
        if not up:
            return {"type": "Empty", "line": line, "label": label}

        if up.startswith("INTEGER ") or up.startswith("REAL ") or up.startswith("LOGICAL ") or up.startswith("DOUBLE PRECISION ") or up.startswith("COMPLEX ") or up.startswith("CHARACTER"):
            return self._parse_decl(up, line, label)
        if up.startswith("DIMENSION "):
            return {"type": "ArrayDecl", "line": line, "label": label, "decl": up[len("DIMENSION "):].strip()}
        if up.startswith("COMMON"):
            return {"type": "CommonBlock", "line": line, "label": label, "raw": text}
        if up.startswith("DATA "):
            return {"type": "DataStatement", "line": line, "label": label, "raw": text}
        if up.startswith("IF") and up.endswith("THEN"):
            return self._parse_if_block(text, line, label)
        if up.startswith("IF"):
            return self._parse_if_single(text, line, label)
        if up.startswith("DO "):
            return self._parse_do(text, line, label)
        if up.startswith("GOTO "):
            return {"type": "Goto", "line": line, "label": label, "target": int(up.split()[1])}
        if up == "CONTINUE":
            return {"type": "Continue", "line": line, "label": label}
        if up.startswith("STOP"):
            return {"type": "Stop", "line": line, "label": label, "msg": text[4:].strip()}
        if up.startswith("READ"):
            return self._parse_io("Read", text, line, label)
        if up.startswith("WRITE"):
            return self._parse_io("Write", text, line, label)
        if up.startswith("OPEN"):
            return {"type": "Open", "line": line, "label": label, "raw": text}
        if up.startswith("CLOSE"):
            return {"type": "Close", "line": line, "label": label, "raw": text}
        if up.startswith("FORMAT"):
            return {"type": "Format", "line": line, "label": label, "raw": text[len("FORMAT"):].strip()}
        if up.startswith("CALL "):
            name, args = self._parse_call(text[5:])
            return {"type": "Call", "line": line, "label": label, "name": name, "args": args}
        if up == "RETURN":
            return {"type": "Return", "line": line, "label": label}
        if "=" in text:
            left, right = text.split("=", 1)
            return {"type": "Assignment", "line": line, "label": label, "left": left.strip(), "right": right.strip()}
        raise FortranError(f"Unknown statement: {text}", line, 1)

    def _parse_decl(self, up, line, label):
        ftype = FortranTypes.INTEGER
        rest = up
        char_len = 1
        if up.startswith("INTEGER "):
            ftype = FortranTypes.INTEGER
            rest = up[len("INTEGER "):]
        elif up.startswith("REAL "):
            ftype = FortranTypes.REAL
            rest = up[len("REAL "):]
        elif up.startswith("LOGICAL "):
            ftype = FortranTypes.LOGICAL
            rest = up[len("LOGICAL "):]
        elif up.startswith("DOUBLE PRECISION "):
            ftype = FortranTypes.DOUBLE
            rest = up[len("DOUBLE PRECISION "):]
        elif up.startswith("COMPLEX "):
            ftype = FortranTypes.COMPLEX
            rest = up[len("COMPLEX "):]
        elif up.startswith("CHARACTER"):
            ftype = FortranTypes.CHARACTER
            rest = up[len("CHARACTER"):].strip()
            if rest.startswith("*"):
                n = ""
                i = 1
                while i < len(rest) and rest[i].isdigit():
                    n += rest[i]
                    i += 1
                char_len = int(n) if n else 1
                rest = rest[i:].strip()
        return {"type": "Declaration", "line": line, "label": label, "ftype": ftype, "char_len": char_len, "vars": self._split_csv(rest)}

    def _parse_if_single(self, text, line, label):
        up = text.upper()
        if not up.startswith("IF"):
            raise FortranError("Malformed IF", line, 1)
        l = text.index("(")
        r = self._find_matching_paren(text, l)
        cond = text[l + 1:r].strip()
        tail = text[r + 1:].strip()
        if tail.count(",") == 2 and all(p.strip().isdigit() for p in tail.split(",")):
            a, b, c = [int(x.strip()) for x in tail.split(",")]
            return {"type": "ArithmeticIf", "line": line, "label": label, "expr": cond, "neg": a, "zero": b, "pos": c}
        stmt = self._parse_stmt(tail, line)
        return {"type": "IfStatement", "line": line, "label": label, "cond": cond, "then": [stmt], "else": []}

    def _parse_if_block(self, text, line, label):
        l = text.index("(")
        r = self._find_matching_paren(text, l)
        cond = text[l + 1:r].strip()
        self.i += 1
        then_body, else_body = [], []
        active = then_body
        while self.i < len(self.lines):
            ln, t, _ = self.lines[self.i]
            up = t.upper().strip()
            if up == "ELSE":
                active = else_body
                self.i += 1
                continue
            # Fortran extension style: ELSE IF (...) THEN
            if up.startswith("ELSE IF") and up.endswith("THEN"):
                nested = self._parse_if_block(t[5:].strip(), ln, None)
                else_body.append(nested)
                break
            if up in ("ENDIF", "END IF"):
                break
            active.append(self._parse_stmt(t, ln))
            self.i += 1
        return {"type": "IfStatement", "line": line, "label": label, "cond": cond, "then": then_body, "else": else_body}

    def _parse_do(self, text, line, label):
        # DO 10 I = 1, N, 1
        up = text.upper().split(None, 2)
        end_label = int(up[1])
        rhs = up[2]
        var = rhs.split("=", 1)[0].strip()
        exprs = self._split_csv(rhs.split("=", 1)[1])
        start = exprs[0]
        stop = exprs[1]
        step = exprs[2] if len(exprs) > 2 else "1"
        return {"type": "DoLoop", "line": line, "label": label, "end_label": end_label, "var": var, "start": start, "stop": stop, "step": step}

    def _find_matching_paren(self, text, lpos):
        depth = 0
        in_str = False
        i = lpos
        while i < len(text):
            c = text[i]
            if c == "'":
                in_str = not in_str
            elif not in_str:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        return i
            i += 1
        raise FortranError("Unmatched parenthesis in statement")

    def _parse_io(self, kind, text, line, label):
        l = text.index("(")
        r = self._find_matching_paren(text, l)
        ctl = self._split_csv(text[l + 1:r])
        unit = ctl[0].strip() if ctl else "*"
        fmt = ctl[1].strip() if len(ctl) > 1 else "*"
        tail = text[r + 1:].strip()
        args = self._split_csv(tail) if tail else []
        return {"type": kind, "line": line, "label": label, "unit": unit, "fmt": fmt, "args": args}

    def _parse_call(self, tail):
        t = tail.strip()
        if "(" not in t:
            return t.upper(), []
        lp = t.index("(")
        rp = self._find_matching_paren(t, lp)
        name = t[:lp].strip().upper()
        args = t[lp + 1:rp]
        return name, self._split_csv(args)


# =========================
# Interpreter
# =========================
class _Ref:
    def __init__(self, getter, setter):
        self._g = getter
        self._s = setter

    def get(self):
        return self._g()

    def set(self, v):
        self._s(v)


class Interpreter:
    def __init__(self):
        self.global_table = SymbolTable()
        self.formats = {}
        self.common_blocks = {}
        self.functions = {}
        self.subroutines = {}
        self.open_units = {}

    # ---- tiny math core (no imports) ----
    def _abs(self, x): return -x if x < 0 else x
    def _sqrt(self, x):
        if x < 0: raise FortranError("SQRT domain error")
        if x == 0: return 0.0
        g = x if x > 1 else 1.0
        for _ in range(40):
            g = 0.5 * (g + x / g)
        return g
    def _exp(self, x):
        s = 1.0
        t = 1.0
        for n in range(1, 60):
            t = t * x / n
            s += t
        return s
    def _log(self, x):
        if x <= 0: raise FortranError("LOG domain error")
        # Newton on exp(y)=x
        y = 0.0
        for _ in range(50):
            ey = self._exp(y)
            y -= (ey - x) / ey
        return y
    def _sin(self, x):
        pi2 = 6.283185307179586
        while x > pi2: x -= pi2
        while x < -pi2: x += pi2
        s = x
        t = x
        for n in range(1, 20):
            t = -t * x * x / ((2*n)*(2*n+1))
            s += t
        return s
    def _cos(self, x):
        pi2 = 6.283185307179586
        while x > pi2: x -= pi2
        while x < -pi2: x += pi2
        s = 1.0
        t = 1.0
        for n in range(1, 20):
            t = -t * x * x / ((2*n-1)*(2*n))
            s += t
        return s
    def _atan(self, x):
        if self._abs(x) <= 1:
            s = x
            t = x
            sign = -1.0
            for n in range(3, 80, 2):
                t = t * x * x
                s += sign * t / n
                sign *= -1
            return s
        return (1.5707963267948966 - self._atan(1/x)) if x > 0 else (-1.5707963267948966 - self._atan(1/x))

    def builtins(self):
        return {
            "SQRT": lambda a: self._sqrt(float(a)),
            "SIN": lambda a: self._sin(float(a)),
            "COS": lambda a: self._cos(float(a)),
            "TAN": lambda a: self._sin(float(a))/self._cos(float(a)),
            "ASIN": lambda a: self._atan(float(a)/self._sqrt(1-float(a)*float(a))),
            "ACOS": lambda a: 1.5707963267948966 - self._atan(float(a)/self._sqrt(1-float(a)*float(a))),
            "ATAN": lambda a: self._atan(float(a)),
            "EXP": lambda a: self._exp(float(a)),
            "LOG": lambda a: self._log(float(a)),
            "LOG10": lambda a: self._log(float(a))/self._log(10.0),
            "ABS": lambda a: self._abs(a),
            "MOD": lambda a,b: int(a) % int(b),
            "MAX": lambda *a: max(a),
            "MIN": lambda *a: min(a),
            "LEN": lambda s: len(str(s).rstrip()),
            "INDEX": lambda s, sub: (str(s).find(str(sub)) + 1 if str(sub) in str(s) else 0),
            "CHAR": lambda n: chr(int(n)),
            "ICHAR": lambda c: ord(str(c)[0]),
        }

    def run(self, ast):
        self.functions = ast["functions"]
        self.subroutines = ast["subroutines"]
        self._collect_formats(ast["body"])
        for fn in self.functions.values():
            self._collect_formats(fn.body)
        for sub in self.subroutines.values():
            self._collect_formats(sub.body)
        self.exec_block(ast["body"], self.global_table)

    def _collect_formats(self, body):
        for st in body:
            if st.get("type") == "Format" and st.get("label") is not None:
                self.formats[st["label"]] = st["raw"]
            if st.get("type") == "IfStatement":
                self._collect_formats(st.get("then", []))
                self._collect_formats(st.get("else", []))

    def exec_block(self, body, table):
        label_to_index = {}
        for idx, st in enumerate(body):
            if st.get("label") is not None:
                label_to_index[st["label"]] = idx
        ip = 0
        while ip < len(body):
            st = body[ip]
            t = st["type"]
            if t == "Empty":
                pass
            elif t == "Declaration":
                self._exec_decl(st, table)
            elif t == "ArrayDecl":
                self._exec_array_decl(st, table)
            elif t == "Assignment":
                self._assign(st["left"], self.eval_expr(st["right"], table), table)
            elif t == "IfStatement":
                c = self.eval_expr(st["cond"], table)
                self.exec_block(st["then"] if c else st["else"], table)
            elif t == "ArithmeticIf":
                v = self.eval_expr(st["expr"], table)
                dest = st["neg"] if v < 0 else st["zero"] if v == 0 else st["pos"]
                if dest not in label_to_index:
                    raise FortranError(f"Unknown label {dest}", st["line"], 1)
                ip = label_to_index[dest]
                continue
            elif t == "DoLoop":
                var = st["var"].upper()
                start = int(self.eval_expr(st["start"], table))
                stop = int(self.eval_expr(st["stop"], table))
                step = int(self.eval_expr(st["step"], table))
                if not table.resolve_table(var):
                    table.define(var, FortranTypes.INTEGER)
                end_idx = None
                for j in range(ip + 1, len(body)):
                    if body[j].get("label") == st["end_label"]:
                        end_idx = j
                        break
                if end_idx is None:
                    raise FortranError("DO end label not found", st["line"], 1)
                k = start
                cond = (lambda x: x <= stop) if step >= 0 else (lambda x: x >= stop)
                while cond(k):
                    table.set(var, k)
                    self.exec_block(body[ip + 1:end_idx + 1], table)
                    k += step
                ip = end_idx + 1
                continue
            elif t == "Goto":
                dest = st["target"]
                if dest not in label_to_index:
                    raise FortranError(f"Unknown label {dest}", st["line"], 1)
                ip = label_to_index[dest]
                continue
            elif t == "Continue":
                pass
            elif t == "Stop":
                msg = st.get("msg", "")
                if msg:
                    print(msg.strip("'"))
                return
            elif t == "Read":
                self._exec_read(st, table)
            elif t == "Write":
                self._exec_write(st, table)
            elif t == "Format":
                if st.get("label") is None:
                    raise FortranError("FORMAT must have label", st["line"], 1)
                self.formats[st["label"]] = st["raw"]
            elif t == "Open":
                self._exec_open(st)
            elif t == "Close":
                self._exec_close(st)
            elif t == "Call":
                self._exec_call(st, table)
            elif t == "Return":
                raise StopIteration()
            elif t == "CommonBlock":
                self._exec_common(st, table)
            elif t == "DataStatement":
                self._exec_data(st, table)
            else:
                raise FortranError(f"Unsupported node {t}", st.get("line"), 1)
            ip += 1

    def _exec_decl(self, st, table):
        for item in st["vars"]:
            name = item.strip().upper()
            dims = None
            if "(" in name:
                base = name[:name.index("(")]
                dims_s = name[name.index("(")+1:name.rindex(")")]
                dims = [int(x.strip()) for x in dims_s.split(",")]
                name = base
            if table.has_local(name):
                continue
            if dims:
                arr = FortranArray(st["ftype"], dims, st["char_len"])
                table.define(name, st["ftype"], arr, initialized=True, char_len=st["char_len"])
            else:
                table.define(name, st["ftype"], FortranTypes.default_value(st["ftype"], st["char_len"]), initialized=False, char_len=st["char_len"])

    def _exec_array_decl(self, st, table):
        for item in [x.strip() for x in st["decl"].split(",") if x.strip()]:
            if "(" not in item:
                continue
            name = item[:item.index("(")].strip().upper()
            dims = [int(x.strip()) for x in item[item.index("(")+1:item.rindex(")")].split(",")]
            if not table.has_local(name):
                table.define(name, FortranTypes.REAL, FortranArray(FortranTypes.REAL, dims), initialized=True)

    def _parse_var_or_arr(self, text):
        s = text.strip().upper()
        if "(" in s and s.endswith(")"):
            n = s[:s.index("(")].strip()
            idx = [x.strip() for x in s[s.index("(")+1:-1].split(",") if x.strip()]
            return n, idx
        return s, None

    def _lref(self, target, table):
        name, idx_exprs = self._parse_var_or_arr(target)
        if idx_exprs is None:
            return _Ref(lambda: table.get(name), lambda v: table.set(name, v))
        info = table.get_info(name)
        arr = info["value"]
        if not isinstance(arr, FortranArray):
            raise FortranError(f"{name} is not an array")
        def g():
            idx = [int(self.eval_expr(e, table)) for e in idx_exprs]
            return arr.get(idx)
        def s(v):
            idx = [int(self.eval_expr(e, table)) for e in idx_exprs]
            arr.set(idx, v)
            info["initialized"] = True
        return _Ref(g, s)

    def _assign(self, left, value, table):
        self._lref(left, table).set(value)

    def _exec_common(self, st, table):
        raw = st["raw"].strip()
        # COMMON /BLK/ A,B
        blk = "BLANK"
        rest = raw[len("COMMON"):].strip()
        if rest.startswith("/"):
            p = rest.find("/", 1)
            blk = rest[1:p].strip().upper() or "BLANK"
            rest = rest[p+1:].strip()
        names = [x.strip().upper() for x in rest.split(",") if x.strip()]
        if blk not in self.common_blocks:
            self.common_blocks[blk] = {}
        mem = self.common_blocks[blk]
        for n in names:
            if n in mem:
                table.vars[n] = mem[n]
            else:
                cell = {"type": FortranTypes.REAL, "value": 0.0, "initialized": True, "char_len": 1}
                mem[n] = cell
                table.vars[n] = cell

    def _exec_data(self, st, table):
        raw = st["raw"].strip()[len("DATA"):].strip()
        if "/" not in raw:
            raise FortranError("Malformed DATA", st["line"], 1)
        left = raw[:raw.index("/")]
        rem = raw[raw.index("/")+1:]
        right = rem[:rem.index("/")] if "/" in rem else rem
        vars_ = [x.strip() for x in left.split(",") if x.strip()]
        vals_ = [x.strip() for x in right.split(",") if x.strip()]
        if not vals_:
            raise FortranError("DATA has no values", st["line"], 1)
        for i, v in enumerate(vars_):
            self._assign(v, self.eval_expr(vals_[i % len(vals_)], table), table)

    def _exec_open(self, st):
        raw = st["raw"]
        args = raw[raw.index("(")+1:raw.rindex(")")]
        unit = None
        fname = None
        for part in [x.strip() for x in args.split(",") if x.strip()]:
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip().upper()
                v = v.strip().strip("'")
                if k == "UNIT": unit = int(v)
                if k == "FILE": fname = v
        if unit is None or fname is None:
            raise FortranError("OPEN requires UNIT and FILE", st["line"], 1)
        self.open_units[unit] = open(fname, "r+") if _exists(fname) else open(fname, "w+")

    def _exec_close(self, st):
        raw = st["raw"]
        args = raw[raw.index("(")+1:raw.rindex(")")]
        unit = None
        for part in [x.strip() for x in args.split(",") if x.strip()]:
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip().upper() == "UNIT":
                    unit = int(v.strip())
        if unit is None:
            raise FortranError("CLOSE requires UNIT", st["line"], 1)
        if unit in self.open_units:
            self.open_units[unit].close()
            del self.open_units[unit]

    def _exec_read(self, st, table):
        unit = st["unit"].strip().upper()
        if unit == "*" or unit == "5":
            line = sys.stdin.readline()
        else:
            u = int(unit)
            if u not in self.open_units:
                raise FortranError(f"Unit not open: {u}", st["line"], 1)
            line = self.open_units[u].readline()
        parts = line.strip().split()
        for i, arg in enumerate(st["args"]):
            val = parts[i] if i < len(parts) else ""
            ref = self._lref(arg, table)
            name, _ = self._parse_var_or_arr(arg)
            finfo = table.get_info(name)
            ftype = finfo["type"]
            if ftype == FortranTypes.INTEGER:
                ref.set(int(val or 0))
            elif ftype in (FortranTypes.REAL, FortranTypes.DOUBLE):
                ref.set(float(val or 0.0))
            elif ftype == FortranTypes.LOGICAL:
                ref.set((val.upper() in ("T", ".TRUE.", "TRUE", "1")))
            else:
                ref.set(val)

    def _exec_write(self, st, table):
        unit = st["unit"].strip().upper()
        vals = [self.eval_expr(a, table) for a in st["args"]]
        fmt = st["fmt"].strip().upper()
        if fmt == "*":
            out = " ".join(str(v) for v in vals)
        elif fmt.isdigit() and int(fmt) in self.formats:
            out = self._apply_format(self.formats[int(fmt)], vals, st["line"])
        else:
            out = " ".join(str(v) for v in vals)
        if unit == "*" or unit == "6":
            print(out)
        else:
            u = int(unit)
            if u not in self.open_units:
                raise FortranError(f"Unit not open: {u}", st["line"], 1)
            self.open_units[u].write(out + "\n")

    def _apply_format(self, raw, vals, line):
        s = raw.strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1]
        parts = _split_format_parts(s)
        out = ""
        i = 0
        for p in parts:
            pu = p.upper().strip()
            if pu == "/":
                out += "\n"
                continue
            if pu == ":":
                if i >= len(vals):
                    break
                continue
            if pu.endswith("X") and pu[:-1].isdigit():
                out += " " * int(pu[:-1])
                continue
            if p.startswith("'") and p.endswith("'"):
                out += p[1:-1]
                continue
            if pu.startswith("I"):
                w = int(pu[1:])
                if i >= len(vals): raise FortranError("FORMAT/argument mismatch", line, 1)
                out += str(int(vals[i])).rjust(w)
                i += 1
                continue
            if pu.startswith("F"):
                ww, dd = pu[1:].split(".")
                w, d = int(ww), int(dd)
                if i >= len(vals): raise FortranError("FORMAT/argument mismatch", line, 1)
                out += ("%" + str(w) + "." + str(d) + "f") % float(vals[i])
                i += 1
                continue
            if pu.startswith("E") or pu.startswith("G"):
                ww, dd = pu[1:].split(".")
                w, d = int(ww), int(dd)
                if i >= len(vals): raise FortranError("FORMAT/argument mismatch", line, 1)
                out += ("%" + str(w) + "." + str(d) + "E") % float(vals[i])
                i += 1
                continue
            if pu.startswith("A"):
                if i >= len(vals): raise FortranError("FORMAT/argument mismatch", line, 1)
                if len(pu) > 1 and pu[1:].isdigit():
                    out += str(vals[i]).rjust(int(pu[1:]))
                else:
                    out += str(vals[i])
                i += 1
                continue
            raise FortranError(f"Unsupported FORMAT descriptor: {p}", line, 1)
        return out

    def _exec_call(self, st, table):
        name = st["name"].upper()
        if name not in self.subroutines:
            raise FortranError(f"Unknown subroutine {name}", st["line"], 1)
        sub = self.subroutines[name]
        local = SymbolTable(parent=self.global_table)
        refs = []
        for p, a in zip(sub.params, st["args"]):
            r = self._lref(a, table)
            refs.append((p.upper(), r))
            # placeholder variable that proxies value
            local.define(p.upper(), FortranTypes.REAL, r.get(), initialized=True)
        try:
            self.exec_block(sub.body, local)
        except StopIteration:
            pass
        for pname, ref in refs:
            ref.set(local.get(pname))

    def _call_function(self, name, arg_values, table):
        if name in self.builtins():
            return self.builtins()[name](*arg_values)
        if name not in self.functions:
            raise FortranError(f"Unknown function {name}")
        fn = self.functions[name]
        local = SymbolTable(parent=self.global_table)
        for p, v in zip(fn.params, arg_values):
            local.define(p.upper(), FortranTypes.REAL, v, initialized=True)
        local.define(fn.name, fn.return_type, FortranTypes.default_value(fn.return_type), initialized=False)
        try:
            self.exec_block(fn.body, local)
        except StopIteration:
            pass
        return local.get(fn.name)

    def eval_expr(self, expr, table):
        tokens = Lexer("" )._scan_expr(expr, 0)
        self._etoks = tokens
        self._ep = 0
        def peek(): return self._etoks[self._ep]
        def pop():
            t = self._etoks[self._ep]
            self._ep += 1
            return t
        def parse_primary():
            t = peek()
            if t.kind == "(":
                pop(); v = parse_or()
                if peek().kind != ")": raise FortranError("Expected )")
                pop(); return v
            if t.kind == "INT": pop(); return int(t.value)
            if t.kind == "REAL": pop(); return float(t.value)
            if t.kind == "STRING": pop(); return t.value
            if t.kind == "TRUE": pop(); return True
            if t.kind == "FALSE": pop(); return False
            if t.kind in ("ID", "KW"):
                name = pop().value.upper()
                if peek().kind == "(":
                    pop()
                    args = []
                    if peek().kind != ")":
                        while True:
                            args.append(parse_or())
                            if peek().kind != ",":
                                break
                            pop()
                    if peek().kind != ")": raise FortranError("Expected ) in call/index")
                    pop()
                    # array first
                    if table.resolve_table(name):
                        info = table.get_info(name)
                        if isinstance(info["value"], FortranArray):
                            idx = [int(x) for x in args]
                            return info["value"].get(idx)
                    return self._call_function(name, args, table)
                return table.get(name)
            if t.kind == "+": pop(); return +parse_primary()
            if t.kind == "-": pop(); return -parse_primary()
            if t.kind == "NOT": pop(); return not bool(parse_primary())
            raise FortranError("Bad expression")
        def parse_pow():
            v = parse_primary()
            while peek().kind == "POW":
                pop(); v = v ** parse_primary()
            return v
        def parse_mul():
            v = parse_pow()
            while peek().kind in ("*", "/"):
                op = pop().kind
                r = parse_pow()
                v = v * r if op == "*" else v / r
            return v
        def parse_add():
            v = parse_mul()
            while peek().kind in ("+", "-"):
                op = pop().kind
                r = parse_mul()
                v = v + r if op == "+" else v - r
            return v
        def parse_cmp():
            v = parse_add()
            while peek().kind in ("EQ", "NE", "LT", "LE", "GT", "GE"):
                op = pop().kind
                r = parse_add()
                if op == "EQ": v = (v == r)
                elif op == "NE": v = (v != r)
                elif op == "LT": v = (v < r)
                elif op == "LE": v = (v <= r)
                elif op == "GT": v = (v > r)
                elif op == "GE": v = (v >= r)
            return v
        def parse_and():
            v = parse_cmp()
            while peek().kind == "AND":
                pop(); v = bool(v) and bool(parse_cmp())
            return v
        def parse_or():
            v = parse_and()
            while peek().kind == "OR":
                pop(); v = bool(v) or bool(parse_and())
            return v
        result = parse_or()
        return result


def _exists(path):
    try:
        f = open(path, "r")
        f.close()
        return True
    except Exception:
        return False


def _split_format_parts(s):
    out, cur, ins = [], "", False
    for c in s:
        if c == "'":
            ins = not ins
            cur += c
        elif c == "," and not ins:
            if cur.strip(): out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip(): out.append(cur.strip())
    return out


def run_source(src):
    lexer = Lexer(src)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    ast = parser.parse()
    intr = Interpreter()
    intr.run(ast)


def _demo_programs():
    p1 = """
      PROGRAM HELLO
      INTEGER I, N
      REAL X, Y
      CHARACTER*20 NAME
      WRITE(*,*) 'Enter your name:'
      READ(*,*) NAME
      WRITE(*,*) 'Hello, ', NAME
      N = 3
      DO 10 I = 1, N
         X = I * 2.5
         Y = SQRT(X)
         WRITE(*,100) I, X, Y
  10  CONTINUE
  100 FORMAT('I=', I3, ' X=', F6.2, ' Y=', F8.4)
      END
    """
    p2 = """
      PROGRAM P2
      INTEGER A
      A = 7
      CALL INC(A)
      WRITE(*,*) 'A=', A
      END
      SUBROUTINE INC(X)
      INTEGER X
      X = X + 5
      RETURN
      END
    """
    return [p1, p2]


def repl():
    print("Fortran77 REPL. Finish block with single '.'; EXIT to quit.")
    buf = []
    while True:
        try:
            line = input("F77> ")
        except EOFError:
            break
        if line.strip().upper() in ("EXIT", "QUIT"):
            break
        if line.strip() == ".":
            src = "\n".join(buf)
            buf = []
            try:
                run_source(src)
            except Exception as e:
                print("ERROR:", e)
            continue
        buf.append(line)


def main(argv):
    if len(argv) >= 3 and argv[1] == "--eval":
        run_source(argv[2])
        return
    if len(argv) == 2:
        with open(argv[1], "r", encoding="utf-8") as f:
            run_source(f.read())
        return
    if len(argv) == 1:
        print("--- Demo 1 ---")
        try:
            run_source(_demo_programs()[0])
        except Exception as e:
            print("Demo1 error:", e)
        print("--- Demo 2 ---")
        try:
            run_source(_demo_programs()[1])
        except Exception as e:
            print("Demo2 error:", e)
        repl()
        return
    print("Usage: python fortran77_interpreter.py [file.f] | --eval \"...\"")


if __name__ == "__main__":
    main(sys.argv)
