"""pytest 引导：保证 `import robot` 可用。

目录现名 robot（D:/NPCSidekick/robot），自然导入即可；这里仍把上级目录
插到 sys.path 首位兜底（裸 pytest 不带 CWD）。曾用名 4_robot（数字开头不能作
包名）时的 sys.modules 注册分支保留——哪天改回去也照常能跑。
"""
import importlib.util
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    import robot  # noqa: F401
except ImportError:
    _PKG = pathlib.Path(__file__).resolve().parent.parent
    _spec = importlib.util.spec_from_file_location(
        "robot", _PKG / "__init__.py", submodule_search_locations=[str(_PKG)])
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["robot"] = _mod
    _spec.loader.exec_module(_mod)
