# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import os

import yaml

from .cli import build_parser
from .paths import environments_path, share_path
from .recipe import parse_recipe
from .sync import package_paths


def _write(path: str, content: str) -> None:
    import mkdocs_gen_files

    with mkdocs_gen_files.open(path, "w") as handle:
        handle.write(content.rstrip() + "\n")


# The width that argparse wraps the help texts to, whatever terminal builds the pages.
HELP_COLUMNS = "90"


def _subcommands(parser: argparse.ArgumentParser) -> list[tuple[str, str, argparse.ArgumentParser]]:
    """The subcommands of a parser, each as its name, its one-line help and its parser."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            return [(name, helps.get(name, ""), child) for name, child in action.choices.items()]
    return []


def _usage(parser: argparse.ArgumentParser) -> str:
    """The help of a command without its description, which the page states as prose."""
    description, parser.description = parser.description, None
    try:
        return parser.format_help().rstrip()
    finally:
        parser.description = description


def _command_section(command: str, summary: str, parser: argparse.ArgumentParser, level: int) -> str:
    text = " ".join((parser.description or summary).split())
    return f"{'#' * level} `{command}`\n\n{text}\n\n```text\n{_usage(parser)}\n```\n"


def _anchor(command: str) -> str:
    return command.replace(" ", "-")


def generate_cli() -> None:
    """Write the command line reference: one page, a section for each command."""
    columns, os.environ["COLUMNS"] = os.environ.get("COLUMNS"), HELP_COLUMNS
    try:
        parser = build_parser()
        rows = ["| Command | Purpose |", "| --- | --- |"]
        sections = [_command_section("seanerstack", "", parser, 2).replace("## `seanerstack`", "## Global options", 1)]
        for name, summary, child in sorted(_subcommands(parser)):
            command = f"seanerstack {name}"
            children = sorted(_subcommands(child))
            if not children:
                rows.append(f"| [`{command}`](#{_anchor(command)}) | {summary} |")
                sections.append(_command_section(command, summary, child, 2))
                continue
            sections.append(f"## `{command}`\n\n{summary}\n")
            for child_name, child_summary, grandchild in children:
                leaf = f"{command} {child_name}"
                rows.append(f"| [`{leaf}`](#{_anchor(leaf)}) | {child_summary} |")
                sections.append(_command_section(leaf, child_summary, grandchild, 3))
    finally:
        if columns is None:
            del os.environ["COLUMNS"]
        else:
            os.environ["COLUMNS"] = columns
    intro = (
        "Every `seanerstack` command, generated from its own help. The global options go before the "
        "command, as in `seanerstack --state-dir DIR init`."
    )
    _write("reference/command-line.md", "# Command line\n\n" + intro + "\n\n" + "\n".join(rows) + "\n\n" + "\n".join(sections))


def _directive_table(directives, name: str) -> str:
    selected = [directive for directive in directives if directive.name == name]
    rows = ["| Declaration | Recipe comment |", "| --- | --- |"]
    for directive in selected:
        declaration = " ".join(directive.source.strip().split()).replace("|", "\\|")
        comment = (directive.comment or "").replace("|", "\\|")
        rows.append(f"| `{declaration}` | {comment} |")
    return "\n".join(rows) if selected else ""


def _summary(recipe) -> str:
    """The first sentence of the recipe's description, for a table cell."""
    text = " ".join((recipe.docstring or "").split())
    first = text.split(". ")[0].rstrip(".")
    return first.replace("|", "\\|")


def _versions(recipe) -> list[str]:
    return [str(directive.args[0]) for directive in recipe.directives if directive.name == "version" and directive.args]


def generate_packages() -> None:
    """Write a page for each recipe, and an index that lists them."""
    root = share_path()
    recipes = {name: (path, parse_recipe(path)) for name, path in package_paths().items()}
    meta = recipes.get("seanergys-meta")
    in_stack = {str(d.args[0]) for d in meta[1].directives if d.name == "depends_on" and d.args} if meta else set()
    for name, (path, recipe) in recipes.items():
        attrs = [
            f"| {key} | `{recipe.attributes[key]}` |"
            for key in ("homepage", "git", "url", "pypi", "seanerstack_resource")
            if key in recipe.attributes
        ]
        attrs.append(f"| recipe | `share/seanerstack/{path.relative_to(root)}` |")
        sections = [f"# {name}", recipe.docstring or "", "| Source | |\n| --- | --- |\n" + "\n".join(attrs)]
        for title, directive in (
            ("Versions", "version"), ("Variants", "variant"), ("Dependencies", "depends_on"),
            ("Conflicts", "conflicts"), ("Provides", "provides"),
        ):
            table = _directive_table(recipe.directives, directive)
            if table:
                sections.append(f"## {title}\n\n{table}")
        _write(f"reference/packages/{name}.md", "\n\n".join(section for section in sections if section))

    rows = ["| Package | Description | Newest version | Stack |", "| --- | --- | --- | :---: |"]
    for name, (_, recipe) in sorted(recipes.items()):
        versions = [version for version in _versions(recipe) if version[:1].isdigit()] or _versions(recipe)
        newest = f"`{versions[0]}`" if versions else ""
        rows.append(f"| [{name}]({name}.md) | {_summary(recipe)} | {newest} | {'✔' if name in in_stack else ''} |")
    index = [
        "# Packages",
        "The recipes of the Seanerstack Spack repository, generated from each `package.py`. "
        "A package marked under *Stack* is installed by `seanergys-meta`.",
        "\n".join(rows),
    ]
    _write("reference/packages/index.md", "\n\n".join(index))


def generate_environments() -> None:
    """Write the environment reference: one page, a section for each shipped environment."""
    root = share_path()
    rows = ["| Environment | Root specs | Activate with |", "| --- | --- | --- |"]
    sections: list[str] = []
    for directory in sorted(path for path in environments_path().iterdir() if path.is_dir()):
        manifest = directory / "spack.yaml"
        if not manifest.is_file():
            continue
        raw = manifest.read_text(encoding="utf-8")
        specs = ((yaml.safe_load(raw) or {}).get("spack") or {}).get("specs") or []
        name = directory.name
        listed = ", ".join(f"`{spec}`" for spec in specs)
        rows.append(f"| [{name}](#{name}) | {listed} | `seanerstack paths env --environment {name}` |")
        sections.append(
            f"## {name}\n\nManifest: `share/seanerstack/{manifest.relative_to(root)}`\n\n```yaml\n{raw.rstrip()}\n```"
        )
    intro = (
        "The Spack environments that Seanerstack ships, generated from their `spack.yaml` manifests. "
        "No manifest names a checkout: `spack develop` binds one on each machine, as "
        "[Work on a package](../how-to/work-on-a-package.md) shows."
    )
    _write("reference/environments.md", "# Environments\n\n" + intro + "\n\n" + "\n".join(rows) + "\n\n" + "\n\n".join(sections))


def main() -> None:
    generate_cli()
    generate_packages()
    generate_environments()
