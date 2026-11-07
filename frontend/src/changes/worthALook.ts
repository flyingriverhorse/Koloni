import type { MergeFile } from '../api/types'

/** One reason a change card's files are worth a look, with the files it is of. Reasons only: no score. */
export interface Look {
  why: string
  paths: string[]
}

// Only what Apply would take: applied, refused and left-out files say on the card why they are not.
const OPEN = new Set<MergeFile['state']>(['ready', 'merged', 'conflict'])
const MIGRATION_DIRS = new Set(['migrations', 'alembic'])
const CONFIG_NAMES = new Set(['settings.py', 'package.json', 'pyproject.toml'])
const SECURITY_WORDS = new Set(['auth', 'oauth', 'security', 'permission', 'permissions', 'secret', 'secrets', 'crypto', 'token', 'tokens'])
// A document about auth changes no code.
const DOC = /\.(md|mdx|rst|txt)$/i
const LARGE = 300

type Is = (file: MergeFile, dirs: string[], name: string) => boolean

/** Its folders' and file's words - split at `/ . _ -` and where camelCase turns - match a security word whole: `author.py` does not. */
const security = (path: string) =>
  !DOC.test(path) &&
  path
    .replace(/\.[^./]+$/, '')
    .split(/[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])/)
    .some(word => SECURITY_WORDS.has(word.toLowerCase()))

// shortcut: package.json counts whatever changed in it, not only its scripts or dependencies; read its diff if that flags too often.
const REASONS: [string, Is][] = [
  [
    'migration or schema',
    (_, dirs, name) => dirs.some(dir => MIGRATION_DIRS.has(dir)) || name.endsWith('.sql') || name === 'schema.prisma',
  ],
  [
    'config or env',
    (_, dirs, name) =>
      name.startsWith('.env') || CONFIG_NAMES.has(name) || ((dirs.length === 0 || dirs[0] === 'config') && /\.(ini|toml|ya?ml)$/.test(name)),
  ],
  ['security path', file => security(file.path)],
  ['deleted', file => file.kind === 'deleted'],
  [`over ${LARGE} lines`, file => file.additions != null && file.deletions != null && file.additions + file.deletions > LARGE],
  // Of these states only a file with a side that is not text, or is over 1 MiB, has no diff.
  ['no diff (not text, or over 1 MiB)', file => file.diff == null],
]

/** Why a card's files are worth a look before Apply, in a fixed order; [] where nothing is. */
export function worthALook(files: MergeFile[]): Look[] {
  const open = files.filter(file => OPEN.has(file.state))
  return REASONS.flatMap(([why, is]) => {
    const paths = open
      .filter(file => {
        const dirs = file.path.toLowerCase().split('/')
        const name = dirs.pop() ?? ''
        return is(file, dirs, name)
      })
      .map(file => file.path)
    return paths.length > 0 ? [{ why, paths }] : []
  })
}
