"""Command-line interface for KnowledgeFlow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .agent_tools import (
    build_hot_cache,
    challenge_proposal,
    context_pack,
    crosslink_vault,
    search_vault,
)
from .pipeline import Store, health, promote, render_dashboard, run, sync


def main() -> None:
    parser = argparse.ArgumentParser(prog="knowledgeflow", description="Auditable, AI-native knowledge system for Obsidian")
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
    commands.add_parser("hot-cache", help="Generate single-read non-hub Agent Hot Cache")

    run_parser = commands.add_parser("run", help="Run sync -> promote -> render -> hot-cache -> health")
    run_parser.add_argument("--offline", action="store_true", help="Skip network fetching")
    run_parser.add_argument("--retry-rejected", action="store_true", help="Retry rejected candidates after detail-page enrichment")

    search_parser = commands.add_parser("search", help="Quality-aware BM25 + bilingual synonym search")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=12)
    search_parser.add_argument("--json", action="store_true")

    pack_parser = commands.add_parser("context-pack", help="Pack token/char-bounded evidence bundle for agents")
    pack_parser.add_argument("query", help="Topic or question")
    pack_parser.add_argument("--budget", type=int, default=4000)
    pack_parser.add_argument("--limit", type=int, default=6)
    pack_parser.add_argument("--json", action="store_true")

    chal_parser = commands.add_parser("challenge", help="Red-team proposal against ADRs, risks, and compliance boundaries")
    chal_parser.add_argument("proposal", help="Proposal or design assumption to stress-test")
    chal_parser.add_argument("--limit", type=int, default=8)
    chal_parser.add_argument("--json", action="store_true")

    link_parser = commands.add_parser("crosslink", help="Conservative cross-folder entity linking")
    mode = link_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    link_parser.add_argument("--limit", type=int, default=120)

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
    elif args.command == "hot-cache":
        result = build_hot_cache(store)
    elif args.command == "search":
        result = search_vault(store, args.query, limit=args.limit)
    elif args.command == "context-pack":
        result = context_pack(store, args.query, budget=args.budget, limit=args.limit)
        if not args.json:
            print(result["markdown"])
            return
    elif args.command == "challenge":
        result = challenge_proposal(store, args.proposal, limit=args.limit)
        if not args.json:
            print(result["markdown"])
            return
    elif args.command == "crosslink":
        result = crosslink_vault(store, apply=args.apply, limit=args.limit)
    else:
        result = run(store, offline=args.offline, retry_rejected=args.retry_rejected)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "health" and not result["healthy"]:
        raise SystemExit(1)
