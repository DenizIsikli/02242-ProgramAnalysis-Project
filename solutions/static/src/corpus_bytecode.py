"""Load the integer-only corpus through JPAMB using the installed JDK.

This evaluation adapter avoids stale committed JSON when adding pairs. It is not a
general replacement for jvm2json: unsupported descriptors, instructions and exception
tables are errors. No compiled files are written into the worktree.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import jpamb
from jpamb import jvm

CLASS = "jpamb.cases.Refactorings"
METHOD = re.compile(r"  public static int (\w+)\([^;]*\);")
INSTRUCTION = re.compile(r"^\s+(\d+):\s+(\w+)(?:\s+(.*))?$")


def parse_javap(text: str) -> dict:
    methods = []
    for block in re.split(r"\n(?=  (?:public|private|protected) )", text):
        match = METHOD.match(block)
        if match is None:
            continue
        name = match[1]
        descriptor = re.search(r"descriptor: \((I*)\)I\s", block)
        locals_match = re.search(r"stack=\d+, locals=(\d+), args_size=\d+", block)
        if descriptor is None or locals_match is None:
            raise ValueError(f"{name}: expected a static int-only method")
        if "Exception table:" in block:
            raise ValueError(f"{name}: exception handlers are not supported")
        code = block.split("    Code:\n", 1)[1]
        raw = []
        for line in code.splitlines()[1:]:
            instruction = INSTRUCTION.match(line)
            if instruction is None:
                break
            raw.append((int(instruction[1]), instruction[2], instruction[3] or ""))
        offsets = {offset: index for index, (offset, _, _) in enumerate(raw)}
        if not raw:
            raise ValueError(f"{name}: no bytecode found")
        bytecode = []
        for offset, mnemonic, operand in raw:
            op = {"offset": offset}
            if mnemonic.startswith(("iload", "istore")):
                base, _, suffix = mnemonic.partition("_")
                op.update(
                    opr="load" if base == "iload" else "store",
                    type="int",
                    index=int(suffix or operand),
                )
            elif mnemonic.startswith("iconst_") or mnemonic in ("bipush", "sipush"):
                value = mnemonic[7:] if mnemonic.startswith("iconst_") else operand
                op.update(
                    opr="push",
                    value={
                        "type": "integer",
                        "value": -1 if value == "m1" else int(value),
                    },
                )
            elif mnemonic in ("iadd", "isub", "imul", "idiv", "irem"):
                op.update(opr="binary", type="int", operant=mnemonic[1:])
            elif mnemonic == "ineg":
                op.update(opr="negate", type="int")
            elif mnemonic == "ireturn":
                op.update(opr="return", type="int")
            elif mnemonic.startswith("if_icmp"):
                op.update(
                    opr="if", condition=mnemonic[7:], target=offsets[int(operand)]
                )
            elif mnemonic in ("ifeq", "ifne", "iflt", "ifle", "ifgt", "ifge"):
                op.update(
                    opr="ifz", condition=mnemonic[2:], target=offsets[int(operand)]
                )
            elif mnemonic == "goto":
                op.update(opr="goto", target=offsets[int(operand)])
            else:
                raise ValueError(f"{name}: unsupported instruction {mnemonic}")
            bytecode.append(op)
        methods.append(
            {
                "name": name,
                "params": [
                    {"type": {"base": "int"}, "annotations": []} for _ in descriptor[1]
                ],
                "code": {
                    "bytecode": bytecode,
                    "max_locals": int(locals_match[1]),
                    "exceptions": [],
                },
            }
        )
    if not methods:
        raise ValueError("javap returned no supported corpus methods")
    return {"name": CLASS.replace(".", "/"), "methods": methods}


def compile_corpus(root: Path) -> dict:
    with TemporaryDirectory(prefix="jpamb-corpus-") as build:
        sources = sorted((root / "cases/jpamb/utils").glob("*.java"))
        sources.append(root / "cases/jpamb/cases/Refactorings.java")
        subprocess.run(
            ["javac", "-g", "-d", build, *map(str, sources)],
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["javap", "-classpath", build, "-c", "-v", "-p", CLASS],
            check=True,
            capture_output=True,
            text=True,
        )
    return parse_javap(result.stdout)


@dataclass(frozen=True)
class CorpusSuite(jpamb.Suite):
    class_data: dict

    def findclass(self, cn: jvm.ClassName, *, eff: jpamb.utils.Effect) -> dict:
        if cn.dotted() == CLASS:
            return self.class_data
        return super().findclass(cn, eff=eff)


def load_bytecode(root: Path, class_data: dict | None = None) -> jpamb.Bytecode:
    suite = (
        jpamb.Suite.from_workdir(root.resolve())
        if class_data is None
        else CorpusSuite(root.resolve(), class_data)
    )
    return jpamb.Bytecode(suite, jpamb.utils.Effect(None))
