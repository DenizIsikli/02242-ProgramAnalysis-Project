"""Hand-assembled bytecode for the corpus pairs, so tests do not need Docker/jvm2json.

The listings mirror what javac produces for jpamb.cases.Refactorings (see the Java source).
`tests/test_region_corpus.py` additionally checks the real decompiled JSON when available.
"""

import pytest

import jvm
from jvm import CmpOpr as C
from jvm import opcode as o

I = jvm.Int()


def _ops(*specs):
    """specs: callables taking offset; offsets assigned by position."""
    return [make(i) for i, make in enumerate(specs)]


def push(v):
    return lambda i: o.Push(offset=i, type=I, value=v)


def load(n):
    return lambda i: o.Load(offset=i, type=I, index=n)


def store(n):
    return lambda i: o.Store(offset=i, type=I, index=n)


def binop(op):
    return lambda i: o.Binary(offset=i, type=I, operant=op)


def ifz(c, t):
    return lambda i: o.Ifz(offset=i, condition=c, target=t)


def if_(c, t):
    return lambda i: o.If(offset=i, condition=c, target=t)


def goto(t):
    return lambda i: o.Goto(offset=i, target=t)


def ret():
    return lambda i: o.Return(offset=i, type=I)


B = jvm.BinaryOpr

SAFEDIV = _ops(
    load(1),
    ifz(C.Ne, 4),
    push(0),
    ret(),
    load(0),
    load(1),
    binop(B.Div),
    store(2),
    load(2),
    ret(),
)
SAFEDIV_EDITED = _ops(
    load(1), ifz(C.Ne, 4), push(0), ret(), load(0), load(1), binop(B.Div), ret()
)


def ratio(with_guard: bool):
    # offsets: 0 load b,1 load a,2 sub,3 store d,[4 load d,5 ifz ne->8,6 push 0,7 ret,]
    #          then: load d, load a, load b, if_icmple else, load a, goto join, else: load b, join: div, ret
    specs = [load(1), load(0), binop(B.Sub), store(2)]
    if with_guard:
        specs += [load(2), ifz(C.Ne, 8), push(0), ret()]
    n = len(specs)
    specs += [
        load(2),
        load(0),
        load(1),
        if_(C.Le, n + 6),
        load(0),
        goto(n + 7),
        load(1),
        binop(B.Div),
        ret(),
    ]
    return _ops(*specs)


SIGN = _ops(
    load(0),
    ifz(C.Le, 4),
    push(1),
    ret(),
    load(0),
    ifz(C.Ge, 8),
    push(-1),
    ret(),
    push(0),
    ret(),
)
SIGN_EDITED = _ops(load(0), ifz(C.Le, 4), push(1), ret(), push(-1), ret())


class FakeBytecode:
    """Just enough of jpamb.Bytecode for the analyser."""

    def __init__(self, methods: dict[str, tuple[list, int, str]]):
        self.methods = {}
        for name, (opcodes, max_locals, desc) in methods.items():
            mid = jvm.AbsMethodID.decode(f"jpamb.cases.Refactorings.{name}:{desc}")
            self.methods[mid] = jvm.Method(mid, opcodes, max_locals)
        self.ids = {n: m for n, m in zip(methods, self.methods)}

    def getmethod(self, mid):
        return self.methods[mid]

    def __getitem__(self, pc):
        return self.methods[pc.method].opcodes[pc.offset]


@pytest.fixture(scope="session")
def fake_bc():
    return FakeBytecode(
        {
            "safeDiv": (SAFEDIV, 3, "(II)I"),
            "safeDiv_edited": (SAFEDIV_EDITED, 2, "(II)I"),
            "ratio": (ratio(True), 3, "(II)I"),
            "ratio_edited": (ratio(False), 3, "(II)I"),
            "sign": (SIGN, 1, "(I)I"),
            "sign_edited": (SIGN_EDITED, 1, "(I)I"),
        }
    )
