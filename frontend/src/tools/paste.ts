/** A server read from the block on its page; `env` holds the values, which are secrets. */
export interface Pasted {
  name: string
  command: string[]
  env: Record<string, string>
}

/** The servers read, and the names of those reached over the network, which cannot be added yet. */
export type Read = { servers: Pasted[]; unsupported: string[] } | { error: string }

export const UNDERSTOOD =
  'This is not a block KOLONİ can read. It reads a "mcpServers" block (Claude Desktop, Cursor), the same without "mcpServers", one server’s {"command", "args", "env"}, VS Code’s "servers", or a claude mcp add line.'

export const NOT_JSON5 =
  'This looks like JSON5 (a key without quotes, or a string in single quotes), which KOLONİ does not read: put double quotes around each key and string, then paste it again.'
// A key without quotes, or a string in single quotes before what follows one.
const JSON5ISH = /[{,]\s*[A-Za-z_$][\w$]*\s*:|'[^'\n]*'\s*[:,}\]]/

/** What stands in the text for a value once it is read: the value itself is kept apart. */
export const MASK = '••••••••'

/** A server's name as app/mcp_client.py NAME has it. */
export const NAME = /^[a-z][a-z0-9-]{0,15}$/

export const count = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

export const programOf = (part = '') => (part.split(/[\\/]/).pop() ?? '').toLowerCase().replace(/\.(cmd|exe)$/, '')

/**
 * What a command may download before it starts - the package npx or uvx is given, the image
 * docker or podman runs (also behind cmd /c) - or null for a command that downloads nothing.
 * shortcut: judged by the launcher's name; npm exec, pnpm dlx, yarn dlx, uv tool run, bunx and pipx run are missed - add one here when it is used.
 */
export function downloadOf(command: string[]): string | null {
  const [program, ...args] = unwrapped(command)
  const launcher = programOf(program)
  if (launcher === 'npx' || launcher === 'uvx') return args.find(arg => !arg.startsWith('-')) ?? launcher
  if ((launcher === 'docker' || launcher === 'podman') && args[0] === 'run') return 'the image it names'
  return null
}

const unwrapped = (command: string[]) => (programOf(command[0]) === 'cmd' && command[1]?.toLowerCase() === '/c' ? command.slice(2) : command)

// As app/package_look.py has them: what may stand before the package, and a package with its version.
const QUIET = ['-y', '--yes', '-q', '--quiet']
const VERSION = '[A-Za-z0-9][A-Za-z0-9._+-]{0,63}'
const NPX = new RegExp(`^(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]{0,213}(@${VERSION})?$`)
const UVX = new RegExp(`^[A-Za-z0-9]([A-Za-z0-9._-]{0,98}[A-Za-z0-9])?((==|@)${VERSION})?$`)

/**
 * The package npx or uvx is given (also behind cmd /c), as app/package_look.py package_of finds it - KOLONİ
 * can look inside it and ask osv.dev about it - or null; null too with an option before it that may change
 * which package runs (--registry, -p, --index-url, --with, --python …).
 */
export function packageOf(command: string[]): string | null {
  const [program, ...args] = unwrapped(command)
  const launcher = programOf(program)
  const valid = launcher === 'npx' ? NPX : launcher === 'uvx' ? UVX : null
  const spec = args.find(arg => !QUIET.includes(arg))
  return valid && spec && valid.test(spec) ? spec : null
}

/**
 * A value a page leaves to its reader is no value: "", ${input:…}, <YOUR_TOKEN>, $VAR, YOUR_KEY,
 * paste-key-here, xxxx, and MASK.
 * shortcut: placeholders by these shapes only; add one here when a page writes another.
 */
export const isValue = (value: string) =>
  value !== '' && value !== MASK && !/^(\$\{.*\}|<.*>|\$[A-Za-z_]\w*|x{3,})$|^your[\W_]|[\W_]here$/is.test(value)

// A name like a secret's, as app/web.py _SECRET has it (-k too): a flag's, a variable's, a field of an address.
const SECRET_NAME = /token|key|secret|password|passwd|pass|pwd|auth|signature|sig|credential|session|jwt|bearer|cookie/i
const secretName = (name: string) => name === 'k' || SECRET_NAME.test(name)
// An argument that is a key on its own: sk-… (and sk-sp-…), ghp_…, github_pat_…, xox?-…, long hex, long base64.
const KEY_LIKE = /^(sk-|gh[pousr]_|github_pat_|xox[a-z]-)\S{6,}$|^[0-9a-f]{32,}$|^(?=.*\d)(?=.*[a-z])[\w+-]{40,}={0,2}$/i
// An address in an argument, the user (and password) before its host, a field of its query.
const URL_IN = /[a-z][a-z0-9+.-]*:\/\/[^\s"'<>]+/gi
const USERINFO = /^([a-z][a-z0-9+.-]*:\/\/)([^/?#@]+)@/i
const FIELD = /([?&])([^=&#]+)=([^&#]*)/g
const AUTHORIZATION = /(authorization:\s*(?:(?:bearer|basic|token)\s+)?)(\S[\s\S]*)/gi
// NAME=VALUE: a flag's (--token=…) or a variable's (docker's -e GITHUB_TOKEN=…); a flag alone.
const NAMED = /^(-{0,2}[\w.-]+)=([\s\S]*)$/
const FLAG = /^-{1,2}([\w-]+)$/

function partShown(command: string[], at: number): string {
  const part = command[at]
  const inUrl = (url: string) =>
    url
      .replace(USERINFO, (_, scheme: string) => `${scheme}${MASK}@`)
      .replace(FIELD, (all, mark: string, name: string, value: string) => (secretName(name) && isValue(value) ? `${mark}${name}=${MASK}` : all))
  const shown = part.replace(URL_IN, inUrl).replace(AUTHORIZATION, (_, before: string) => before + MASK)
  if (shown !== part) return shown
  const named = NAMED.exec(part)
  const [name, value] = named ? [named[1], named[2]] : [null, part]
  const flag = at > 1 ? FLAG.exec(command[at - 1]) : null
  const secret = name ? secretName(name.replace(/^-+/, '')) : !!flag && secretName(flag[1]) && !part.startsWith('-')
  return (secret && isValue(value)) || KEY_LIKE.test(value) ? (name ? `${name}=${MASK}` : MASK) : part
}

/**
 * A command as it may be shown: a key in an argument is MASK - a value named like a secret (after such a flag,
 * spaced or with =, or as a variable's NAME=), after "Authorization:", the user and password or a secret field of
 * an address, or one that is KEY_LIKE. The program itself is never a key. app/mcp_client.py command_shown is the same.
 * shortcut: keys by these shapes only (a --monkey or --design flag is taken for one); add a shape here and there when a README writes another.
 */
export function commandShown(command: string[]): string[] {
  return command.map((part, at) => (at === 0 ? part : partShown(command, at)))
}

/**
 * Where an argument's value is kept, beside the variables (a variable is never named so).
 * shortcut: by its place in the command - an argument added before it by hand moves a kept key to the next MASK; upgrade if that is seen.
 */
export const argumentKey = (server: string, at: number) => `${server}\nargument ${at}`

const error = { error: UNDERSTOOD }
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const isScalar = (value: unknown) => ['string', 'number', 'boolean'].includes(typeof value)

// A string is matched whole first and kept as it is: a "//" or ",]" inside one is text.
const COMMENT = /("(?:[^"\\]|\\.)*")|\/\/[^\n]*|\/\*[\s\S]*?\*\//g
const TRAILING_COMMA = /("(?:[^"\\]|\\.)*")|,(?=\s*[}\]])/g

/** JSONC as JSON: its comments, then its trailing commas, taken out (in that order: a comment may sit between the comma and the brace). */
const jsonOf = (text: string) =>
  text.replace(COMMENT, (_, string?: string) => string ?? ' ').replace(TRAILING_COMMA, (_, string?: string) => string ?? '')

/**
 * The servers in a block pasted from a server's page. Never says what was in the text: JSON.parse's
 * own message quotes it, and a token with it. JSONC as READMEs write it is read too: comments and trailing commas.
 * shortcut: JSON5's single quotes and unquoted keys are told apart (NOT_JSON5), not read - no JSON5 parser is installed - so such a block is not masked and stays as typed in the box only; read it if a README is seen to write them.
 */
export function readPasted(text: string): Read {
  // (A line copied with the shell's prompt before it.)
  const trimmed = text.trim().replace(/^\$\s+/, '')
  if (/^claude\s+mcp\s+add\s/.test(trimmed)) return fromClaudeLine(trimmed)
  let json: unknown
  try {
    json = JSON.parse(jsonOf(trimmed))
  } catch {
    return JSON5ISH.test(trimmed) ? { error: NOT_JSON5 } : error
  }
  if (!isObject(json)) return error
  const block = json.mcpServers ?? json.servers ?? (isObject(json.mcp) ? json.mcp.servers : undefined)
  // One server alone: its name is not in the block, and is asked for.
  if (block === undefined && ('command' in json || 'url' in json)) return fromEntries([['', json]])
  return isObject(block ?? json) ? fromEntries(Object.entries((block ?? json) as Record<string, unknown>)) : error
}

function fromEntries(entries: [string, unknown][]): Read {
  const servers: Pasted[] = []
  const unsupported: string[] = []
  for (const [name, entry] of entries) {
    if (!isObject(entry)) return error
    if (typeof entry.command !== 'string') {
      // One reached over the network (Windsurf calls its address serverUrl): said, and the others still read.
      if ('url' in entry || 'serverUrl' in entry || (entry.type !== undefined && entry.type !== 'stdio')) {
        unsupported.push(name)
        continue
      }
      return error
    }
    const args = entry.args ?? []
    const env = entry.env ?? {}
    if (!entry.command.trim() || !Array.isArray(args) || !args.every(isScalar) || !isObject(env) || !Object.values(env).every(isScalar)) return error
    servers.push({
      name,
      command: [entry.command, ...args.map(String)],
      env: Object.fromEntries(Object.entries(env).map(([key, value]) => [key, String(value)])),
    })
  }
  return servers.length + unsupported.length > 0 ? { servers, unsupported } : error
}

/**
 * claude mcp add [-e K=V …] [-s scope] [-t transport] <name> [--] <command> <args…>, one line (\ ` ^ carry it on).
 * shortcut: quotes as a POSIX shell reads them, without escapes inside, and --opt=value is not read; upgrade if a page writes them so.
 */
function fromClaudeLine(text: string): Read {
  const line = text.replace(/[\\`^]\r?\n/g, ' ')
  if (/[\r\n]/.test(line)) return error
  // A quote with no other to close it ("don't") is a letter of its word.
  const words = (line.match(/(?:"[^"]*"|'[^']*'|[^\s"']|["'])+/g) ?? []).map(word => word.replace(/"([^"]*)"|'([^']*)'/g, '$1$2'))
  // Pairs, not an object: a variable named __proto__ is a variable.
  const env: [string, string][] = []
  let name = ''
  let remote = false
  let at = 3
  for (; at < words.length; at++) {
    const word = words[at]
    if (word === '--') {
      at++
      break
    }
    if (word === '-e' || word === '--env') {
      if (!/^[A-Za-z_]\w*=/.test(words[at + 1] ?? '')) return error
      // Several may follow one -e.
      while (/^[A-Za-z_]\w*=/.test(words[at + 1] ?? '')) {
        const [key, ...value] = words[++at].split('=')
        env.push([key, value.join('=')])
      }
    } else if (['-s', '--scope', '-H', '--header'].includes(word)) at++
    else if (word === '-t' || word === '--transport') remote = words[++at] !== 'stdio'
    else if (word.startsWith('-')) return error
    else if (!name) name = word
    // The command, given without "--".
    else break
  }
  if (!name) return error
  if (remote) return { servers: [], unsupported: [name] }
  const command = words.slice(at)
  return command.length > 0 ? { servers: [{ name, command, env: Object.fromEntries(env) }], unsupported: [] } : error
}

/**
 * The text again with what was read put away: each value is MASK, and a server reached over the
 * network is only its name (its address and headers may carry a key). Null when there is nothing to
 * put away. `away` holds the values, by server and variable (an argument's by argumentKey).
 */
export function masked(text: string): { text: string; away: [string, string][] } | null {
  const got = readPasted(text)
  if (!('servers' in got)) return null
  const away: [string, string][] = []
  const shown = got.servers.map(({ name, command, env }) => {
    for (const [variable, value] of Object.entries(env)) if (isValue(value)) away.push([`${name}\n${variable}`, value])
    const kept = Object.fromEntries(Object.entries(env).map(([variable, value]) => [variable, isValue(value) ? MASK : value]))
    const [program, ...args] = commandShown(command)
    args.forEach((arg, at) => arg !== command[at + 1] && away.push([argumentKey(name, at + 1), command[at + 1]]))
    return [name, { command: program, args, env: kept }] as const
  })
  if (away.length === 0 && got.unsupported.length === 0) return null
  const all = [...shown, ...got.unsupported.map(name => [name, { url: '…' }] as const)]
  return { text: JSON.stringify(all.length === 1 && all[0][0] === '' ? all[0][1] : { mcpServers: Object.fromEntries(all) }, null, 2), away }
}
