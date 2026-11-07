import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
export const E2E_ROOT = path.join(REPO_ROOT, 'runtime', 'e2e')
export const PROJECT_DIR = path.join(E2E_ROOT, 'project')
// Ports of their own for a second checkout (a git worktree) to run its e2e beside this one.
export const APP_PORT = Number(process.env.KOLONI_E2E_PORT || 9480)
export const MODEL_PORT = Number(process.env.FAKE_MODEL_PORT || 8081)
export const APP_URL = `http://127.0.0.1:${APP_PORT}`
export const MODEL_URL = `http://127.0.0.1:${MODEL_PORT}`
// The backend's page key (slice 94): given, so that every request of a spec can carry it.
export const PAGE_KEY = 'e2e-page-key-of-a-test-run-not-a-secret'
// A command that runs the stand-in for Claude Code working natively; start-backend.mjs writes it.
export const FAKE_CLAUDE = path.join(E2E_ROOT, process.platform === 'win32' ? 'fake-claude.cmd' : 'fake-claude')
// The same for the stand-in for the agy CLI.
export const FAKE_AGY = path.join(E2E_ROOT, process.platform === 'win32' ? 'fake-agy.cmd' : 'fake-agy')
// The repo's Python, which runs the backend and its stand-ins.
export const PYTHON = path.join(REPO_ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
// The stand-in for an MCP server (the one the backend's own tests use): a spec adds it through the Tools page,
// as this command and with its plan in a variable. start-backend.mjs writes the plan; the server its record.
export const FAKE_MCP = path.join(REPO_ROOT, 'tests', 'fake_mcp_server.py')
export const MCP_PLAN = path.join(E2E_ROOT, 'mcp-plan.json')
export const MCP_RECORD = path.join(E2E_ROOT, 'mcp-record.jsonl')
// The stand-in for llama-server (slice 64), in a folder of its own with a `models` folder; start-backend.mjs writes
// it, and sets it to serve on a port of its own: never this machine's 8080, where the user's own may be.
export const FAKE_LLAMA = path.join(E2E_ROOT, 'llama', process.platform === 'win32' ? 'llama-server.cmd' : 'llama-server')
export const LLAMA_PORT = MODEL_PORT + 1
// Kept for looking at after a failed run; not in git (e2e/_*), and not under E2E_ROOT, which every run clears.
export const LOG_DIR = path.join(REPO_ROOT, 'frontend', 'e2e', '_logs')
export const KEPT_DIR = path.join(REPO_ROOT, 'frontend', 'e2e', '_failures')
// A folder outside the project (slice 41): not under runtime/, which KOLONİ never opens.
export const OUTSIDE_DIR = path.join(os.tmpdir(), `koloni-e2e-outside-${APP_PORT}`)
// The skills a spec adds (slice 45): folders of the user's, outside the project and runtime/.
export const SKILL_DIR = path.join(os.tmpdir(), `koloni-e2e-skills-${APP_PORT}`)
