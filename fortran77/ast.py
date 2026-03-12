from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any


@dataclass
class Program:
    name: Optional[str]
    body: List['Stmt']
    subprograms: List['Subprogram'] = field(default_factory=list)


@dataclass
class Subprogram:
    kind: str  # SUBROUTINE|FUNCTION
    name: str
    params: List[str]
    body: List['Stmt']
    return_type: Optional[str] = None


class Stmt:
    label: Optional[int] = None


@dataclass
class Declaration(Stmt):
    vartype: str
    items: List[Tuple[str, Optional[Tuple[int, ...]], Optional[int]]]
    # (name, shape, char_len)


@dataclass
class Assignment(Stmt):
    target: 'Expr'
    expr: 'Expr'


@dataclass
class IfThen(Stmt):
    cond: 'Expr'
    then_body: List[Stmt]
    else_body: List[Stmt]


@dataclass
class ArithmeticIf(Stmt):
    expr: 'Expr'
    neg_label: int
    zero_label: int
    pos_label: int


@dataclass
class Goto(Stmt):
    label_target: int


@dataclass
class Continue(Stmt):
    pass


@dataclass
class Stop(Stmt):
    message: Optional[str] = None


@dataclass
class DoLoop(Stmt):
    end_label: int
    var: str
    start: 'Expr'
    end: 'Expr'
    step: Optional['Expr']
    body: List[Stmt]


@dataclass
class Read(Stmt):
    unit: Any
    fmt: Any
    items: List['Expr']


@dataclass
class Write(Stmt):
    unit: Any
    fmt: Any
    items: List['Expr']


@dataclass
class Format(Stmt):
    label_id: int
    raw: str


@dataclass
class OpenStmt(Stmt):
    args: dict


@dataclass
class CloseStmt(Stmt):
    args: dict


@dataclass
class CallStmt(Stmt):
    name: str
    args: List['Expr']


@dataclass
class ReturnStmt(Stmt):
    pass


@dataclass
class CommonBlock(Stmt):
    block_name: str
    names: List[str]


@dataclass
class DataStmt(Stmt):
    targets: List['Expr']
    values: List['Expr']


class Expr:
    pass


@dataclass
class Number(Expr):
    value: Any


@dataclass
class String(Expr):
    value: str


@dataclass
class Logical(Expr):
    value: bool


@dataclass
class Var(Expr):
    name: str


@dataclass
class ArrayRef(Expr):
    name: str
    indices: List[Expr]


@dataclass
class UnaryOp(Expr):
    op: str
    operand: Expr


@dataclass
class BinOp(Expr):
    left: Expr
    op: str
    right: Expr


@dataclass
class FuncCall(Expr):
    name: str
    args: List[Expr]
