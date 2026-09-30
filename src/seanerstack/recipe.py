# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import ast
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Directive:
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    lineno: int
    end_lineno: int
    source: str
    comment: str | None = None


@dataclass(frozen=True)
class Recipe:
    path: Path
    class_name: str
    docstring: str | None
    attributes: dict[str, Any]
    directives: tuple[Directive, ...]

    @property
    def git(self) -> str | None:
        value = self.attributes.get("git")
        return value if isinstance(value, str) else None

    @property
    def url(self) -> str | None:
        value = self.attributes.get("url")
        return value if isinstance(value, str) else None

    @property
    def seanerstack_resource(self) -> str | None:
        value = self.attributes.get("seanerstack_resource")
        return value if isinstance(value, str) else None


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _preceding_comment(lines: list[str], lineno: int) -> str | None:
    index = lineno - 2
    comments: list[str] = []
    while index >= 0:
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            comments.append(stripped[1:].strip())
            index -= 1
            continue
        if not stripped and comments:
            break
        break
    if not comments:
        return None
    return " ".join(reversed(comments))


def parse_recipe(path: Path) -> Recipe:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not classes:
        raise ValueError(f"{path}: no package class found")
    cls = classes[0]

    attributes: dict[str, Any] = {}
    directives: list[Directive] = []
    for node in cls.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            attributes[node.targets[0].id] = _literal(node.value)
            continue
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name):
            continue
        directives.append(
            Directive(
                name=call.func.id,
                args=tuple(_literal(arg) for arg in call.args),
                kwargs={kw.arg: _literal(kw.value) for kw in call.keywords if kw.arg},
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                source=ast.get_source_segment(source, node) or ast.unparse(node),
                comment=_preceding_comment(lines, node.lineno),
            )
        )

    return Recipe(
        path=path,
        class_name=cls.name,
        docstring=ast.get_docstring(cls),
        attributes=attributes,
        directives=tuple(directives),
    )
