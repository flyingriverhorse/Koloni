// Starts the real backend for end-to-end tests from an empty database and a
// known sample project. The cleanup happens here, before the server opens its
// database, rather than in a Playwright global setup that runs after it.
import { spawn } from 'node:child_process'
import { appendFileSync, createWriteStream, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { APP_PORT, E2E_ROOT, FAKE_AGY, FAKE_CLAUDE, FAKE_LLAMA, LLAMA_PORT, LOG_DIR, MCP_PLAN, MCP_RECORD, MODEL_URL, PAGE_KEY, PROJECT_DIR, PYTHON, REPO_ROOT } from './paths.mjs'

rmSync(E2E_ROOT, { recursive: true, force: true })
mkdirSync(PROJECT_DIR, { recursive: true })
writeFileSync(path.join(PROJECT_DIR, 'hello.py'), "print('hi')\n")
writeFileSync(path.join(PROJECT_DIR, 'check.py'), "print('2 passed')\n")
// What the memory test notes a fact from, and later changes. Written here, before any turn:
// a file that changed during a turn cannot back a fact.
writeFileSync(path.join(PROJECT_DIR, 'settings.txt'), '# settings\nThe service listens on port 8123.\n')
writeFileSync(
  path.join(PROJECT_DIR, 'slow.py'),
  'import time\nfor i in range(60):\n    print("tick", i, flush=True)\n    time.sleep(0.5)\n',
)

// A dev server an agent starts and leaves running (slice 42b): on a free port of this machine, it
// says where, as Vite does, and serves a page whose script writes its words; "deny": one that
// refuses to be shown in another page's frame.
writeFileSync(
  path.join(PROJECT_DIR, 'serve42.py'),
  [
    'import http.server, sys',
    'PAGE = b"<h1 id=t>not run</h1><script>document.getElementById(\'t\').textContent = \'Served live\'</script>"',
    'class Page(http.server.BaseHTTPRequestHandler):',
    '    def do_GET(self):',
    '        self.send_response(200)',
    '        self.send_header("Content-Type", "text/html")',
    '        if "deny" in sys.argv:',
    '            self.send_header("X-Frame-Options", "DENY")',
    '        self.end_headers()',
    '        self.wfile.write(PAGE)',
    '    def log_message(self, *args):',
    '        pass',
    'server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)',
    'print(f"  Local:   http://127.0.0.1:{server.server_address[1]}/", flush=True)',
    'server.serve_forever()',
    '',
  ].join('\n'),
)

// A static game in a folder of its own, shown by an agent and opened in Preview (slice 42b).
mkdirSync(path.join(PROJECT_DIR, 'game42'), { recursive: true })
writeFileSync(path.join(PROJECT_DIR, 'game42', 'index.html'), '<h1>A game</h1>\n')

// A picture an agent shows (slice 39): five honey bars on a light ground, as a PNG.
writeFileSync(path.join(PROJECT_DIR, 'chart39.png'), barsPng())
function barsPng() {
  const [width, height, bars] = [240, 140, [40, 90, 65, 120, 80]]
  const rows = Array.from({ length: height }, (_, y) => {
    const row = Buffer.alloc(1 + width * 3) // a filter byte of 0, then RGB
    for (let x = 0; x < width; x++) {
      const bar = Math.floor((x - 20) / 44)
      const on = x >= 20 && (x - 20) % 44 < 30 && bar < bars.length && y < height - 10 && height - 10 - y < bars[bar]
      row.set(on ? [227, 164, 58] : [250, 246, 238], 1 + x * 3)
    }
    return row
  })
  const chunk = (type, data) => {
    const sized = Buffer.alloc(4)
    sized.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(zlib.crc32(body))
    return Buffer.concat([sized, body, crc])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header.set([8, 2, 0, 0, 0], 8) // 8 bits a channel, RGB
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

const python = PYTHON
// The plan of the stand-in MCP server a spec adds through the Tools page: only where its record goes.
writeFileSync(MCP_PLAN, JSON.stringify({ record: MCP_RECORD }))

// A stand-in for Claude Code working natively (the one the backend's own tests use): a
// provider whose command is FAKE_CLAUDE runs it, and it follows this plan. It says a word,
// hands a look-around to a sub-agent of its own - which reads a file and runs a command -
// and reports. The events are the ones measured from the real CLI (slice 13). Its sub-agent is
// one named as KOLONİ names a role it offers the CLI (89g): an ordinary one where none is offered.
const SUB = { parent: 'toolu_sub' }
const plan = path.join(E2E_ROOT, 'claude-plan.json')
writeFileSync(
  plan,
  JSON.stringify({
    record: path.join(E2E_ROOT, 'claude-record.json'),
    // (the version measured to name a role's tool use to the hook: 89g's roles are offered to it)
    version: '2.1.311',
    script: [
      { say: 'I will ask a helper.' },
      {
        tool: 'Agent',
        id: 'toolu_sub',
        open: true,
        input: { description: 'Look around', subagent_type: 'koloni-checker', prompt: 'Read hello.py and say what it prints' },
      },
      { system: { subtype: 'task_started', tool_use_id: 'toolu_sub', is_backgrounded: false } },
      { tool: 'Read', input: { file_path: 'hello.py' }, result: "print('hi')", ...SUB },
      { tool: 'Bash', input: { command: 'python hello.py' }, result: 'hi', ...SUB },
      { system: { subtype: 'task_notification', tool_use_id: 'toolu_sub', status: 'completed', summary: 'It prints hi.' } },
      { result_for: 'toolu_sub', result: 'It prints hi.' },
      { say: 'The helper says it prints hi.' },
    ],
  }),
)
const fake = path.join(REPO_ROOT, 'tests', 'fake_claude_native_cli.py')
if (process.platform === 'win32') writeFileSync(FAKE_CLAUDE, `@"${python}" "${fake}" %*\r\n`)
else writeFileSync(FAKE_CLAUDE, `#!/bin/sh\nexec "${python}" "${fake}" "$@"\n`, { mode: 0o755 })

// A stand-in for the agy CLI (the one the backend's own tests use), with a plan of its own.
// It looks at a file with a tool of its own, asks for a command - which, started without
// leave to do more, it refuses itself - and answers. The events are the ones measured from
// the real CLI (slice 17c).
const agyPlan = path.join(E2E_ROOT, 'agy-plan.json')
writeFileSync(
  agyPlan,
  JSON.stringify({
    record: path.join(E2E_ROOT, 'agy-record.json'),
    // The page lists the models while a turn runs: only the turn is put on record here.
    record_models: false,
    model: 'gemini-stand-in',
    script: [
      { say: 'Let me look.' },
      { tool: 'view_file', parameters: { AbsolutePath: 'hello.py' }, output: "print('hi')" },
      { tool: 'run_command', asks: true, parameters: { CommandLine: 'python hello.py' }, touches: { 'ran.txt': 'x' } },
      { say: 'It prints hi. I could not run it here.' },
    ],
  }),
)
const fakeAgy = path.join(REPO_ROOT, 'tests', 'fake_agy_cli.py')
if (process.platform === 'win32') writeFileSync(FAKE_AGY, `@"${python}" "${fakeAgy}" %*\r\n`)
else writeFileSync(FAKE_AGY, `#!/bin/sh\nexec "${python}" "${fakeAgy}" "$@"\n`, { mode: 0o755 })

// A stand-in for llama-server (the one the backend's own tests use) with two models, set as the one the Models page
// starts: on a port of its own, so that a Start never reaches the user's server on 8080.
const llama = path.dirname(FAKE_LLAMA)
mkdirSync(path.join(llama, 'models'), { recursive: true })
for (const name of ['e2e-model.gguf', 'e2e-other.gguf']) writeFileSync(path.join(llama, 'models', name), '')
const fakeLlama = path.join(REPO_ROOT, 'tests', 'fake_llama_server.py')
if (process.platform === 'win32') writeFileSync(FAKE_LLAMA, `@"${python}" "${fakeLlama}" %*\r\n`)
else writeFileSync(FAKE_LLAMA, `#!/bin/sh\nexec "${python}" "${fakeLlama}" "$@"\n`, { mode: 0o755 })
const llamaArgs = ['-m', path.join('models', 'e2e-model.gguf'), '--port', String(LLAMA_PORT), '-c', '8192', '--jinja']
writeFileSync(path.join(E2E_ROOT, 'local-server.json'), JSON.stringify({ executable: FAKE_LLAMA, args: llamaArgs }))

const server = spawn(python, ['-m', 'app.main'], {
  cwd: REPO_ROOT,
  stdio: ['ignore', 'pipe', 'pipe'],
  env: {
    ...process.env,
    KOLONI_PORT: String(APP_PORT),
    KOLONI_RUNTIME_ROOT: E2E_ROOT,
    // Never this machine's llama-server or graphics card: the stand-in, and no nvidia-smi ("–").
    KOLONI_LOCAL_SERVER: FAKE_LLAMA,
    KOLONI_NVIDIA_SMI: path.join(E2E_ROOT, 'no-nvidia-smi'),
    KOLONI_MODEL_BASE_URL: `${MODEL_URL}/v1`,
    // Google is never reached from a spec: its key check goes to the fake server.
    KOLONI_GEMINI_URL: MODEL_URL,
    KOLONI_DETECT_CLI: '0',
    // Nor models.dev: the catalogue is not downloaded at the start.
    KOLONI_CATALOGUE_REFRESH: '0',
    KOLONI_PAGE_KEY: PAGE_KEY,
    // Slice 51: the agent's browser is the stand-in (tests/fake_browser.py), never this machine's Chrome.
    KOLONI_BROWSER_FAKE: path.join(REPO_ROOT, 'tests', 'fake_browser.py'),
    // K-tarayici-disari: a site's name of a test's own (site.test) is not asked of DNS; the stand-in takes it to loopback.
    KOLONI_E2E_NAMES: '1',
    FAKE_CLI_PLAN: plan,
    FAKE_AGY_PLAN: agyPlan,
    // A home folder of the run's own, when one is given (107-cli-home: its ~/.codex, never this machine's).
    // shortcut: given only for that spec's run; make it every run's once the other specs are seen to pass with it.
    ...(process.env.KOLONI_E2E_HOME && { USERPROFILE: process.env.KOLONI_E2E_HOME, HOME: process.env.KOLONI_E2E_HOME }),
  },
})
// All the backend says goes on as before, and into a log of this run: when a run fails,
// that log says whether the backend raised, stopped or went quiet (keep-failures.mjs keeps it).
mkdirSync(LOG_DIR, { recursive: true })
const logged = path.join(LOG_DIR, 'backend.log')
writeFileSync(logged, `started ${new Date().toISOString()}\n`)
const log = createWriteStream(logged, { flags: 'a' })
server.stdout.on('data', chunk => (process.stdout.write(chunk), log.write(chunk)))
server.stderr.on('data', chunk => (process.stderr.write(chunk), log.write(chunk)))
// Written at once: this process ends with the backend, before a stream would be flushed.
server.on('exit', (code, signal) =>
  appendFileSync(logged, `the backend exited: code ${code}, signal ${signal}, ${new Date().toISOString()}\n`),
)
const stop = () => server.kill()
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
process.on('exit', stop)
server.on('exit', code => process.exit(code ?? 0))
