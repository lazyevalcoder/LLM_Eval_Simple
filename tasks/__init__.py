"""Task registry for the personal eval suite."""

from . import codegen, debug, instruction, multifile, terminal, toolcalls

ALL = (
    codegen.TASKS
    + debug.TASKS
    + multifile.TASKS
    + toolcalls.TASKS
    + terminal.TASKS
    + instruction.TASKS
)

__all__ = ["ALL"]
