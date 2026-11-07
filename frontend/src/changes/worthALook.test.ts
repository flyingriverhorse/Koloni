import { expect, test } from 'vitest'
import type { MergeFile } from '../api/types'
import { worthALook } from './worthALook'

/** K-dikkat-satiri: why a change card's files are worth a look - the reasons, never a score. */

const file = (path: string, over: Partial<MergeFile> = {}): MergeFile => ({
  path,
  kind: 'changed',
  state: 'ready',
  diff: '--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b',
  additions: 1,
  deletions: 1,
  note: null,
  ...over,
})
const why = (...paths: (string | MergeFile)[]) =>
  worthALook(paths.map(p => (typeof p === 'string' ? file(p) : p))).map(look => look.why)

test('a migration or schema file, by its folder or name', () => {
  for (const path of ['alembic/versions/0091_x.py', 'app/migrations/0001_initial.py', 'db/seed.SQL', 'prisma/schema.prisma']) {
    expect(why(path), path).toEqual(['migration or schema'])
  }
  // A models file is not one by its name.
  expect(why('app/db/models.py')).toEqual([])
})

test('a config or env file: .env* anywhere, the named files anywhere, ini / toml / yaml at the root or under config/', () => {
  for (const path of ['.env', 'web/.env.local', 'app/settings.py', 'frontend/package.json', 'pyproject.toml', 'alembic.ini', 'docker-compose.yml', 'config/app.yaml', 'config/deep/x.toml']) {
    expect(why(path), path).toEqual(['config or env'])
  }
  expect(why('.github/workflows/ci.yml', 'tests/data.toml')).toEqual([])
})

test('a security path: a whole word of its folders or file, never a part of one', () => {
  for (const path of ['app/auth.py', 'app/auth/views.py', 'src/AuthService.ts', 'lib/user_permissions.py', 'oauth-client.ts', 'core/crypto/keys.go', 'jwt.token.ts']) {
    expect(why(path), path).toEqual(['security path'])
  }
  expect(why('app/author.py', 'tokenizer.py', 'authority/x.py')).toEqual([])
  // A document about it changes no code.
  expect(why('docs/auth.md', 'secrets.txt')).toEqual([])
})

test('a deleted file, over 300 lines of one, and one with no diff', () => {
  expect(why(file('old.py', { kind: 'deleted' }))).toEqual(['deleted'])
  expect(why(file('big.py', { additions: 250, deletions: 51 }))).toEqual(['over 300 lines'])
  expect(why(file('big.py', { additions: 250, deletions: 50 }))).toEqual([])
  expect(why(file('logo.png', { diff: null, additions: null, deletions: null }))).toEqual(['no diff (not text, or over 1 MiB)'])
  // A whole-file clash of a binary: still taken by Apply, so counted.
  expect(why(file('blob.bin', { state: 'conflict', whole: true, diff: null, additions: null, deletions: null }))).toEqual([
    'no diff (not text, or over 1 MiB)',
  ])
})

test('only what Apply would take counts: applied, refused and left-out files are not', () => {
  for (const state of ['applied', 'refused', 'left_out'] as const) {
    expect(why(file('.env', { state, kind: 'deleted', diff: null }))).toEqual([])
  }
  expect(why(file('a.txt', { state: 'merged' }))).toEqual([])
})

test('each reason names its files, in a fixed order; a file can have several', () => {
  expect(worthALook([file('a.txt'), file('app/auth.py', { kind: 'deleted' }), file('auth.sql'), file('b.txt')])).toEqual([
    { why: 'migration or schema', paths: ['auth.sql'] },
    { why: 'security path', paths: ['app/auth.py', 'auth.sql'] },
    { why: 'deleted', paths: ['app/auth.py'] },
  ])
})
