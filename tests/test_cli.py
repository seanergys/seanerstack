# SPDX-License-Identifier: Apache-2.0
from seanerstack.cli import build_parser


def test_reorganized_cli():
    parser = build_parser()

    args = parser.parse_args(["package", "update", "demo", "--check"])
    assert (args.command, args.package_command, args.package) == ("package", "update", "demo")

    args = parser.parse_args(["toolchain", "bootstrap", "gcc@15"])
    assert (args.command, args.toolchain_command, args.compiler) == ("toolchain", "bootstrap", "gcc@15")

    args = parser.parse_args(["paths", "env", "--package", "properdocs"])
    assert (args.command, args.paths_command, args.package) == ("paths", "env", "properdocs")
