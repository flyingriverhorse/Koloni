# Install

KOLONİ runs from its source folder. You install a few tools once, then build and start it.

## What you need

- **Python 3.12, 3.13 or 3.14**, and [uv](https://docs.astral.sh/uv/), which installs KOLONİ's
  Python packages.
- **Node.js 24**, to build the page.
- **Git** on your `PATH`. KOLONİ uses it to merge an agent's changes with yours and to commit when
  you ask.
- **At least one model**, any of:
    - a model server that speaks the OpenAI API and supports tool calls, for example llama.cpp's
      `llama-server` started with `--jinja`, or a hosted API. Other OpenAI-compatible servers (Ollama,
      …) should work but are not tested;
    - an Anthropic API key;
    - a CLI installed and signed in **in your own terminal**. KOLONİ never signs in for you.

| CLI | Command | Sign in |
|---|---|---|
| Claude Code | `claude` | `claude auth login` |
| Codex | `codex` | `codex login` |
| GitHub Copilot CLI | `copilot` | `gh auth login`, or a GitHub token, or a model server of your own |
| Qoder | `qodercli` | Qoder's own sign-in |
| agy | `agy` | agy's own sign-in |

Using a CLI through KOLONİ counts against your plan with that vendor.

- **Docker** is optional: to run agents' commands in a container, or to run KOLONİ itself in one.

### How well each system is tested

| System | State |
|---|---|
| Windows | Used and tested every day, with the real CLIs. |
| Linux | The automatic tests run on every change. A clean install and daily use are less tested. There are no desktop notifications. |
| macOS | Not tested yet. |
| Docker | The image has been built and started; it is the newest and least tested way to run KOLONİ. |

## Install and start

Get KOLONİ's source folder, open a terminal in it, and run:

=== "Windows (PowerShell)"

    ```powershell
    uv venv .venv --python 3.12
    uv pip install --python .venv/Scripts/python.exe -r requirements-dev.lock
    uv pip install --python .venv/Scripts/python.exe --no-deps -e .
    npm --prefix frontend ci
    npm --prefix frontend run build
    .venv/Scripts/python.exe -m app.main
    ```

=== "macOS and Linux"

    ```bash
    uv venv .venv --python 3.12
    uv pip install --python .venv/bin/python -r requirements-dev.lock
    uv pip install --python .venv/bin/python --no-deps -e .
    npm --prefix frontend ci
    npm --prefix frontend run build
    .venv/bin/python -m app.main
    ```

The window prints one line:

```
KOLONİ is open at http://127.0.0.1:8790/#key=…
```

Started from a terminal, KOLONİ also opens the page in your browser. Set `KOLONI_OPEN_BROWSER=0`
to stop that.

The part after `#key=` is the **page key**. Every request from the page must carry it, so a
program on your machine (such as a command an agent runs) cannot approve its own cards or change
your settings. Each start makes a new key. An old tab or bookmark shows
"Open KOLONİ from the link in its window"; paste the new link there.

Stop KOLONİ with Ctrl+C in its window. A model server you started from the Models page stops with
it.

If you skip the build step, KOLONİ serves only its API and there is no page to open.

### This guide inside KOLONİ

KOLONİ serves this guide at `http://127.0.0.1:8790/guide/`, and the **Learn more →** links in its
hints open it there. It works offline and matches the version you run. Build it once with the
optional Zensical package:

=== "Windows (PowerShell)"

    ```powershell
    uv pip install --python .venv/Scripts/python.exe -r pyproject.toml --extra docs
    .venv/Scripts/zensical build
    ```

=== "macOS and Linux"

    ```bash
    uv pip install --python .venv/bin/python -r pyproject.toml --extra docs
    .venv/bin/zensical build
    ```

Without it KOLONİ runs as usual, and `/guide/` says how to build the guide. Once Zensical is
installed, the update scripts rebuild the guide on each update.

### Where your data goes

Your data goes in `runtime/` inside the KOLONİ folder: the database, working copies, backups and
logs. To keep it elsewhere, set `KOLONI_RUNTIME_ROOT` before you start. API keys are stored in
plain text in that database, so keep the folder private.

### Another port

KOLONİ uses port 8790. To use another one, for example to run a second KOLONİ next to the first:

=== "Windows (PowerShell)"

    ```powershell
    $env:KOLONI_PORT = 8800; .venv/Scripts/python.exe -m app.main
    ```

=== "macOS and Linux"

    ```bash
    KOLONI_PORT=8800 .venv/bin/python -m app.main
    ```

Give each KOLONİ its own `KOLONI_RUNTIME_ROOT` too: two of them must not share a database.

## Update

Stop KOLONİ first (Ctrl+C in its window). Then, in its folder:

=== "Windows (PowerShell)"

    ```powershell
    ./scripts/update.ps1
    ```

=== "macOS and Linux"

    ```bash
    ./scripts/update.sh
    ```

The script refuses while you have uncommitted changes in KOLONİ's files, or while something answers on
KOLONİ's port (`KOLONI_PORT`, 8790). Otherwise it backs up the database, pulls the new version, updates the packages and
rebuilds the page, and this guide where Zensical is installed. It stops at the first step that fails. Start KOLONİ again; the database is
upgraded as it starts. `-DryRun` (Windows) or `--dry-run` (macOS and Linux) prints the steps
without running them.

## Docker

The image holds the page, the API and the database in one container. It is for API keys and model
servers: no CLI is in it. (This is not the project setting that runs agents' commands in Docker.)

```bash
docker build -t koloni .
docker run -it --name koloni -p 127.0.0.1:8790:8790 \
  -v koloni-data:/data \
  -v "$HOME/code/my-app:/projects/my-app" \
  koloni
```

- **Keep `127.0.0.1:` in `-p`.** Without it, the page is open to your network.
- **The link** with the page key is printed at the start; `docker logs koloni` shows it again.
- **Your data** is in the `koloni-data` volume: the database, working copies and logs, with keys in
  plain text.
- **Your projects** are the folders you mount under `/projects`. Open one with the folder button.
  The container runs as user `koloni` (uid 1000); on Linux, files it writes in a mounted folder
  belong to uid 1000.
- **A model server on your machine**: add
  `-e KOLONI_MODEL_BASE_URL=http://host.docker.internal:8080/v1`. On Linux, also add
  `--add-host=host.docker.internal:host-gateway`, and start the model server on the docker0
  address (for example `--host 172.17.0.1`), never on `0.0.0.0`.
- **Another port**: use the same number on both sides and in `KOLONI_PORT`, for example
  `-e KOLONI_PORT=8800 -p 127.0.0.1:8800:8800`.
- **To update**: `git pull`, build the image again, remove the old container
  (`docker rm -f koloni`), and start a new one with the same `koloni-data` volume. The database is
  backed up and upgraded as KOLONİ starts.
- Do not mount Docker's socket into the container: whoever has the socket has full control of your
  machine.

The image has no Node.js, `npx` or `uv`, so MCP servers started with `npx` or `uvx` do not run in
it. Webhooks, which call KOLONİ from your machine, are refused by the image.

## Settings from the environment

KOLONİ does not read a `.env` file. Set these in the shell before you start it.

| Variable | Default | Meaning |
|---|---|---|
| `KOLONI_PORT` | `8790` | The port on `127.0.0.1`. |
| `KOLONI_RUNTIME_ROOT` | `runtime/` | Where the database and working files live. |
| `KOLONI_OPEN_BROWSER` | `1` | `0` does not open the browser at the start. |
| `KOLONI_PAGE_KEY` | a new one each start | A fixed page key. |
| `KOLONI_MODEL_BASE_URL` | `http://127.0.0.1:8080/v1` | First start only: the address of the "Local" provider. |
| `KOLONI_MODEL_ID` | the first model the server lists | First start only: Local's default model. |
| `KOLONI_MODEL_API_KEY` | none | First start only: Local's key. |
| `KOLONI_DETECT_CLI` | `1` | First start only: add Claude Code, Qoder, Codex and agy (switched off) if they are installed. `0` skips this. |

After the first start, change providers on the Models page; the first-start variables no longer
change them. The full list is in [Environment variables](../reference/environment.md).
