#!/usr/bin/env python3
"""
Unified CLI wrapper for:
- Chess.com analysis (chesscom.py)
- Lichess study upload (lichess.py)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List
from pathlib import Path

def _load_dotenv() -> None:
    """
    Best-effort .env loader.
    Search order (first found wins per-variable via os.environ.setdefault):
      1) current working directory: ./.env
      2) script directory: <dir_of_this_file>/.env
      3) user config: ~/.config/chess-study/.env
    """
    candidates = []

    # 1) CWD
    candidates.append(Path(os.getcwd()) / ".env")

    # 2) script dir (works when running from repo root OR installed executable)
    try:
        candidates.append(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass

    # 3) user config
    home = os.path.expanduser("~")
    candidates.append(Path(home) / ".config" / "chess-study" / ".env")

    for p in candidates:
        try:
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)
        except Exception:
            # best-effort; never hard fail
            continue


def _ensure_data_dir(data_dir: str) -> str:
    p = Path(data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _run_module_main(module_name: str, argv: List[str]) -> int:
    """
    Import a module and run its `main()` as if called from CLI.

    Assumes the module exposes a top-level main().
    """
    mod = __import__(module_name, fromlist=["main"])
    if not hasattr(mod, "main"):
        raise SystemExit(f"Module {module_name} has no main()")
    old_argv = sys.argv
    try:
        sys.argv = [module_name] + argv
        mod.main()
        return 0
    finally:
        sys.argv = old_argv


def _require_username(u: str) -> str:
    u = (u or "").strip()
    if not u:
        raise SystemExit("Missing Chess.com username. Pass it as an argument or set env CHESSCOM_USER.")
    return u


def main() -> None:
    _load_dotenv()
    ap = argparse.ArgumentParser(
        prog="chess_cli",
        description="One CLI for Chess.com analysis + Lichess study publishing.",
    )
    ap.add_argument(
        "--data-dir",
        default=os.getenv("DATA_DIR", "data"),
        help="Directory for generated files (default: data, or env DATA_DIR)",
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    # ---- analyze ----
    p_an = sub.add_parser("analyze", help="Fetch games from Chess.com, run Stockfish, write data/*")
    p_an.add_argument("username", nargs="?", default=os.getenv("CHESSCOM_USER", ""), help="Chess.com username (or env CHESSCOM_USER)")
    p_an.add_argument("--max-games", type=int, default=50)
    p_an.add_argument("--depth", type=int, default=12)
    p_an.add_argument("--stockfish", default="stockfish")
    p_an.add_argument("--user-agent", default="my-chess-analysis/0.1 (contact: you@example.com)")

    # optional overrides (rarely needed)
    p_an.add_argument("--out", default="summary.csv")
    p_an.add_argument("--moves-out", default="moves.csv")
    p_an.add_argument("--blunders-csv", default="blunders.csv")
    p_an.add_argument("--blunders-pgn", default="blunders.pgn")

    # thresholds
    p_an.add_argument("--inacc-cp", type=int, default=50)
    p_an.add_argument("--mistake-cp", type=int, default=100)
    p_an.add_argument("--blunder-cp", type=int, default=200)

    # ---- upload-top ----
    p_up = sub.add_parser("upload-top", help="Upload biggest blunder per game to Lichess Study as chapters")
    p_up.add_argument("--study", default=os.getenv("LICHESS_STUDY_ID", ""), help="Study ID (or env LICHESS_STUDY_ID)")
    p_up.add_argument("--token", default=os.getenv("LICHESS_TOKEN", ""), help="Token (or env LICHESS_TOKEN)")
    p_up.add_argument("--blunders-csv", default="", help="Path to blunders.csv (default: <data-dir>/blunders.csv)")
    p_up.add_argument("--metric", choices=["wp_loss", "cp_loss", "wp_swing"], default="wp_loss")
    p_up.add_argument("--limit", type=int, default=0)
    p_up.add_argument("--sleep", type=float, default=0.6)
    p_up.add_argument("--dry-run", action="store_true")

    # ---- sync (analyze -> upload-top) ----
    p_sy = sub.add_parser("sync", help="Run analyze, then upload-top")
    p_sy.add_argument("username", nargs="?", default=os.getenv("CHESSCOM_USER", ""), help="Chess.com username (or env CHESSCOM_USER)")
    p_sy.add_argument("--max-games", type=int, default=50)
    p_sy.add_argument("--depth", type=int, default=12)
    p_sy.add_argument("--stockfish", default="stockfish")
    p_sy.add_argument("--user-agent", default="my-chess-analysis/0.1 (contact: you@example.com)")
    p_sy.add_argument("--study", default=os.getenv("LICHESS_STUDY_ID", ""), help="Study ID (or env LICHESS_STUDY_ID)")
    p_sy.add_argument("--token", default=os.getenv("LICHESS_TOKEN", ""), help="Token (or env LICHESS_TOKEN)")
    p_sy.add_argument("--metric", choices=["wp_loss", "cp_loss", "wp_swing"], default="wp_loss")
    p_sy.add_argument("--limit", type=int, default=0)

    args = ap.parse_args()
    data_dir = _ensure_data_dir(args.data_dir)

    if args.cmd == "analyze":
        args.username = _require_username(args.username)

        argv = [
            args.username,
            "--data-dir",
            data_dir,
            "--max-games",
            str(args.max_games),
            "--depth",
            str(args.depth),
            "--stockfish",
            args.stockfish,
            "--user-agent",
            args.user_agent,
            "--out",
            args.out,
            "--moves-out",
            args.moves_out,
            "--blunders-csv",
            args.blunders_csv,
            "--blunders-pgn",
            args.blunders_pgn,
            "--inacc-cp",
            str(args.inacc_cp),
            "--mistake-cp",
            str(args.mistake_cp),
            "--blunder-cp",
            str(args.blunder_cp),
        ]
        raise SystemExit(_run_module_main("chesscom", argv))

    if args.cmd == "upload-top":
        if not args.study:
            raise SystemExit("Missing --study (or env LICHESS_STUDY_ID).")
        if not args.token:
            raise SystemExit("Missing --token (or env LICHESS_TOKEN).")

        blunders_csv = args.blunders_csv or str(Path(data_dir) / "blunders.csv")
        argv = [
            "--study",
            args.study,
            "--token",
            args.token,
            "upload-top",
            "--blunders-csv",
            blunders_csv,
            "--metric",
            args.metric,
            "--sleep",
            str(args.sleep),
        ]
        if args.limit:
            argv += ["--limit", str(args.limit)]
        if args.dry_run:
            argv += ["--dry-run"]
        raise SystemExit(_run_module_main("lichess", argv))

    if args.cmd == "sync":
        args.username = _require_username(args.username)

        if not args.study:
            raise SystemExit("Missing --study (or env LICHESS_STUDY_ID).")
        if not args.token:
            raise SystemExit("Missing --token (or env LICHESS_TOKEN).")

        # 1) analyze
        _run_module_main(
            "chesscom",
            [
                args.username,
                "--data-dir",
                data_dir,
                "--max-games",
                str(args.max_games),
                "--depth",
                str(args.depth),
                "--stockfish",
                args.stockfish,
                "--user-agent",
                args.user_agent,
            ],
        )

        # 2) upload-top
        blunders_csv = str(Path(data_dir) / "blunders.csv")
        up_argv = [
            "--study",
            args.study,
            "--token",
            args.token,
            "upload-top",
            "--blunders-csv",
            blunders_csv,
            "--metric",
            args.metric,
        ]
        if args.limit:
            up_argv += ["--limit", str(args.limit)]
        _run_module_main("lichess", up_argv)
        raise SystemExit(0)


if __name__ == "__main__":
    main()
