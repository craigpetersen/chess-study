#!/usr/bin/env python3
import argparse
import csv
import io
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests
import chess
import chess.pgn
import chess.engine

API_BASE = "https://api.chess.com/pub"


def http_get_json(url: str, user_agent: str) -> dict:
    r = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    r.raise_for_status()
    return r.json()


def iter_recent_games(username: str, max_games: int, user_agent: str):
    """
    Yields game JSON objects newest-first from monthly archives.
    """
    archives_url = f"{API_BASE}/player/{username}/games/archives"
    archives = http_get_json(archives_url, user_agent).get("archives", [])
    for month_url in reversed(archives):
        month = http_get_json(month_url, user_agent)
        games = month.get("games", [])
        games.sort(key=lambda g: g.get("end_time", 0), reverse=True)
        for g in games:
            yield g
            max_games -= 1
            if max_games <= 0:
                return


def pick_my_color(game: dict, username: str) -> chess.Color | None:
    w = (game.get("white") or {}).get("username", "").lower()
    b = (game.get("black") or {}).get("username", "").lower()
    u = username.lower()
    if w == u:
        return chess.WHITE
    if b == u:
        return chess.BLACK
    return None


def _first_info(info):
    return info[0] if isinstance(info, list) else info


def score_white(info):
    """
    Returns a dict describing the engine eval from White POV.
    - kind: "cp" or "mate"
    - cp: int (if kind=="cp") else None
    - mate: int (mate in N; sign from White POV) if kind=="mate" else None
    """
    info = _first_info(info)
    s = info["score"].pov(chess.WHITE)
    mate = s.mate()
    if mate is not None:
        return {"kind": "mate", "cp": None, "mate": int(mate)}
    cp = s.score(mate_score=100000)
    return {"kind": "cp", "cp": int(cp), "mate": None}


def mate_to_pseudo_cp(mate: int) -> int:
    """
    Convert mate-in-N to a bounded cp-like value for win-prob mapping.
    Positive mate means White is mating; negative means White is getting mated.
    """
    sign = 1 if mate > 0 else -1
    n = abs(mate)
    return sign * max(6000, 10000 - 300 * min(n, 10))


def win_prob_from_cp(cp: int) -> float:
    """
    Rough mapping from centipawns (White POV) to win probability for White.
    Not Chess.com's exact bar, but stable for swing tracking.
    """
    return 1.0 / (1.0 + math.pow(10.0, -cp / 400.0))


def win_prob_from_eval(eval_obj) -> float:
    if eval_obj["kind"] == "mate":
        cp = mate_to_pseudo_cp(eval_obj["mate"])
    else:
        cp = eval_obj["cp"]
    return win_prob_from_cp(int(cp))


def safe_san(board: chess.Board, move: chess.Move) -> str:
    """
    SAN can fail if we’re in a weird parsing edge; fall back to UCI.
    """
    try:
        return board.san(move)
    except Exception:
        return move.uci()


def analyze_game_pgn(
    pgn_text: str,
    my_color: chess.Color,
    engine: chess.engine.SimpleEngine,
    depth: int,
    blunder_cp: int,
    mistake_cp: int,
    inacc_cp: int,
    game_url: str,
    end_time_utc: str,
    opponent: str,
    my_color_str: str,
) -> tuple[dict, list[dict], list[dict], list[chess.pgn.Game]]:
    """
    Returns:
      - summary stats for *your moves only*
      - move_rows: one row per ply (for graphing eval bar swing)
      - blunder_rows: one row per blunder (with FEN before/after + best move)
      - blunder_games: PGN Games for each blunder (FEN setup + mainline + variation)
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return (
            {
                "plies_analyzed": 0,
                "inaccuracies": 0,
                "mistakes": 0,
                "blunders": 0,
                "max_cp_loss": 0,
                "max_wp_swing": 0.0,
            },
            [],
            [],
            [],
        )

    board = game.board()

    inaccuracies = mistakes = blunders = 0
    max_cp_loss = 0
    max_wp_swing = 0.0
    plies_analyzed = 0

    move_rows: list[dict] = []
    blunder_rows: list[dict] = []
    blunder_games: list[chess.pgn.Game] = []

    ply = 0
    for move in game.mainline_moves():
        ply += 1
        side_to_move = board.turn
        is_my_move = (side_to_move == my_color)

        fen_before = board.fen()
        move_number = board.fullmove_number

        info_before = engine.analyse(board, chess.engine.Limit(depth=depth))
        eval_before = score_white(info_before)
        wp_before = win_prob_from_eval(eval_before)

        san_played = safe_san(board, move)
        played_uci = move.uci()

        best_move_uci = ""
        best_move_san = ""
        if is_my_move:
            try:
                best = engine.play(board, chess.engine.Limit(depth=depth))
                if best.move is not None:
                    best_move_uci = best.move.uci()
                    best_move_san = safe_san(board, best.move)
            except Exception:
                pass

        board.push(move)

        fen_after = board.fen()

        info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
        eval_after = score_white(info_after)
        wp_after = win_prob_from_eval(eval_after)

        wp_swing = abs(wp_after - wp_before)
        max_wp_swing = max(max_wp_swing, wp_swing)

        cp_loss = ""
        label = ""

        if is_my_move:
            plies_analyzed += 1

            if eval_before["kind"] == "cp" and eval_after["kind"] == "cp":
                cp_best_white = eval_before["cp"]
                cp_after_white = eval_after["cp"]

                if my_color == chess.WHITE:
                    loss = cp_best_white - cp_after_white
                else:
                    loss = cp_after_white - cp_best_white

                if loss < 0:
                    loss = 0

                cp_loss = int(loss)
                max_cp_loss = max(max_cp_loss, int(loss))

                if loss >= blunder_cp:
                    blunders += 1
                    label = "blunder"
                elif loss >= mistake_cp:
                    mistakes += 1
                    label = "mistake"
                elif loss >= inacc_cp:
                    inaccuracies += 1
                    label = "inaccuracy"

        move_rows.append(
            {
                "game_url": game_url,
                "end_time_utc": end_time_utc,
                "opponent": opponent,
                "my_color": my_color_str,
                "ply": ply,
                "move_number": move_number,
                "move_san": san_played,
                "move_uci": played_uci,
                "side_to_move": "white" if side_to_move == chess.WHITE else "black",
                "is_my_move": int(is_my_move),
                "eval_before_kind": eval_before["kind"],
                "eval_before_cp": eval_before["cp"] if eval_before["kind"] == "cp" else "",
                "eval_before_mate": eval_before["mate"] if eval_before["kind"] == "mate" else "",
                "eval_after_kind": eval_after["kind"],
                "eval_after_cp": eval_after["cp"] if eval_after["kind"] == "cp" else "",
                "eval_after_mate": eval_after["mate"] if eval_after["kind"] == "mate" else "",
                "wp_before": f"{wp_before:.6f}",
                "wp_after": f"{wp_after:.6f}",
                "wp_swing": f"{wp_swing:.6f}",
                "cp_loss": cp_loss,
                "label": label,
                "fen_before": fen_before,
                "fen_after": fen_after,
            }
        )

        if is_my_move and label == "blunder":
            blunder_rows.append(
                {
                    "game_url": game_url,
                    "end_time_utc": end_time_utc,
                    "opponent": opponent,
                    "my_color": my_color_str,
                    "ply": ply,
                    "move_number": move_number,
                    "played_move_san": san_played,
                    "played_move_uci": played_uci,
                    "best_move_san": best_move_san,
                    "best_move_uci": best_move_uci,
                    "eval_before_kind": eval_before["kind"],
                    "eval_before_cp": eval_before["cp"] if eval_before["kind"] == "cp" else "",
                    "eval_before_mate": eval_before["mate"] if eval_before["kind"] == "mate" else "",
                    "eval_after_kind": eval_after["kind"],
                    "eval_after_cp": eval_after["cp"] if eval_after["kind"] == "cp" else "",
                    "eval_after_mate": eval_after["mate"] if eval_after["kind"] == "mate" else "",
                    "wp_before": f"{wp_before:.6f}",
                    "wp_after": f"{wp_after:.6f}",
                    "wp_swing": f"{wp_swing:.6f}",
                    "cp_loss": cp_loss,
                    "fen_before": fen_before,
                    "fen_after": fen_after,
                }
            )

            try:
                puzzle_board = chess.Board(fen_before)
                pgn_game = chess.pgn.Game()
                pgn_game.setup(puzzle_board)

                pgn_game.headers["Event"] = "Blunder Moment"
                pgn_game.headers["Site"] = ""
                pgn_game.headers["Annotator"] = game_url

                try:
                    dt = datetime.fromisoformat(end_time_utc.replace("Z", "+00:00"))
                    pgn_game.headers["Date"] = dt.strftime("%Y.%m.%d")
                except Exception:
                    pgn_game.headers["Date"] = "????.??.??"

                pgn_game.headers["White"] = "You" if my_color == chess.WHITE else opponent
                pgn_game.headers["Black"] = opponent if my_color == chess.WHITE else "You"
                pgn_game.headers["Result"] = "*"

                played = chess.Move.from_uci(played_uci)
                main = pgn_game.add_main_variation(played)
                main.comment = f"Blunder. cp_loss={cp_loss} wp_swing={wp_swing:.3f}"

                if best_move_uci:
                    bestm = chess.Move.from_uci(best_move_uci)
                    var = pgn_game.add_variation(bestm)
                    var.comment = "Best move"

                blunder_games.append(pgn_game)
            except Exception:
                pass

    summary = {
        "plies_analyzed": plies_analyzed,
        "inaccuracies": inaccuracies,
        "mistakes": mistakes,
        "blunders": blunders,
        "max_cp_loss": max_cp_loss,
        "max_wp_swing": max_wp_swing,
    }
    return summary, move_rows, blunder_rows, blunder_games


def _resolve_out(data_dir: Path, name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.parent == Path("."):
        return data_dir / p.name
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username", help="Chess.com username")
    ap.add_argument("--max-games", type=int, default=50)
    ap.add_argument("--stockfish", default="stockfish", help="Path to stockfish binary")
    ap.add_argument("--depth", type=int, default=12)

    ap.add_argument("--data-dir", default="data", help="Directory for generated files (default: data)")

    ap.add_argument("--out", default="summary.csv")
    ap.add_argument("--moves-out", default="moves.csv")
    ap.add_argument("--blunders-csv", default="blunders.csv")
    ap.add_argument("--blunders-pgn", default="blunders.pgn")

    ap.add_argument("--inacc-cp", type=int, default=50)
    ap.add_argument("--mistake-cp", type=int, default=100)
    ap.add_argument("--blunder-cp", type=int, default=200)

    ap.add_argument(
        "--user-agent",
        default="my-chess-analysis/0.1 (contact: you@example.com)",
        help="Chess.com recommends a UA with contact info",
    )
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    out_path = _resolve_out(data_dir, args.out)
    moves_path = _resolve_out(data_dir, args.moves_out)
    blunders_csv_path = _resolve_out(data_dir, args.blunders_csv)
    blunders_pgn_path = _resolve_out(data_dir, args.blunders_pgn)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    moves_path.parent.mkdir(parents=True, exist_ok=True)
    blunders_csv_path.parent.mkdir(parents=True, exist_ok=True)
    blunders_pgn_path.parent.mkdir(parents=True, exist_ok=True)

    if args.stockfish == "stockfish" and shutil.which("stockfish") is None:
        raise SystemExit(
            "Stockfish not found on PATH.\n"
            "On WSL: sudo apt-get install -y stockfish\n"
            "Or run with: --stockfish /path/to/stockfish"
        )

    engine = chess.engine.SimpleEngine.popen_uci(args.stockfish)

    summary_rows = []
    all_move_rows: list[dict] = []
    all_blunder_rows: list[dict] = []
    all_blunder_games: list[chess.pgn.Game] = []

    try:
        for g in iter_recent_games(args.username, args.max_games, args.user_agent):
            my_color = pick_my_color(g, args.username)
            if my_color is None:
                continue

            pgn = g.get("pgn") or ""
            if not pgn.strip():
                continue

            end_time = g.get("end_time")
            end_dt = (
                datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()
                if end_time
                else ""
            )

            white = g.get("white", {}) or {}
            black = g.get("black", {}) or {}
            my_color_str = "white" if my_color == chess.WHITE else "black"

            opponent = (black if my_color == chess.WHITE else white).get("username", "")
            time_class = g.get("time_class", "")
            rules = g.get("rules", "")
            url = g.get("url", "")

            my_rating = (white if my_color == chess.WHITE else black).get("rating", "")
            my_result = (white if my_color == chess.WHITE else black).get("result", "")

            accuracies = g.get("accuracies") or {}
            my_acc = accuracies.get("white" if my_color == chess.WHITE else "black", "")

            stats, move_rows, blunder_rows, blunder_games = analyze_game_pgn(
                pgn_text=pgn,
                my_color=my_color,
                engine=engine,
                depth=args.depth,
                blunder_cp=args.blunder_cp,
                mistake_cp=args.mistake_cp,
                inacc_cp=args.inacc_cp,
                game_url=url,
                end_time_utc=end_dt,
                opponent=opponent,
                my_color_str=my_color_str,
            )

            all_move_rows.extend(move_rows)
            all_blunder_rows.extend(blunder_rows)
            all_blunder_games.extend(blunder_games)

            summary_rows.append(
                {
                    "end_time_utc": end_dt,
                    "time_class": time_class,
                    "rules": rules,
                    "color": my_color_str,
                    "opponent": opponent,
                    "my_rating_after": my_rating,
                    "my_result_code": my_result,
                    "my_accuracy": my_acc,
                    "plies_analyzed": stats["plies_analyzed"],
                    "inaccuracies": stats["inaccuracies"],
                    "mistakes": stats["mistakes"],
                    "blunders": stats["blunders"],
                    "max_cp_loss": stats["max_cp_loss"],
                    "max_wp_swing": f'{stats["max_wp_swing"]:.4f}',
                    "game_url": url,
                }
            )
    finally:
        engine.quit()

    summary_fields = [
        "end_time_utc",
        "time_class",
        "rules",
        "color",
        "opponent",
        "my_rating_after",
        "my_result_code",
        "my_accuracy",
        "plies_analyzed",
        "inaccuracies",
        "mistakes",
        "blunders",
        "max_cp_loss",
        "max_wp_swing",
        "game_url",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)

    move_fields = [
        "game_url",
        "end_time_utc",
        "opponent",
        "my_color",
        "ply",
        "move_number",
        "move_san",
        "move_uci",
        "side_to_move",
        "is_my_move",
        "eval_before_kind",
        "eval_before_cp",
        "eval_before_mate",
        "eval_after_kind",
        "eval_after_cp",
        "eval_after_mate",
        "wp_before",
        "wp_after",
        "wp_swing",
        "cp_loss",
        "label",
        "fen_before",
        "fen_after",
    ]
    with open(moves_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=move_fields)
        w.writeheader()
        w.writerows(all_move_rows)

    blunder_fields = [
        "game_url",
        "end_time_utc",
        "opponent",
        "my_color",
        "ply",
        "move_number",
        "played_move_san",
        "played_move_uci",
        "best_move_san",
        "best_move_uci",
        "eval_before_kind",
        "eval_before_cp",
        "eval_before_mate",
        "eval_after_kind",
        "eval_after_cp",
        "eval_after_mate",
        "wp_before",
        "wp_after",
        "wp_swing",
        "cp_loss",
        "fen_before",
        "fen_after",
    ]
    with open(blunders_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=blunder_fields)
        w.writeheader()
        w.writerows(all_blunder_rows)

    with open(blunders_pgn_path, "w", encoding="utf-8") as f:
        exporter = chess.pgn.FileExporter(f)
        for g in all_blunder_games:
            g.accept(exporter)
            f.write("\n\n")

    print(f"Wrote {len(summary_rows)} games to {out_path}")
    print(f"Wrote {len(all_move_rows)} move rows to {moves_path}")
    print(f"Wrote {len(all_blunder_rows)} blunders to {blunders_csv_path}")
    print(f"Wrote {len(all_blunder_games)} PGN puzzles to {blunders_pgn_path}")


if __name__ == "__main__":
    main()
