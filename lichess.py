#!/usr/bin/env python3
import argparse
import csv
import io
import os
import time
from collections import defaultdict

import requests
import chess
import chess.pgn


def env_default(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def lichess_headers(token: str):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def import_chapter(study_id: str, token: str, pgn_text: str, name: str):
    url = f"https://lichess.org/api/study/{study_id}/import-pgn"
    data = {"name": name, "pgn": pgn_text}
    r = requests.post(url, headers=lichess_headers(token), data=data, timeout=30)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.reason}\n{r.text[:2000]}", response=r)
    return r.text


def parse_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except Exception:
        return default


def build_puzzle_pgn_from_row(row: dict) -> str:
    fen_before = row["fen_before"].strip()
    played_uci = row["played_move_uci"].strip()
    best_uci = (row.get("best_move_uci") or "").strip()

    board = chess.Board(fen_before)
    g = chess.pgn.Game()
    g.setup(board)

    # IMPORTANT: leave Site empty so Lichess will set it to the chapter URL
    g.headers["Site"] = ""
    g.headers["Event"] = "Biggest Blunder"
    g.headers["Date"] = (row.get("end_time_utc", "")[:10] or "????-??-??").replace("-", ".")
    g.headers["Annotator"] = row.get("game_url", "")  # Chess.com provenance lives here
    g.headers["White"] = "You" if row.get("my_color") == "white" else row.get("opponent", "Opponent")
    g.headers["Black"] = row.get("opponent", "Opponent") if row.get("my_color") == "white" else "You"
    g.headers["Result"] = "*"

    played = chess.Move.from_uci(played_uci)
    node_main = g.add_main_variation(played)
    node_main.comment = f"Blunder. cp_loss={row.get('cp_loss','')} wp_swing={row.get('wp_swing','')}"

    if best_uci:
        bestm = chess.Move.from_uci(best_uci)
        var = g.add_variation(bestm)
        var.comment = "Best move"

    buf = io.StringIO()
    g.accept(chess.pgn.FileExporter(buf))
    return buf.getvalue().strip() + "\n"


def upload_top_blunders(
    study_id: str,
    token: str,
    blunders_csv: str,
    metric: str,
    limit: int,
    sleep_s: float,
    dry_run: bool,
):
    rows = []
    with open(blunders_csv, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "played_move_uci" in r and r.get("fen_before"):
                rows.append(r)

    if not rows:
        print("No rows found in blunders.csv")
        return

    by_game = defaultdict(list)
    for r in rows:
        by_game[r["game_url"]].append(r)

    picked = []
    for _, items in by_game.items():
        key = (lambda x: parse_float(x.get("wp_swing", "0"))) if metric == "wp_swing" else (
            lambda x: parse_float(x.get("cp_loss", "0"))
        )
        picked.append(max(items, key=key))

    picked.sort(key=(lambda x: parse_float(x.get(metric, "0"))), reverse=True)
    if limit and len(picked) > limit:
        picked = picked[:limit]

    print(f"Selected {len(picked)} biggest blunders ({metric}) across {len(by_game)} games.")

    for i, r in enumerate(picked, 1):
        opp = r.get("opponent", "")
        metric_val = r.get(metric, "")
        me_color = (r.get("my_color", "") or "").lower()
        suffix = "as White" if me_color == "white" else "as Black" if me_color == "black" else "as ?"
        name = f"{i:02d} Biggest blunder vs {opp} ({metric_val}) — {suffix}"

        pgn_text = build_puzzle_pgn_from_row(r)

        if dry_run:
            print(f"[DRY] {name} :: {r.get('game_url','')}")
            continue

        resp = import_chapter(study_id, token, pgn_text, name)
        print(f"[{i}] uploaded: {name}")
        print(resp.strip()[:200])
        time.sleep(sleep_s)


def main():
    ap = argparse.ArgumentParser("lichess")
    ap.add_argument("--study", default=env_default("LICHESS_STUDY_ID"), help="Study ID (or set LICHESS_STUDY_ID)")
    ap.add_argument("--token", default=env_default("LICHESS_TOKEN"), help="Token (or set LICHESS_TOKEN)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upload-top", help="Upload biggest blunder per game from blunders.csv")
    p_up.add_argument("--blunders-csv", default="data/blunders.csv")
    p_up.add_argument("--metric", choices=["wp_swing", "cp_loss"], default="wp_swing")
    p_up.add_argument("--limit", type=int, default=0)
    p_up.add_argument("--sleep", type=float, default=0.6)
    p_up.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()

    if not args.study:
        raise SystemExit("Missing study id. Use --study or set LICHESS_STUDY_ID.")
    if not args.token:
        raise SystemExit("Missing token. Use --token or set LICHESS_TOKEN (needs study:write).")

    if args.cmd == "upload-top":
        upload_top_blunders(args.study, args.token, args.blunders_csv, args.metric, args.limit, args.sleep, args.dry_run)


if __name__ == "__main__":
    main()
