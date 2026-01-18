#!/usr/bin/env python3
import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

# ANSI colors
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
ORANGE = "\033[38;5;208m"  # works in most terminals
RED = "\033[31m"
DIM = "\033[2m"


def _colored_dot(label: str, dot: str) -> str:
    label = (label or "").strip().lower()
    if label == "blunder":
        return f"{RED}{dot}{RESET}"
    if label == "mistake":
        return f"{ORANGE}{dot}{RESET}"
    if label == "inaccuracy":
        return f"{YELLOW}{dot}{RESET}"
    return f"{GREEN}{dot}{RESET}"


def _plain_dot(label: str) -> str:
    label = (label or "").strip().lower()
    if label == "blunder":
        return "B"
    if label == "mistake":
        return "m"
    if label == "inaccuracy":
        return "i"
    return "."


def _default_moves_path(data_dir: str) -> str:
    return str(Path(data_dir) / "moves.csv")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="timeline", description="Print a per-game move timeline with blunder markers.")
    ap.add_argument("--data-dir", default=os.getenv("DATA_DIR", "data"), help="Data directory (default: data)")
    ap.add_argument("--moves", default="", help="Path to moves.csv (default: <data-dir>/moves.csv)")
    ap.add_argument("--limit", type=int, default=10, help="How many games to show (newest first)")
    ap.add_argument("--my-moves-only", action="store_true", help="Show only my moves (recommended)")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    ap.add_argument("--dot", default="●", help="Dot character (default: ●)")
    ap.add_argument("--sep-every", type=int, default=5, help="Insert separator every N dots (default: 5)")
    ap.add_argument("--show-positions", action="store_true", help="Print the move indices of inacc/mistake/blunder")
    args = ap.parse_args(argv)

    dot = args.dot

    data_dir = args.data_dir
    moves_path = args.moves or _default_moves_path(data_dir)
    moves_path = Path(moves_path)

    if not moves_path.exists():
        raise SystemExit(f"Missing {moves_path}. Run: chess-study analyze ... first.")

    # group rows by game_url
    games = defaultdict(list)
    with moves_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            games[r["game_url"]].append(r)

    # newest first by end_time_utc (same per-game)
    def game_sort_key(item):
        rows = item[1]
        return rows[0].get("end_time_utc", "")

    game_items = sorted(games.items(), key=game_sort_key, reverse=True)[: args.limit]

    sep = f"{DIM}|{RESET}" if not args.no_color else "|"

    for idx, (game_url, rows) in enumerate(game_items, start=1):
        rows.sort(key=lambda r: int(r.get("ply", "0") or 0))

        opp = rows[0].get("opponent", "?")
        my_color = rows[0].get("my_color", "?")

        filtered = []
        for r in rows:
            if args.my_moves_only:
                if str(r.get("is_my_move", "0")) == "1":
                    filtered.append(r)
            else:
                filtered.append(r)

        inacc_positions = []
        mistake_positions = []
        blunder_positions = []

        bar_parts = []
        for i, r in enumerate(filtered, start=1):
            label = (r.get("label") or "").strip().lower()
            if label == "inaccuracy":
                inacc_positions.append(i)
            elif label == "mistake":
                mistake_positions.append(i)
            elif label == "blunder":
                blunder_positions.append(i)

            if args.no_color:
                bar_parts.append(_plain_dot(label))
            else:
                bar_parts.append(_colored_dot(label, dot))

        # Insert separators every N dots
        pretty = []
        for i, ch in enumerate(bar_parts, start=1):
            pretty.append(ch)
            if args.sep_every > 0 and i % args.sep_every == 0 and i != len(bar_parts):
                pretty.append(sep)

        bar = "".join(pretty)

        print(f"{idx}) vs {opp}  ({my_color})  moves={len(filtered)}  url={game_url}")
        print("   " + bar)
        print(f"   inacc={len(inacc_positions)}  mistake={len(mistake_positions)}  blunder={len(blunder_positions)}")
        if args.show_positions:
            if inacc_positions:
                print(f"   inacc at:   {', '.join(map(str, inacc_positions))}")
            if mistake_positions:
                print(f"   mistake at: {', '.join(map(str, mistake_positions))}")
            if blunder_positions:
                print(f"   blunder at: {', '.join(map(str, blunder_positions))}")
        print()

    # legend
    if args.no_color:
        print("Legend: . ok  i inacc  m mistake  B blunder")
    else:
        print("Legend:", _colored_dot("", dot), "ok ",
              _colored_dot("inaccuracy", dot), "inacc ",
              _colored_dot("mistake", dot), "mistake ",
              _colored_dot("blunder", dot), "blunder")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
