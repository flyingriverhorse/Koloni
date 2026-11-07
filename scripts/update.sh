#!/usr/bin/env bash
# Updates this checkout of KOLONİ in one go (0.1.0-guncelleme): the database backed up, the
# code pulled, the Python packages and the page rebuilt. The database itself is migrated when
# KOLONİ next starts. Stop KOLONİ first - the script refuses while something answers on its
# port. Same steps as scripts/update.ps1. --dry-run prints them and runs nothing.
# shortcut: only KOLONI_PORT is looked at - a KOLONİ on another port, or anything else run
# from this .venv (pytest), still holds its files; check those by hand until it is seen.
# All in one function, read whole before it runs: `git pull` may rewrite this very file.
main() {
  cd "$(dirname "$0")/.." || exit 1
  local dry=0
  [ "${1:-}" = "--dry-run" ] && dry=1
  local py=.venv/bin/python port="${KOLONI_PORT:-8790}" runtime="${KOLONI_RUNTIME_ROOT:-runtime}"
  local db="$runtime/data/koloni.db"
  local backup
  backup="$runtime/data/backups/koloni-$(date +%Y%m%dT%H%M%S).db"

  stop() { echo "update: $1 - stopped, nothing after it ran."; exit 1; }
  step() {
    local name=$1; shift
    echo "== $name"
    [ "$dry" = 1 ] && return
    "$@" || stop "$name failed"
  }

  # B-340: a folder git does not know (a copy made with git archive) cannot be pulled - said in
  # words before git says "fatal" on every step after.
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || stop "this folder is not a git checkout; update it with git first (git clone)"

  # A worktree's .venv / node_modules lead to the main checkout's: uv and npm would rewrite those.
  if [ -L .venv ] || [ -L frontend/node_modules ] || [ "$(git rev-parse --path-format=absolute       --git-dir 2>/dev/null)" != "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ]; then
    stop "this is a linked working copy; run the update in the main checkout"
  fi

  if [ "$dry" = 1 ]; then
    echo "update (dry run): these steps would run, nothing is run now."
    echo "== refuse if tracked files have changes (git status, runtime/ left out)"
    echo "== refuse while KOLONİ answers on 127.0.0.1:$port"
  else
    # Untracked files do not stop a fast-forward; changed tracked ones would be in its way.
    local changed
    changed=$(git status --porcelain --untracked-files=no -- . ':(exclude)runtime') \
      || stop "git status failed (is this a git checkout?)"
    if [ -n "$changed" ]; then
      echo "$changed"
      stop "tracked files have uncommitted changes: commit or stash them first"
    fi
    # (bash's own /dev/tcp: a refused connection to this machine answers at once.)
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      stop "something answers on 127.0.0.1:$port - stop KOLONİ first (Ctrl+C in its window)"
    fi
  fi

  local backed_up=""
  if [ "$dry" = 1 ] || [ -f "$db" ]; then
    # SQLite's own online backup: a consistent copy, the WAL's pages too - never a plain copy.
    back_up() {
      mkdir -p "$(dirname "$backup")" && "$py" -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' "$db" "$backup"
    }
    step "back up the database to $backup" back_up
    backed_up=$backup
  fi
  # The guide (/guide/) where Zensical is installed: looked at before the sync, which takes it
  # away (it is the optional docs extra, not in the lock), then put back and the guide rebuilt.
  local guide=0
  { [ "$dry" = 1 ] || [ -x .venv/bin/zensical ]; } && guide=1
  step "git pull --ff-only" git pull --ff-only
  step "uv pip sync requirements-dev.lock" uv pip sync --python "$py" requirements-dev.lock
  step "uv pip install --no-deps -e ." uv pip install --python "$py" --no-deps -e .
  step "npm --prefix frontend ci" npm --prefix frontend ci
  step "npm --prefix frontend run build" npm --prefix frontend run build
  if [ "$guide" = 1 ]; then
    # (KOLONİ is updated by now: a guide that is not rebuilt is said, and the update ends as usual.)
    echo "== uv pip install -r pyproject.toml --extra docs, then zensical build (the guide at /guide/; a failure only warns)"
    if [ "$dry" != 1 ]; then
      { uv pip install --python "$py" -r pyproject.toml --extra docs && .venv/bin/zensical build; } \
        || echo "update: warning - the guide was not rebuilt (see above); KOLONİ itself is updated."
    fi
  fi

  [ "$dry" = 1 ] && exit 0
  local kept="backup: $backed_up"
  [ -n "$backed_up" ] || kept="no database yet, nothing backed up"
  echo "Updated to $(git rev-parse --short HEAD). Restart KOLONİ; the database is migrated when it starts ($kept)."
  exit 0
}
main "$@"
