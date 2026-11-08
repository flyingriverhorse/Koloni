const URL = /^[a-z][\w+.-]*:\/\//i
// A known extension, not any dotted end: `os.path` or `self.name` is code, not a file.
const EXTENSION =
  /\.(py|pyi|ipynb|ts|tsx|js|jsx|mjs|cjs|json|jsonl|md|txt|toml|ya?ml|ini|cfg|conf|env|lock|log|csv|xml|html?|css|scss|svg|png|jpe?g|gif|pdf|zip|sh|ps1|bat|cmd|go|rs|java|kt|c|h|cpp|hpp|cs|rb|php|sql|db|vue|svelte)$/i
const PROGRAMS = new Set(
  (
    'git gh npm npx pnpm yarn bun deno node tsc vite vitest playwright oxlint eslint prettier python python3 py pip pip3 uv uvx ' +
    'pytest ruff mypy alembic uvicorn cargo rustc go make cmake docker kubectl cd ls dir cat type rg grep findstr sed awk find ' +
    'head tail echo curl wget mkdir rm cp mv touch chmod ssh sudo winget powershell pwsh cmd bash sh claude codex copilot agy'
  ).split(' '),
)
const POWERSHELL = /^(get|set|new|remove|select|invoke|start|stop|test|copy|move|add|out|write)-\w+$/i

/**
 * What an inline code span names, for its colour: a file path, a command, or neither (null).
 * shortcut: a heuristic over inline code only, by its shape and first word; upgrade to the turn's own tool calls if it guesses wrong often.
 */
export function codeKind(text: string): 'path' | 'command' | null {
  if (URL.test(text)) return null
  const unquoted = text.match(/^(["'])(.+)\1$/)?.[2]
  const name = unquoted ?? text
  if ((unquoted || !/\s/.test(name)) && (/[/\\]/.test(name) || EXTENSION.test(name) || /^\.[a-z_]/i.test(name))) return 'path'
  const [first, ...rest] = text.split(' ')
  if (rest.length && rest.join('') && (PROGRAMS.has(first.toLowerCase()) || POWERSHELL.test(first))) return 'command'
  return null
}
