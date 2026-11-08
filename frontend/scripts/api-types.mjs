// Regenerates src/api/generated.ts from the backend's OpenAPI schema, or with
// --check fails when the committed file is stale.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repo = path.resolve(frontend, '..')
const check = process.argv.includes('--check')
const schema = path.join(repo, 'runtime', 'openapi.json')
const committed = path.join(frontend, 'src', 'api', 'generated.ts')
const target = check ? path.join(repo, 'runtime', 'generated.check.ts') : committed
const python = path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

mkdirSync(path.dirname(schema), { recursive: true })
execFileSync(python, [path.join(repo, 'scripts', 'export_openapi.py'), schema], { stdio: 'inherit' })
execFileSync(process.execPath, [path.join(frontend, 'node_modules', 'openapi-typescript', 'bin', 'cli.js'), schema, '-o', target], { stdio: 'inherit' })

if (check) {
  const read = file => readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
  if (read(committed) !== read(target)) {
    console.error('src/api/generated.ts is stale: run `npm run generate:api`')
    process.exit(1)
  }
}
