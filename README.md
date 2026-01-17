# Chess.com → Stockfish → Lichess Study (Blunder Chapters)

Pull your recent Chess.com games, run Stockfish locally to detect blunders/swingy moments, then publish the **biggest blunder per game** into a Lichess Study as “puzzle-like” chapters (position before the blunder, your move, and the engine best move as a variation).

This project is designed to work well on **Windows + WSL2** (recommended), and also on Linux/macOS.


## Files in this repo

- `chess_cli.py` — **single entrypoint CLI** (analyze / upload / sync)
- `chesscom.py` — Chess.com fetch + Stockfish analysis (writes `./data/*`)
- `lichess.py` — Lichess Study uploader (uploads chapters from `./data/blunders.csv`)


## What it produces

By default, generated artifacts go into `./data/`:

- `data/summary.csv` — per-game summary (includes Chess.com accuracy if provided)
- `data/moves.csv` — per-move timeline (FEN before/after, eval kind, win-prob swing) suitable for graphing
- `data/blunders.csv` — only your “blunder” moves with FEN before/after + engine best move
- `data/blunders.pgn` — one PGN “chapter” per blunder (start from FEN; mainline is your move; variation is best move)

Publishing to Lichess uses `data/blunders.csv` and uploads **one chapter per game** (the biggest blunder for that game).


## Prerequisites

### 1) Python + uv
- Python 3.11+
- `uv` installed

Install uv:
- macOS/Linux:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- Windows (PowerShell):
  ```powershell
  winget install --id Astral.uv -e
  ```

Verify:
```bash
uv --version
```

### 2) Stockfish engine
Stockfish is a native executable (not a pip package). Install it on the same OS environment where you run Python.

**Recommended (WSL2 Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install -y stockfish
which stockfish
```

**macOS (Homebrew):**
```bash
brew install stockfish
```


## Setup

From the project root:

1) Create a virtual environment:
```bash
uv python install 3.11
uv venv --python 3.11
```

2) Install dependencies:
```bash
uv pip install requests python-chess
```


## Configuration (environment variables)

Use environment variables for portability.

Required for Lichess upload:
- `LICHESS_TOKEN` — must include `study:write`
- `LICHESS_STUDY_ID` — the 8-char ID from your Study URL, e.g. `https://lichess.org/study/<ID>`

Optional convenience:
- `CHESSCOM_USER` — your Chess.com username (used as the default for `analyze` / `sync`)

Example `.env` (create locally; do not commit tokens):
```bash
CHESSCOM_USER=crymeasong
LICHESS_STUDY_ID=Z1HaMxbk
LICHESS_TOKEN=__PASTE_TOKEN_HERE__
```

Load it (WSL/Linux/macOS):
```bash
set -a
source .env
set +a
```


## Quick start

### Analyze your last 10 games (writes to ./data)
```bash
uv run python chess_cli.py analyze --max-games 10 --depth 10
```

(You can still pass a username explicitly if you prefer)
```bash
uv run python chess_cli.py analyze crymeasong --max-games 10 --depth 10
```

### Upload biggest blunder per game to your Lichess Study
```bash
uv run python chess_cli.py upload-top --metric wp_swing --limit 10
```

### One command: analyze + upload
```bash
uv run python chess_cli.py sync --max-games 10 --depth 10 --metric wp_swing --limit 10
```


## Useful examples

### Increase analysis depth (slower but usually better signal)
```bash
uv run python chess_cli.py analyze --max-games 10 --depth 12
```

### Use a specific Stockfish binary (if not on PATH)
```bash
uv run python chess_cli.py analyze --stockfish /usr/games/stockfish --max-games 10 --depth 10
```

### Dry-run upload (show what would be uploaded without modifying your study)
```bash
uv run python chess_cli.py upload-top --metric wp_swing --limit 5 --dry-run
```

### Upload by centipawn loss instead of swing
```bash
uv run python chess_cli.py upload-top --metric cp_loss --limit 10
```


## Notes

- `chess_cli.py analyze` and `sync` default the username from `CHESSCOM_USER`.
- Upload does **not** delete or “clear” existing study chapters. (Keeping this simple avoids needing to resolve chapter IDs.)
- The uploader leaves the PGN `[Site]` header empty so Lichess can set it to the chapter URL. Chess.com provenance is stored in `[Annotator]` instead.


## Troubleshooting

### Stockfish not found
If you see:
`FileNotFoundError: No such file or directory: 'stockfish'`

Install Stockfish in your environment:
```bash
sudo apt-get install -y stockfish
```

Or pass an explicit path:
```bash
uv run python chess_cli.py analyze --stockfish /usr/games/stockfish --max-games 10 --depth 10
```

### Lichess upload returns HTTP 400
Most commonly:
- Token missing `study:write`
- Wrong Study ID
- Study is not accessible to the token user

Try uploading a minimal PGN chapter first, then re-run.


## Security notes
- Never commit `LICHESS_TOKEN` to git.
- Prefer `.env` in `.gitignore` and a committed `.env.example` template.
