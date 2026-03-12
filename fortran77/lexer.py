from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


class FortranSyntaxError(Exception):
    pass


@dataclass
class Line:
    line_no: int
    label: Optional[int]
    text: str


LOGICAL_TOKENS = {
    '.AND.': 'AND',
    '.OR.': 'OR',
    '.NOT.': 'NOT',
    '.EQ.': 'EQ',
    '.NE.': 'NE',
    '.LT.': 'LT',
    '.LE.': 'LE',
    '.GT.': 'GT',
    '.GE.': 'GE',
    '.TRUE.': 'TRUE',
    '.FALSE.': 'FALSE',
}


def preprocess_fixed_form(source: str) -> List[Line]:
    """Process fixed-form source: comments/labels/continuation."""
    out: List[Line] = []
    pending: Optional[Line] = None

    for idx, raw in enumerate(source.splitlines(), 1):
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        first = line[0] if line else ' '
        if first in ('c', 'C', '*', '!'):
            continue

        # pad for fixed-form columns
        padded = line + ' ' * max(0, 6 - len(line))
        label_field = padded[:5]
        cont = padded[5:6]
        stmt = padded[6:] if len(padded) > 6 else ''

        label = None
        if label_field.strip():
            if not label_field.strip().isdigit():
                raise FortranSyntaxError(f'Invalid label at line {idx}: {label_field!r}')
            label = int(label_field.strip())

        if cont.strip():
            if pending is None:
                raise FortranSyntaxError(f'Continuation without previous statement at line {idx}')
            pending.text += ' ' + stmt.strip()
            continue

        current = Line(line_no=idx, label=label, text=stmt.strip())
        if pending is not None:
            out.append(pending)
        pending = current

    if pending is not None:
        out.append(pending)
    return out


_token_re = re.compile(
    r"\s*(\*\*|\(|\)|,|=|\+|-|\*|/|:[A-Za-z_][A-Za-z0-9_]*:|\.[A-Za-z]+\.|'[^']*'|\d+\.\d*|\d+|[A-Za-z_][A-Za-z0-9_]*|.)",
    re.IGNORECASE,
)


@dataclass
class Token:
    kind: str
    value: str


class ExprLexer:
    def __init__(self, text: str):
        self.tokens: List[Token] = []
        pos = 0
        while pos < len(text):
            m = _token_re.match(text, pos)
            if not m:
                raise FortranSyntaxError(f'Bad token near: {text[pos:pos+20]!r}')
            tok = m.group(1)
            pos = m.end()
            if tok.isspace() or tok == '':
                continue
            up = tok.upper()
            if up in LOGICAL_TOKENS:
                self.tokens.append(Token(LOGICAL_TOKENS[up], up))
            elif tok.startswith("'"):
                self.tokens.append(Token('STRING', tok[1:-1]))
            elif re.fullmatch(r'\d+\.\d*', tok):
                self.tokens.append(Token('REAL', tok))
            elif re.fullmatch(r'\d+', tok):
                self.tokens.append(Token('INT', tok))
            elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', tok):
                self.tokens.append(Token('ID', up))
            else:
                self.tokens.append(Token(tok, tok))
        self.tokens.append(Token('EOF', 'EOF'))
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def pop(self) -> Token:
        t = self.tokens[self.i]
        self.i += 1
        return t

    def match(self, *kinds: str) -> Optional[Token]:
        if self.peek().kind in kinds:
            return self.pop()
        return None

    def expect(self, kind: str) -> Token:
        t = self.pop()
        if t.kind != kind:
            raise FortranSyntaxError(f'Expected {kind}, got {t.kind}')
        return t
