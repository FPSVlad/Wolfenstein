from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .ast import *
from .lexer import ExprLexer, FortranSyntaxError, Line


def _split_csv(text: str) -> List[str]:
    out, cur, depth, in_str = [], [], 0, False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            in_str = not in_str
            cur.append(ch)
        elif not in_str and ch == '(':
            depth += 1
            cur.append(ch)
        elif not in_str and ch == ')':
            depth -= 1
            cur.append(ch)
        elif not in_str and depth == 0 and ch == ',':
            out.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        out.append(''.join(cur).strip())
    return [x for x in out if x]


class Parser:
    def __init__(self, lines: List[Line]):
        self.lines = lines
        self.i = 0

    def parse(self) -> Program:
        name = None
        body: List[Stmt] = []
        subs: List[Subprogram] = []
        in_main = True
        while self.i < len(self.lines):
            line = self.lines[self.i]
            text = line.text.strip()
            up = text.upper()
            if up.startswith('PROGRAM '):
                name = text.split(None, 1)[1].strip().upper()
                self.i += 1
                continue
            if up.startswith('SUBROUTINE ') or up.startswith('FUNCTION ') or re.match(r'^(INTEGER|REAL|LOGICAL|CHARACTER)\s+FUNCTION\b', up):
                subs.append(self.parse_subprogram())
                self.i += 1
                continue
            if up == 'END':
                in_main = False
                self.i += 1
                continue
            if in_main:
                stmt = self.parse_stmt()
                if stmt:
                    stmt.label = line.label
                    body.append(stmt)
            self.i += 1
        return Program(name=name, body=body, subprograms=subs)

    def parse_subprogram(self) -> Subprogram:
        line = self.lines[self.i]
        text = line.text.strip()
        up = text.upper()
        return_type = None
        if re.match(r'^(INTEGER|REAL|LOGICAL|CHARACTER)\s+FUNCTION\b', up):
            return_type, rem = up.split(None, 1)
            up = rem
            text = rem
        if up.startswith('SUBROUTINE '):
            kind = 'SUBROUTINE'
            sig = text[len('SUBROUTINE '):]
        else:
            kind = 'FUNCTION'
            sig = text[len('FUNCTION '):]
        m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*(\((.*)\))?$', sig.strip(), re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad subprogram signature: {text}')
        name = m.group(1).upper()
        params = [p.strip().upper() for p in _split_csv(m.group(3) or '')]
        self.i += 1
        body: List[Stmt] = []
        while self.i < len(self.lines):
            l = self.lines[self.i]
            u = l.text.strip().upper()
            if u == 'END':
                break
            stmt = self.parse_stmt()
            if stmt:
                stmt.label = l.label
                body.append(stmt)
            self.i += 1
        return Subprogram(kind=kind, name=name, params=params, body=body, return_type=return_type)

    def parse_stmt(self) -> Optional[Stmt]:
        line = self.lines[self.i]
        text = line.text.strip()
        up = text.upper()
        if not text:
            return None
        if up.startswith(('INTEGER ', 'REAL ', 'LOGICAL ', 'CHARACTER')):
            return self.parse_decl(text)
        if up.startswith('IF ') and up.endswith('THEN'):
            return self.parse_if_then()
        if up.startswith('IF(') or up.startswith('IF ('):
            return self.parse_if_inline(text)
        if up.startswith('DO '):
            return self.parse_do(text)
        if up.startswith('GOTO '):
            return Goto(int(text.split()[1]))
        if up == 'CONTINUE':
            return Continue()
        if up.startswith('STOP'):
            msg = text[4:].strip() or None
            return Stop(msg)
        if up.startswith('READ'):
            return self.parse_read_write(text, True)
        if up.startswith('WRITE'):
            return self.parse_read_write(text, False)
        if up.startswith('FORMAT'):
            if line.label is None:
                raise FortranSyntaxError('FORMAT requires label')
            return Format(label_id=line.label, raw=text[len('FORMAT'):].strip())
        if up.startswith('OPEN'):
            return OpenStmt(self.parse_kv_args(text))
        if up.startswith('CLOSE'):
            return CloseStmt(self.parse_kv_args(text))
        if up.startswith('CALL '):
            rest = text[5:].strip()
            m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*(\((.*)\))?$', rest, re.IGNORECASE)
            if not m:
                raise FortranSyntaxError(f'Bad CALL: {text}')
            args = [self.parse_expr(a) for a in _split_csv(m.group(3) or '')]
            return CallStmt(name=m.group(1).upper(), args=args)
        if up == 'RETURN':
            return ReturnStmt()
        if up.startswith('COMMON'):
            m = re.match(r'COMMON\s*/([A-Za-z_][A-Za-z0-9_]*)/\s*(.*)$', text, re.IGNORECASE)
            if not m:
                raise FortranSyntaxError(f'Bad COMMON: {text}')
            return CommonBlock(block_name=m.group(1).upper(), names=[x.strip().upper() for x in _split_csv(m.group(2))])
        if up.startswith('DATA '):
            m = re.match(r'DATA\s+(.*)/(.*)/\s*$', text, re.IGNORECASE)
            if not m:
                raise FortranSyntaxError(f'Bad DATA: {text}')
            targets = [self.parse_expr(x) for x in _split_csv(m.group(1))]
            values = [self.parse_expr(x) for x in _split_csv(m.group(2))]
            return DataStmt(targets=targets, values=values)
        if '=' in text:
            left, right = text.split('=', 1)
            return Assignment(target=self.parse_expr(left.strip()), expr=self.parse_expr(right.strip()))
        return None

    def parse_if_then(self) -> IfThen:
        line = self.lines[self.i]
        text = line.text.strip()
        m = re.match(r'IF\s*\((.*)\)\s*THEN\s*$', text, re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad IF THEN: {text}')
        cond = self.parse_expr(m.group(1))
        self.i += 1
        then_body: List[Stmt] = []
        else_body: List[Stmt] = []
        active = then_body
        while self.i < len(self.lines):
            u = self.lines[self.i].text.strip().upper()
            if u == 'ELSE':
                active = else_body
                self.i += 1
                continue
            if u in ('END IF', 'ENDIF'):
                break
            st = self.parse_stmt()
            if st:
                st.label = self.lines[self.i].label
                active.append(st)
            self.i += 1
        return IfThen(cond=cond, then_body=then_body, else_body=else_body)

    def parse_if_inline(self, text: str) -> Stmt:
        m = re.match(r'IF\s*\((.*)\)\s*(.*)$', text, re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad IF: {text}')
        cond_src, rest = m.group(1), m.group(2).strip()
        cond = self.parse_expr(cond_src)
        # arithmetic if IF (e) l1, l2, l3
        if re.fullmatch(r'\d+\s*,\s*\d+\s*,\s*\d+', rest):
            nums = [int(x.strip()) for x in rest.split(',')]
            return ArithmeticIf(cond, nums[0], nums[1], nums[2])
        nested = Parser([Line(0, None, rest)]).parse_stmt()
        return IfThen(cond=cond, then_body=[nested] if nested else [], else_body=[])

    def parse_do(self, text: str) -> DoLoop:
        m = re.match(r'DO\s+(\d+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?),\s*(.+?)(?:,\s*(.+))?$', text, re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad DO: {text}')
        end_label = int(m.group(1))
        var = m.group(2).upper()
        start = self.parse_expr(m.group(3))
        end = self.parse_expr(m.group(4))
        step = self.parse_expr(m.group(5)) if m.group(5) else None
        self.i += 1
        body: List[Stmt] = []
        while self.i < len(self.lines):
            l = self.lines[self.i]
            st = self.parse_stmt()
            if st:
                st.label = l.label
                body.append(st)
            if l.label == end_label:
                break
            self.i += 1
        return DoLoop(end_label=end_label, var=var, start=start, end=end, step=step, body=body)

    def parse_decl(self, text: str) -> Declaration:
        m = re.match(r'(INTEGER|REAL|LOGICAL|CHARACTER)(\*(\d+))?\s+(.*)$', text, re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad declaration: {text}')
        vartype = m.group(1).upper()
        char_len = int(m.group(3)) if m.group(3) else None
        items = []
        for part in _split_csv(m.group(4)):
            mm = re.match(r'([A-Za-z_][A-Za-z0-9_]*)(\((.*)\))?$', part, re.IGNORECASE)
            if not mm:
                raise FortranSyntaxError(f'Bad declared item: {part}')
            shape = None
            if mm.group(3):
                shape = tuple(int(x.strip()) for x in _split_csv(mm.group(3)))
            items.append((mm.group(1).upper(), shape, char_len))
        return Declaration(vartype=vartype, items=items)

    def parse_read_write(self, text: str, is_read: bool) -> Stmt:
        kw = 'READ' if is_read else 'WRITE'
        m = re.match(rf'{kw}\s*\((.*)\)\s*(.*)$', text, re.IGNORECASE)
        if not m:
            raise FortranSyntaxError(f'Bad {kw}: {text}')
        control = _split_csv(m.group(1))
        unit = control[0] if control else '*'
        fmt = control[1] if len(control) > 1 else '*'
        items = [self.parse_expr(x) for x in _split_csv(m.group(2))] if m.group(2).strip() else []
        if is_read:
            return Read(unit=unit.strip().upper(), fmt=fmt.strip().upper(), items=items)
        return Write(unit=unit.strip().upper(), fmt=fmt.strip().upper(), items=items)

    def parse_kv_args(self, text: str) -> dict:
        m = re.match(r'\w+\s*\((.*)\)\s*$', text)
        args = {}
        for p in _split_csv(m.group(1) if m else ''):
            if '=' in p:
                k, v = p.split('=', 1)
                args[k.strip().upper()] = v.strip().strip("'")
        return args

    def parse_expr(self, text: str) -> Expr:
        l = ExprParser(text)
        return l.parse()


class ExprParser:
    def __init__(self, text: str):
        self.lex = ExprLexer(text)

    def parse(self) -> Expr:
        e = self.parse_or()
        if self.lex.peek().kind != 'EOF':
            raise FortranSyntaxError(f'Unexpected token: {self.lex.peek().value}')
        return e

    def parse_or(self):
        e = self.parse_and()
        while self.lex.match('OR'):
            e = BinOp(e, '.OR.', self.parse_and())
        return e

    def parse_and(self):
        e = self.parse_cmp()
        while self.lex.match('AND'):
            e = BinOp(e, '.AND.', self.parse_cmp())
        return e

    def parse_cmp(self):
        e = self.parse_add()
        while self.lex.peek().kind in ('EQ', 'NE', 'LT', 'LE', 'GT', 'GE'):
            op = self.lex.pop().kind
            e = BinOp(e, f'.{op}.', self.parse_add())
        return e

    def parse_add(self):
        e = self.parse_mul()
        while self.lex.peek().kind in ('+', '-'):
            op = self.lex.pop().kind
            e = BinOp(e, op, self.parse_mul())
        return e

    def parse_mul(self):
        e = self.parse_pow()
        while self.lex.peek().kind in ('*', '/'):
            op = self.lex.pop().kind
            e = BinOp(e, op, self.parse_pow())
        return e

    def parse_pow(self):
        e = self.parse_unary()
        while self.lex.match('**'):
            e = BinOp(e, '**', self.parse_unary())
        return e

    def parse_unary(self):
        if self.lex.match('-'):
            return UnaryOp('-', self.parse_unary())
        if self.lex.match('+'):
            return UnaryOp('+', self.parse_unary())
        if self.lex.match('NOT'):
            return UnaryOp('.NOT.', self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.lex.peek()
        if self.lex.match('('):
            e = self.parse_or()
            self.lex.expect(')')
            return e
        if t.kind == 'INT':
            self.lex.pop()
            return Number(int(t.value))
        if t.kind == 'REAL':
            self.lex.pop()
            return Number(float(t.value))
        if t.kind == 'STRING':
            self.lex.pop()
            return String(t.value)
        if t.kind == 'TRUE':
            self.lex.pop()
            return Logical(True)
        if t.kind == 'FALSE':
            self.lex.pop()
            return Logical(False)
        if t.kind == 'ID':
            name = self.lex.pop().value
            if self.lex.match('('):
                args = []
                if self.lex.peek().kind != ')':
                    while True:
                        args.append(self.parse_or())
                        if not self.lex.match(','):
                            break
                self.lex.expect(')')
                # Unknown yet: function or array, runtime resolves
                if args and all(isinstance(a, (Number, Var, BinOp, UnaryOp, ArrayRef, FuncCall, String, Logical)) for a in args):
                    return FuncCall(name=name, args=args)
                return FuncCall(name=name, args=args)
            return Var(name=name)
        raise FortranSyntaxError(f'Unexpected token in expression: {t.value}')
