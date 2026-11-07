import { expect, test } from 'vitest'
import { argumentKey, commandShown, downloadOf, isValue, MASK, masked, NOT_JSON5, packageOf, readPasted, UNDERSTOOD } from './paste'

test('a key in an argument is shown as MASK: after a key flag (spaced or =), after Authorization:, or one that looks like a key', () => {
  const hex = 'a'.repeat(16) + '0123456789abcdef'
  const b64 = 'Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWpr'
  expect(commandShown(['node', 'x.js', '--api-key', 'sk-abc123456', '--token=t0ken1', '-k', 'k1', '--apiKey', 'v1', '--header', 'Authorization: Bearer zz9'])).toEqual(
    ['node', 'x.js', '--api-key', MASK, `--token=${MASK}`, '-k', MASK, '--apiKey', MASK, '--header', `Authorization: Bearer ${MASK}`],
  )
  for (const key of ['sk-abc123456', 'sk-sp-abc123456', 'ghp_abc123456', 'xoxb-1234-5678', hex, b64]) expect(commandShown(['npx', key])).toEqual(['npx', MASK])
  // what is not a key stays as it is, and so does a key flag with no value, or one that is left to the reader
  const plain = ['npx', '-y', '@modelcontextprotocol/server-filesystem', 'C:\\Users\\me\\projects\\a-very-long-folder-name-for-work', '/home/me/projects/another-very-long-folder-name', '--port', '8080', '--port=8080', '--api-key', '--verbose', '--token', '<YOUR_TOKEN>']
  expect(commandShown(plain)).toEqual(plain)
  // the program itself is never taken for a key
  expect(commandShown([hex])).toEqual([hex])
  // a variable's key (docker -e), a header given with =, an address's key and password, and the flags web._SECRET
  // names - the same cases as tests/test_mcp.py's
  const probed = ['docker', '-e', 'GITHUB_TOKEN=ghp_x1', '--header=Authorization: Bearer b3arer', 'https://mcp.example.test/sse?api_key=k3y1&mode=x', 'postgres://u:pw1@h/db', '--pass', 'p1', '--pwd', 'p2', '--credential', 'c1', '--cookie', 'c2', '--session', 's1', '--jwt', 'j1']
  expect(commandShown(probed)).toEqual([
    'docker', '-e', `GITHUB_TOKEN=${MASK}`, `--header=Authorization: Bearer ${MASK}`, `https://mcp.example.test/sse?api_key=${MASK}&mode=x`, `postgres://${MASK}@h/db`,
    '--pass', MASK, '--pwd', MASK, '--credential', MASK, '--cookie', MASK, '--session', MASK, '--jwt', MASK,
  ])
})

test('put away: a key in an argument is MASK in the text and kept apart by its place', () => {
  const read = masked(JSON.stringify({ mcpServers: { brave: { command: 'npx', args: ['-y', 'brave-mcp', '--api-key', 'sk-abc123456', '--secret=s3cr3t'] } } }))!
  expect(read.text).not.toMatch(/sk-abc|s3cr3t/)
  expect(JSON.parse(read.text).mcpServers.brave.args).toEqual(['-y', 'brave-mcp', '--api-key', MASK, `--secret=${MASK}`])
  expect(read.away).toEqual([[argumentKey('brave', 4), 'sk-abc123456'], [argumentKey('brave', 5), '--secret=s3cr3t']])
})

const github = { command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_secret123456' } }
const fetch = { command: 'uvx', args: ['mcp-server-fetch'] }
const both = [
  { name: 'github', command: ['npx', '-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_secret123456' } },
  { name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env: {} },
]

test('a "mcpServers" block, the same without it, and VS Code’s "servers" and "mcp.servers" read alike', () => {
  for (const block of [{ mcpServers: { github, fetch } }, { github, fetch }, { servers: { github, fetch } }, { inputs: [], servers: { github, fetch } }, { mcp: { servers: { github, fetch } } }])
    expect(readPasted(`\n  ${JSON.stringify(block, null, 2)}\n`)).toEqual({ servers: both, unsupported: [] })
})

test('one server alone is read with no name, to be asked for; a number or a flag in its arguments or variables is a word', () => {
  expect(readPasted(JSON.stringify({ command: 'node', args: ['server.js', 8080], env: { DEBUG: true } }))).toEqual({
    servers: [{ name: '', command: ['node', 'server.js', '8080'], env: { DEBUG: 'true' } }],
    unsupported: [],
  })
  // VS Code says "stdio" of a command server
  expect(readPasted(JSON.stringify({ servers: { git: { type: 'stdio', command: 'uvx', args: ['mcp-server-git'] } } }))).toEqual({
    servers: [{ name: 'git', command: ['uvx', 'mcp-server-git'], env: {} }],
    unsupported: [],
  })
})

test('one reached over the network is named, not added, and the others are still read', () => {
  const block = { mcpServers: { fetch, remote: { url: 'https://example.test/mcp', headers: { Authorization: 'Bearer x' } }, sse: { type: 'sse', url: 'https://example.test/sse' }, wind: { serverUrl: 'https://example.test' } } }
  expect(readPasted(JSON.stringify(block))).toEqual({ servers: [both[1]], unsupported: ['remote', 'sse', 'wind'] })
  expect(readPasted(JSON.stringify({ url: 'https://example.test/mcp' }))).toEqual({ servers: [], unsupported: [''] })
})

test('a claude mcp add line: its name, its variables, and the command after --', () => {
  expect(readPasted('claude mcp add github -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_secret123456 -- npx -y @modelcontextprotocol/server-github')).toEqual({
    servers: [both[0]],
    unsupported: [],
  })
  // options before the name, several variables after one -e, quotes, a value with "=", a line carried on with \
  expect(readPasted(`claude mcp add --scope user --env A=1 "B=two words" C=x=y my-db \\\n -- "C:\\Program Files\\db\\server.exe" --port 5432`)).toEqual({
    servers: [{ name: 'my-db', command: ['C:\\Program Files\\db\\server.exe', '--port', '5432'], env: { A: '1', B: 'two words', C: 'x=y' } }],
    unsupported: [],
  })
  // the command without --
  expect(readPasted('claude mcp add fetch uvx mcp-server-fetch')).toEqual({ servers: [both[1]], unsupported: [] })
  expect(readPasted('claude mcp add --transport http notion https://mcp.notion.com/mcp')).toEqual({ servers: [], unsupported: ['notion'] })
  expect(readPasted('claude mcp add -t stdio fetch -- uvx mcp-server-fetch')).toEqual({ servers: [both[1]], unsupported: [] })
})

test('anything else says which shapes are read', () => {
  for (const text of ['hello', '[]', '"npx"', '{}', '{"mcpServers": {}}', '{"github": "npx"}', '{"x": {"command": "npx", "args": "-y"}}', '{"x": {"command": "npx", "env": {"A": {"b": 1}}}}', '{"x": {"command": " "}}', '{"x": {"name": 1}}', 'claude mcp add', 'claude mcp add x --', 'claude mcp add -e NOVALUE x -- npx', 'claude mcp add --weird x -- npx'])
    expect(readPasted(text)).toEqual({ error: UNDERSTOOD })
})

test('broken JSON with a token in it: the error never repeats what was pasted, and nothing is put away', () => {
  for (const [text, said] of [
    ["{mcpServers: {github: {command: 'npx', env: {TOKEN: 'ghp_secret123456'}}}}", NOT_JSON5],
    ["{\"mcpServers\": {\"github\": {\"command\": 'npx'}}}", NOT_JSON5],
    ['{"mcpServers": {"github": {"command": "npx", "env": {"TOKEN": "ghp_secret123456" /* unclosed', UNDERSTOOD],
  ]) {
    const read = readPasted(text)
    expect(read).toEqual({ error: said })
    expect(JSON.stringify(read)).not.toContain('ghp_')
    expect(masked(text)).toBeNull()
  }
})

test('JSONC as READMEs write it: comments and trailing commas are read, a "//" or ",]" in a string is kept, and the key is put away', () => {
  const text = `{
    // Claude Desktop
    "mcpServers": {
      /* the GitHub server */
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github", "--url=https://x.test/*a*/,]",],
        "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_secret123456", // your token
        },
      },
    },
  }`
  expect(readPasted(text)).toEqual({
    servers: [{ ...both[0], command: [...both[0].command, '--url=https://x.test/*a*/,]'] }],
    unsupported: [],
  })
  const read = masked(text)!
  expect(read.text).not.toContain('ghp_')
  expect(read.away).toEqual([['github\nGITHUB_PERSONAL_ACCESS_TOKEN', 'ghp_secret123456']])
})

test('a value a page leaves to its reader is no value', () => {
  for (const value of ['', '${input:github_token}', '<YOUR_TOKEN>', MASK, '$GITHUB_TOKEN', 'YOUR_API_KEY', 'your-key', 'paste_key_here', 'xxxx', 'XXXXXXXX'])
    expect(isValue(value)).toBe(false)
  for (const value of ['ghp_secret123456', '1', 'true', 'xx', 'nowhere']) expect(isValue(value)).toBe(true)
})

test('a claude mcp add line: a shell prompt before it, carried on with \\ ` or ^, one line only, a lone quote in a word', () => {
  const read = { servers: [both[1]], unsupported: [] }
  expect(readPasted('$ claude mcp add fetch -- uvx mcp-server-fetch')).toEqual(read)
  for (const on of ['\\', '`', '^']) expect(readPasted(`claude mcp add fetch ${on}\r\n  -- uvx mcp-server-fetch`)).toEqual(read)
  expect(readPasted('claude mcp add fetch -- uvx mcp-server-fetch\nclaude mcp add other -- uvx x')).toEqual({ error: UNDERSTOOD })
  expect(readPasted("claude mcp add notes -- node don't.js")).toEqual({ servers: [{ name: 'notes', command: ['node', "don't.js"], env: {} }], unsupported: [] })
})

test('put away: each value masked and kept apart; a server over the network left as its name; nothing to put away is null', () => {
  const read = masked(JSON.stringify({ mcpServers: { github, remote: { url: 'https://example.test/?key=k1', headers: { Authorization: 'Bearer zz' } } } }))!
  expect(read.away).toEqual([['github\nGITHUB_PERSONAL_ACCESS_TOKEN', 'ghp_secret123456']])
  expect(JSON.parse(read.text)).toEqual({
    mcpServers: { github: { command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: MASK } }, remote: { url: '…' } },
  })
  // what is written is read again as the same servers
  expect(readPasted(read.text)).toEqual({ servers: [{ ...both[0], env: { GITHUB_PERSONAL_ACCESS_TOKEN: MASK } }], unsupported: ['remote'] })
  // one alone stays one alone
  expect(JSON.parse(masked(JSON.stringify(github))!.text)).toEqual({ ...github, env: { GITHUB_PERSONAL_ACCESS_TOKEN: MASK } })
  expect(masked(JSON.stringify({ fetch }))).toBeNull()
  expect(masked('not a block ghp_x')).toBeNull()
})

test('the package npx or uvx is given is told only where it is the one that runs', () => {
  expect(packageOf(['npx', '-y', '@upstash/context7-mcp@4.4.4'])).toBe('@upstash/context7-mcp@4.4.4')
  expect(packageOf(['cmd', '/c', 'npx', '--yes', '-q', 'JSONStream'])).toBe('JSONStream')
  expect(packageOf(['uvx', 'mcp-server-git@2026.10.19', '--repository', 'C:/p'])).toBe('mcp-server-git@2026.10.19')
  for (const command of [
    ['npx', './local-folder'],
    ['npx', '--registry=https://registry.example.invalid', 'rea-agents'],
    ['npx', '-p', 'other', 'rea-agents'],
    ['uvx', '--with', 'extra', 'mcp-server-git'],
    ['uvx', '--python', '3.12', 'mcp-server-git'],
    ['uvx', 'git+https://example.test/x'],
    ['constructor', 'x'],
    ['node', 'server.js'],
  ])
    expect(packageOf(command)).toBeNull()
  // what may be downloaded is still said of such a command
  expect(downloadOf(['npx', '-p', 'other', 'rea-agents'])).toBe('other')
})
