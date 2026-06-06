"""concrete — Concrete developer CLI.

Commands:
    concrete start emulator    Start Firebase emulators (forum)
    concrete start agent       Start LangGraph dev server (langgraph-agent)
    concrete start all         Start both
"""

import argparse
import sys

from concrete_cli.commands.start import cmd_start


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="concrete",
        description="Concrete developer CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # -- start ----------------------------------------------------------------
    start_parser = sub.add_parser("start", help="Start local services")
    start_sub = start_parser.add_subparsers(dest="service", metavar="<service>")
    start_sub.required = True

    for svc in ("emulator", "agent", "all"):
        p = start_sub.add_parser(svc, help={
            "emulator": "Start Firebase emulators",
            "agent":    "Start LangGraph dev server",
            "all":      "Start Firebase emulators + LangGraph dev server",
        }[svc])
        p.add_argument("--no-seed", action="store_true",
                       help="Skip Firebase seed data import/export")

    start_parser.set_defaults(func=cmd_start)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
