"""Run tournament parsers: raw/<id>/ -> data/parsed/<id>/.

    python -m pipeline.parse                 # every included tournament with a parser
    python -m pipeline.parse --only ID ...   # specific tournaments
"""
from __future__ import annotations

import argparse
import importlib
import sys
import traceback

from . import registry
from .schema import TournamentWriter
from .validate import validate_tournament


def run_parser(t: registry.Tournament) -> dict:
    spec = t.get("parser")
    if not spec:
        raise ValueError(f"{t.id}: no parser configured")
    mod_name, _, fn_name = spec.partition(":")
    mod = importlib.import_module(f"pipeline.parsers.{mod_name}")
    fn = getattr(mod, fn_name or "parse")
    w = TournamentWriter(t.id)
    fn(t, w, **(t.get("parser_options") or {}))
    return w.close({"parser": spec})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    ts = registry.all_tournaments(include_excluded=bool(a.only))
    if a.only:
        ts = [t for t in ts if t.id in set(a.only)]
    failed = 0
    for t in ts:
        if not t.get("parser"):
            if a.only:
                print(f"SKIP {t.id}: no parser")
            continue
        try:
            meta = run_parser(t)
            problems = validate_tournament(t.id)
            c = meta["counts"]
            status = "OK " if not problems else "WARN"
            print(f"{status} {t.id}: {c['teams']} teams, {c['games']} games "
                  f"({c['games_with_scores']} scored), {c['players']} players, "
                  f"{c['player_stat_rows']} stat rows, {len(meta['warnings'])} parser warnings")
            if not a.quiet:
                for p in problems[:15]:
                    print(f"     - {p}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.id}")
            traceback.print_exc()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
