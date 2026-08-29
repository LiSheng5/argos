"""pytest 引导：把仓库根插进 sys.path，保证 `import argos` 可用（裸 pytest 不带 CWD）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import argos  # noqa: F401
