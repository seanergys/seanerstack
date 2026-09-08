# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse

import yaml

from .cli import build_parser
from .paths import environments_path, share_path
from .recipe import parse_recipe
from .sync import package_paths


def _write(path: str, content: str) -> None:
    import mkdocs_gen_files

    with mkdocs_gen_files.open(path, "w") as handle:
        handle.write(content.rstrip() + "\n")


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _cli_pages(command: str, parser: argparse.ArgumentParser):
    yield command, parser
    for name, child in _subparsers(parser).items():
        yield from _cli_pages(f"{command} {name}", child)


def generate_cli() -> None:
    parser = build_parser()
    pages = list(_cli_pages("seanstack", parser))
    links: list[str] = []
    for command, command_parser in pages:
        slug = command.replace(" ", "-")
        links.append(f"- [`{command}`]({slug}.md)")
        help_text = command_parser.format_help().rstrip()
        content = f"# `{command}`\n\n{command_parser.description or ''}\n\n```text\n{help_text}\n```\n"
        _write(f"reference/cli/{slug}.md", content)
    _write("reference/cli/index.md", "# Command line reference\n\n" + "\n".join(links))


def _directive_table(directives, name: str) -> str:
    selected = [directive for directive in directives if directive.name == name]
    if not selected:
        return "_None._"
    rows = ["| Declaration | Recipe comment |", "| --- | --- |"]
    for directive in selected:
        declaration = " ".join(directive.source.strip().split()).replace("|", "\\|")
        comment = (directive.comment or "").replace("|", "\\|")
        rows.append(f"| `{declaration}` | {comment} |")
    return "\n".join(rows)


def generate_packages() -> None:
    root = share_path()
    links: list[str] = []
    for name, path in package_paths().items():
        recipe = parse_recipe(path)
        links.append(f"- [{name}]({name}.md)")
        attrs = []
        for key in ("homepage", "git", "url", "pypi", "seanstack_resource"):
            if key in recipe.attributes:
                attrs.append(f"- **{key}:** `{recipe.attributes[key]}`")
        content = f"""# {name}

{recipe.docstring or '_No package description is present in the recipe._'}

## Source

{chr(10).join(attrs) if attrs else '_No source attributes found._'}

Recipe: `share/seanstack/{path.relative_to(root)}`

## Versions

{_directive_table(recipe.directives, 'version')}

## Variants

{_directive_table(recipe.directives, 'variant')}

## Dependencies

{_directive_table(recipe.directives, 'depends_on')}

## Conflicts

{_directive_table(recipe.directives, 'conflicts')}

## Provides

{_directive_table(recipe.directives, 'provides')}
"""
        _write(f"reference/packages/{name}.md", content)
    _write("reference/packages/index.md", "# Package reference\n\nGenerated directly from the native Spack recipes.\n\n" + "\n".join(links))


def _format_yaml(value) -> str:
    return "```yaml\n" + yaml.safe_dump(value, sort_keys=False).rstrip() + "\n```"


def generate_environments() -> None:
    root = share_path()
    envs = environments_path()
    links: list[str] = []
    for directory in sorted(path for path in envs.iterdir() if path.is_dir()):
        manifest = directory / "spack.yaml"
        if not manifest.is_file():
            continue
        raw = manifest.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        spack = data.get("spack", {})
        links.append(f"- [{directory.name}]({directory.name}.md)")
        specs = spack.get("specs", [])
        develop = spack.get("develop")
        content = f"""# {directory.name}

Manifest: `share/seanstack/{manifest.relative_to(root)}`

## Root specs

{_format_yaml(specs)}

## Develop bindings

{_format_yaml(develop) if develop else '_No checkout path is committed. Use `spack develop` to bind local sources._'}

## Complete manifest

```yaml
{raw.rstrip()}
```
"""
        _write(f"reference/environments/{directory.name}.md", content)
    _write("reference/environments/index.md", "# Environment reference\n\nGenerated directly from native `spack.yaml` manifests.\n\n" + "\n".join(links))


def main() -> None:
    generate_cli()
    generate_packages()
    generate_environments()
