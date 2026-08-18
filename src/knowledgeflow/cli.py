"""Command-line interface for KnowledgeFlow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .pipeline import Store, health, promote, render_dashboard, run, sync


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowledgeflow", description="Auditable knowledge inflow for Obsidian")
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="Obsidian vault path")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync", help="Fetch trusted sources into the candidate ledger")
    sync_parser.add_argument("--offline", action="store_true")
    promote_parser = commands.add_parser("promote", help="Filter, route, number and write knowledge notes")
    promote_parser.add_argument("--dry-run", action="store_true")
    promote_parser.add_argument("--retry-rejected", action="store_true", help="Retry rejected candidates after detail-page enrichment")
    commands.add_parser("render", help="Regenerate the Obsidian inbox dashboard")
    commands.add_parser("health", help="Check generated-note contracts")
    run_parser = commands.add_parser("run", help="Run sync -> promote -> render -> health")
    run_parser.add_argument("--offline", action="store_true", help="Skip network fetching")
    run_parser.add_argument("--retry-rejected", action="store_true", help="Retry rejected candidates after detail-page enrichment")
    args = parser.parse_args()
    store = Store(args.vault.expanduser().resolve())
    if args.command == "sync":
        result = sync(store, offline=args.offline)
    elif args.command == "promote":
        result = promote(store, dry_run=args.dry_run, retry_rejected=args.retry_rejected)
    elif args.command == "render":
        result = render_dashboard(store)
    elif args.command == "health":
        result = health(store)
    else:
        result = run(store, offline=args.offline, retry_rejected=args.retry_rejected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "health" and not result["healthy"]:
        raise SystemExit(1)
