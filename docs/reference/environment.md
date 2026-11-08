# Environment variables

KOLONİ reads these when it starts. It does not read a `.env` file: set them in the shell before you
start it.

=== "Windows (PowerShell)"

    ```powershell
    $env:KOLONI_PORT = 8800; .venv/Scripts/python.exe -m app.main
    ```

=== "macOS and Linux"

    ```bash
    KOLONI_PORT=8800 .venv/bin/python -m app.main
    ```

## Where and how KOLONİ runs

| Variable | Default | What it does |
|---|---|---|
| `KOLONI_PORT` | `8790` | The port KOLONİ listens on. |
| `KOLONI_RUNTIME_ROOT` | `runtime/` in KOLONİ's folder | Where the database, working copies, backups and logs are kept. Two KOLONİs must not share one. |
| `KOLONI_HOST` | `127.0.0.1` | The address KOLONİ listens on. Anything other than `127.0.0.1`, `::1` or `localhost` is refused at the start, except inside the Docker image. |
| `KOLONI_PAGE_KEY` | a new one each start | A fixed page key. KOLONİ takes it out of its own environment once read, so its commands and agents do not get it. |
| `KOLONI_OPEN_BROWSER` | `1` | `0`: do not open the page in the browser at the start. |
| `KOLONI_DEV` | not set | `1`: also accept the live-reload page on port 5173 (for development). |

## The first start only

These make the first providers. After the first start, change providers on the Models page; changing
these does nothing to providers that already exist.

| Variable | Default | What it does |
|---|---|---|
| `KOLONI_MODEL_BASE_URL` | `http://127.0.0.1:8080/v1` | The address of the "Local" provider. |
| `KOLONI_MODEL_ID` | the first model the server lists | Local's default model. |
| `KOLONI_MODEL_API_KEY` | none | Local's key. |
| `KOLONI_DETECT_CLI` | `1` | First start only: add Claude Code, Qoder, Codex and agy (switched off) as providers if they are installed. `0` skips this. |

## Models and agents

| Variable | Default | What it does |
|---|---|---|
| `KOLONI_MODEL_FIRST_TOKEN_SECONDS` | `900` | How long a model may take to start answering before the run fails. |
| `KOLONI_MODEL_STALL_SECONDS` | `120` | How long an answer may pause before the run fails. |
| `KOLONI_CONTEXT_CHARS` | `240000` | How much history, in characters, an agent keeps when its model's context window is not known. |
| `KOLONI_SEARCH_SECONDS` | `20` | How long a search through the project's files may take before it is given up. A value that is not a positive number is ignored. |

## Background work

| Variable | Default | What it does |
|---|---|---|
| `KOLONI_TRIGGER_CLOCK` | `1` | `0`: triggers do not start by themselves. |
| `KOLONI_CATALOGUE_REFRESH` | `1` | `0`: never download the model catalogue at the start. Otherwise it is downloaded again once it is a week old, unless **Keep the catalogue fresh** is off on the Models page. |

## The local model server and MCP servers

| Variable | Default | What it does |
|---|---|---|
| `KOLONI_LOCAL_SERVER` | `llama-server` on PATH | The program the Models page's **Server** tab starts, until you choose another there: the full path of `llama-server` in a llama.cpp build's `bin` folder. |
| `KOLONI_NVIDIA_SMI` | `nvidia-smi` | The program the **Server** tab asks for GPU memory and load. |
| `KOLONI_MCP_HOME` | `KOLONI/mcp/` in your cache folder (`%LOCALAPPDATA%` on Windows), one folder per runtime | Where the MCP servers KOLONİ starts keep their files. |

## Variables KOLONİ gives to commands

Agents' commands get this machine's environment, except variables with secret names (such as
`GITHUB_TOKEN` or `OPENAI_API_KEY`) and the ways into a program you are signed in to (`GIT_ASKPASS`,
`SSH_AUTH_SOCK`, `VSCODE_*`, `CLAUDE_CODE_*` and the like), unless you name them under Settings ›
This project › Commands and secrets › **Secret variables commands may see**. A project whose tests use git over ssh
needs `SSH_AUTH_SOCK` named there. KOLONİ's own git, which pushes for you, keeps all of them. With **Planted test key (canary)** on, they also get a made-up
`KOLONI_CANARY_KEY`. In Docker, commands get none of this machine's environment.
