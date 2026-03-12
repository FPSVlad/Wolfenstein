from __future__ import annotations

import io
import math
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .ast import *
from .lexer import FortranSyntaxError, preprocess_fixed_form
from .parser import Parser


class FortranRuntimeError(Exception):
    pass


class StopExecution(Exception):
    pass


class ReturnSignal(Exception):
    def __init__(self, value=None):
        self.value = value


@dataclass
class Symbol:
    vartype: str
    value: Any
    shape: Optional[Tuple[int, ...]] = None
    char_len: Optional[int] = None


class Ref:
    def __init__(self, getter, setter):
        self._getter = getter
        self._setter = setter

    @property
    def value(self):
        return self._getter()

    @value.setter
    def value(self, v):
        self._setter(v)


class Environment:
    def __init__(self, parent: Optional['Environment'] = None):
        self.parent = parent
        self.symbols: Dict[str, Symbol] = {}

    def define(self, name: str, symbol: Symbol):
        self.symbols[name] = symbol

    def get_symbol(self, name: str) -> Symbol:
        key = name.upper()
        if key in self.symbols:
            return self.symbols[key]
        if self.parent:
            return self.parent.get_symbol(key)
        raise FortranRuntimeError(f'Undefined variable {name}')


class Interpreter:
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.global_env = Environment()
        self.subprograms: Dict[str, Subprogram] = {}
        self.formats: Dict[int, str] = {}
        self.files: Dict[int, Any] = {}
        self.common_blocks: Dict[str, Dict[str, Symbol]] = {}

    def run_source(self, source: str):
        lines = preprocess_fixed_form(source)
        ast = Parser(lines).parse()
        self.run_program(ast)

    def run_file(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            self.run_source(f.read())

    def run_program(self, prog: Program):
        for s in prog.subprograms:
            self.subprograms[s.name] = s
            self._collect_formats(s.body)
        self._collect_formats(prog.body)
        try:
            self.exec_block(prog.body, self.global_env)
        except StopExecution:
            return

    def _collect_formats(self, body: List[Stmt]):
        for st in body:
            if isinstance(st, Format):
                self.formats[st.label_id] = st.raw
            if isinstance(st, IfThen):
                self._collect_formats(st.then_body)
                self._collect_formats(st.else_body)
            if isinstance(st, DoLoop):
                self._collect_formats(st.body)

    def exec_block(self, body: List[Stmt], env: Environment):
        label_map = {st.label: i for i, st in enumerate(body) if st.label is not None}
        i = 0
        while i < len(body):
            st = body[i]
            jump = self.exec_stmt(st, env, label_map)
            if jump is None:
                i += 1
            else:
                if jump not in label_map:
                    raise FortranRuntimeError(f'Unknown label {jump}')
                i = label_map[jump]

    def exec_stmt(self, st: Stmt, env: Environment, label_map: Dict[int, int]):
        if isinstance(st, Declaration):
            for name, shape, char_len in st.items:
                if name in env.symbols:
                    continue
                env.define(name, Symbol(st.vartype, self.default_value(st.vartype, shape, char_len), shape, char_len))
            return None
        if isinstance(st, Assignment):
            ref = self.get_lvalue(st.target, env)
            ref.value = self.cast_assign(self.eval_expr(st.expr, env), ref.value)
            return None
        if isinstance(st, IfThen):
            if self.truthy(self.eval_expr(st.cond, env)):
                self.exec_block(st.then_body, env)
            else:
                self.exec_block(st.else_body, env)
            return None
        if isinstance(st, ArithmeticIf):
            v = self.eval_expr(st.expr, env)
            if v < 0:
                return st.neg_label
            if v == 0:
                return st.zero_label
            return st.pos_label
        if isinstance(st, Goto):
            return st.label_target
        if isinstance(st, Continue):
            return None
        if isinstance(st, Stop):
            if st.message:
                self.stdout.write(st.message + '\n')
            raise StopExecution()
        if isinstance(st, DoLoop):
            start = int(self.eval_expr(st.start, env))
            end = int(self.eval_expr(st.end, env))
            step = int(self.eval_expr(st.step, env)) if st.step else 1
            sym = env.get_symbol(st.var)
            val = start
            cond = (lambda x: x <= end) if step > 0 else (lambda x: x >= end)
            while cond(val):
                sym.value = val
                self.exec_block(st.body, env)
                val += step
            return None
        if isinstance(st, Read):
            self.exec_read(st, env)
            return None
        if isinstance(st, Write):
            self.exec_write(st, env)
            return None
        if isinstance(st, Format):
            self.formats[st.label_id] = st.raw
            return None
        if isinstance(st, OpenStmt):
            unit = int(st.args.get('UNIT', -1))
            fname = st.args.get('FILE')
            mode = st.args.get('STATUS', 'UNKNOWN').upper()
            py_mode = 'r+' if mode in ('OLD', 'UNKNOWN') else 'w+'
            self.files[unit] = open(fname, py_mode, encoding='utf-8')
            return None
        if isinstance(st, CloseStmt):
            unit = int(st.args.get('UNIT', -1))
            fh = self.files.pop(unit, None)
            if fh:
                fh.close()
            return None
        if isinstance(st, CallStmt):
            self.call_subroutine(st.name, st.args, env)
            return None
        if isinstance(st, ReturnStmt):
            raise ReturnSignal()
        if isinstance(st, CommonBlock):
            block = self.common_blocks.setdefault(st.block_name, {})
            for n in st.names:
                if n in block:
                    env.define(n, block[n])
                else:
                    sym = Symbol('REAL', 0.0)
                    block[n] = sym
                    env.define(n, sym)
            return None
        if isinstance(st, DataStmt):
            vals = [self.eval_expr(v, env) for v in st.values]
            for i, target in enumerate(st.targets):
                ref = self.get_lvalue(target, env)
                ref.value = vals[i % len(vals)]
            return None
        raise FortranRuntimeError(f'Unsupported statement: {st}')

    def cast_assign(self, value, old):
        if isinstance(old, bool):
            return bool(value)
        if isinstance(old, int) and not isinstance(old, bool):
            return int(value)
        if isinstance(old, float):
            return float(value)
        if isinstance(old, str):
            s = str(value)
            return s[: len(old)].ljust(len(old))
        return value

    def default_value(self, vartype: str, shape, char_len):
        scalar = 0
        if vartype == 'REAL':
            scalar = 0.0
        elif vartype == 'LOGICAL':
            scalar = False
        elif vartype == 'CHARACTER':
            scalar = ' ' * (char_len or 1)
        if not shape:
            return scalar
        if len(shape) == 1:
            return [scalar for _ in range(shape[0])]
        if len(shape) == 2:
            return [[scalar for _ in range(shape[1])] for _ in range(shape[0])]
        raise FortranRuntimeError('Only 1D/2D arrays supported')

    def get_lvalue(self, expr: Expr, env: Environment) -> Ref:
        if isinstance(expr, Var):
            sym = env.get_symbol(expr.name)
            if sym.vartype == 'REF':
                return sym.value
            return Ref(lambda: sym.value, lambda v: setattr(sym, 'value', v))
        if isinstance(expr, FuncCall):
            # treat as array reference if symbol exists and is array
            try:
                sym = env.get_symbol(expr.name)
                if sym.shape:
                    idx = [int(self.eval_expr(a, env)) - 1 for a in expr.args]
                    return self.array_ref(sym, idx)
            except FortranRuntimeError:
                pass
        raise FortranRuntimeError('Invalid assignment target')

    def array_ref(self, sym: Symbol, idx: List[int]) -> Ref:
        if len(idx) == 1:
            return Ref(lambda: sym.value[idx[0]], lambda v: sym.value.__setitem__(idx[0], v))
        if len(idx) == 2:
            return Ref(lambda: sym.value[idx[0]][idx[1]], lambda v: sym.value[idx[0]].__setitem__(idx[1], v))
        raise FortranRuntimeError('Only 1D/2D arrays supported')

    def eval_expr(self, expr: Expr, env: Environment):
        if isinstance(expr, Number):
            return expr.value
        if isinstance(expr, String):
            return expr.value
        if isinstance(expr, Logical):
            return expr.value
        if isinstance(expr, Var):
            sym = env.get_symbol(expr.name)
            return sym.value.value if sym.vartype == 'REF' else sym.value
        if isinstance(expr, UnaryOp):
            v = self.eval_expr(expr.operand, env)
            return {'-': -v, '+': +v, '.NOT.': (not self.truthy(v))}[expr.op]
        if isinstance(expr, BinOp):
            a = self.eval_expr(expr.left, env)
            b = self.eval_expr(expr.right, env)
            return self.apply_op(a, expr.op, b)
        if isinstance(expr, FuncCall):
            # array element?
            try:
                sym = env.get_symbol(expr.name)
                if sym.shape:
                    idx = [int(self.eval_expr(a, env)) - 1 for a in expr.args]
                    return self.array_ref(sym, idx).value
            except FortranRuntimeError:
                pass
            args = [self.eval_expr(a, env) for a in expr.args]
            if expr.name in self.builtins():
                return self.builtins()[expr.name](*args)
            if expr.name in self.subprograms:
                sp = self.subprograms[expr.name]
                if sp.kind != 'FUNCTION':
                    raise FortranRuntimeError(f'{expr.name} is SUBROUTINE, cannot use in expression')
                return self.call_function(sp, expr.args, env)
            raise FortranRuntimeError(f'Unknown function {expr.name}')
        raise FortranRuntimeError(f'Unknown expression {expr}')

    def apply_op(self, a, op, b):
        if op == '+':
            return a + b
        if op == '-':
            return a - b
        if op == '*':
            return a * b
        if op == '/':
            return a / b
        if op == '**':
            return a ** b
        if op == '.AND.':
            return self.truthy(a) and self.truthy(b)
        if op == '.OR.':
            return self.truthy(a) or self.truthy(b)
        if op == '.EQ.':
            return a == b
        if op == '.NE.':
            return a != b
        if op == '.LT.':
            return a < b
        if op == '.LE.':
            return a <= b
        if op == '.GT.':
            return a > b
        if op == '.GE.':
            return a >= b
        raise FortranRuntimeError(f'Unsupported op {op}')

    def truthy(self, v):
        return bool(v)

    def builtins(self):
        return {
            'SQRT': lambda x: math.sqrt(x),
            'SIN': lambda x: math.sin(x),
            'COS': lambda x: math.cos(x),
            'EXP': lambda x: math.exp(x),
            'LOG': lambda x: math.log(x),
            'ABS': lambda x: abs(x),
            'MOD': lambda a, b: a % b,
            'LEN': lambda s: len(str(s).rstrip()),
            'INDEX': lambda s, sub: (str(s).find(str(sub)) + 1 if str(sub) in str(s) else 0),
            'CHAR': lambda i: chr(int(i)),
            'ICHAR': lambda c: ord(str(c)[0]),
        }

    def call_subroutine(self, name: str, arg_exprs: List[Expr], caller_env: Environment):
        if name not in self.subprograms:
            raise FortranRuntimeError(f'Unknown subroutine {name}')
        sp = self.subprograms[name]
        if sp.kind != 'SUBROUTINE':
            raise FortranRuntimeError(f'{name} is not a SUBROUTINE')
        local = Environment(parent=self.global_env)
        for p, arg in zip(sp.params, arg_exprs):
            ref = self.get_lvalue(arg, caller_env)
            local.define(p, Symbol('REF', ref))

        try:
            self.exec_block(sp.body, local)
        except ReturnSignal:
            pass

    def call_function(self, sp: Subprogram, arg_exprs: List[Expr], caller_env: Environment):
        local = Environment(parent=self.global_env)
        for p, arg in zip(sp.params, arg_exprs):
            local.define(p, Symbol('REAL', self.eval_expr(arg, caller_env)))
        ret_type = sp.return_type or 'REAL'
        local.define(sp.name, Symbol(ret_type, self.default_value(ret_type, None, None), None, None))
        try:
            self.exec_block(sp.body, local)
        except ReturnSignal:
            pass
        return local.get_symbol(sp.name).value

    def _resolve_stream(self, unit, for_read=False):
        if unit == '*':
            return self.stdin if for_read else self.stdout
        if unit == '6':
            return self.stdout
        if unit == '5':
            return self.stdin
        u = int(unit)
        return self.files.get(u, self.stdout)

    def exec_write(self, st: Write, env: Environment):
        stream = self._resolve_stream(st.unit, for_read=False)
        vals = [self.eval_expr(i, env) for i in st.items]
        if st.fmt == '*':
            stream.write(' '.join(str(v) for v in vals) + '\n')
            return
        if st.fmt.isdigit() and int(st.fmt) in self.formats:
            fmt = self.formats[int(st.fmt)]
            stream.write(self.apply_format(fmt, vals) + '\n')
            return
        stream.write(' '.join(str(v) for v in vals) + '\n')

    def exec_read(self, st: Read, env: Environment):
        stream = self._resolve_stream(st.unit, for_read=True)
        line = stream.readline()
        parts = line.strip().split()
        for i, target in enumerate(st.items):
            ref = self.get_lvalue(target, env)
            val = parts[i] if i < len(parts) else ''
            old = ref.value
            if isinstance(old, int):
                ref.value = int(val)
            elif isinstance(old, float):
                ref.value = float(val)
            elif isinstance(old, bool):
                ref.value = val.upper() in ('T', '.TRUE.', 'TRUE', '1')
            else:
                ref.value = str(val)

    def apply_format(self, raw: str, vals: List[Any]) -> str:
        src = raw.strip()
        if src.startswith('(') and src.endswith(')'):
            src = src[1:-1]
        chunks = []
        vi = 0
        for part in [p.strip() for p in src.split(',') if p.strip()]:
            if part.startswith("'") and part.endswith("'"):
                chunks.append(part[1:-1])
                continue
            m = None
            if part.upper().startswith('I'):
                w = int(part[1:])
                chunks.append(f'{int(vals[vi]):>{w}}')
                vi += 1
            elif part.upper().startswith('F'):
                m = part[1:].split('.')
                w, d = int(m[0]), int(m[1])
                chunks.append(f'{float(vals[vi]):>{w}.{d}f}')
                vi += 1
            elif part.upper().startswith('A'):
                w = int(part[1:]) if len(part) > 1 else 0
                s = str(vals[vi])
                chunks.append(f'{s:>{w}}' if w else s)
                vi += 1
        return ''.join(chunks)


def run_repl():
    intr = Interpreter()
    buf = []
    print('Fortran77 REPL. End input with a single dot.')
    while True:
        try:
            line = input('F77> ')
        except EOFError:
            break
        if line.strip() in ('QUIT', 'EXIT'):
            break
        if line.strip() == '.':
            src = '\n'.join(buf)
            buf = []
            try:
                intr.run_source(src)
            except Exception as e:
                print(f'ERROR: {e}')
            continue
        buf.append(line)
