// McCabe complexity per function in src/ (1 + if / loop / case / catch / ?: / && / || / ??),
// nested functions counted on their own; tests and generated files skipped. Fails when a function
// not in complexity-baseline.json is over the limit, or a baselined one went up. --update lowers
// or drops baseline entries that went down or vanished; it never adds one.
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

export const LIMIT = 12
const K = ts.SyntaxKind
const isFn = n => ts.isFunctionLike(n) && n.body !== undefined

// A function's own name, else its variable / property / JSX attribute's, else the call it is passed to.
function nameOf(f) {
  if (f.name) return f.name.getText()
  let p = f.parent
  while (ts.isParenthesizedExpression(p) || ts.isJsxExpression(p) || ts.isAsExpression(p)) p = p.parent
  if (p.name) return p.name.getText()
  if (ts.isCallExpression(p)) {
    const callee = p.expression
    if (ts.isIdentifier(callee)) return callee.text
    if (ts.isPropertyAccessExpression(callee)) return callee.name.text
  }
  return '(anon)'
}

// Every function in one file: { name: 'Outer>inner', value, line }, in source order.
export function measure(fileName, text) {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true)
  const rows = []
  const visit = (f, outer) => {
    const name = outer ? `${outer}>${nameOf(f)}` : nameOf(f)
    const row = { name, value: 1, line: sf.getLineAndCharacterOfPosition(f.getStart()).line + 1 }
    rows.push(row)
    const count = n => {
      if (isFn(n)) return visit(n, name)
      switch (n.kind) {
        case K.IfStatement: case K.ForStatement: case K.ForInStatement: case K.ForOfStatement:
        case K.WhileStatement: case K.DoStatement: case K.CaseClause: case K.CatchClause:
        case K.ConditionalExpression:
          row.value++
          break
        case K.BinaryExpression: {
          const o = n.operatorToken.kind
          if (o === K.AmpersandAmpersandToken || o === K.BarBarToken || o === K.QuestionQuestionToken) row.value++
        }
      }
      ts.forEachChild(n, count)
    }
    ts.forEachChild(f, count)
  }
  const top = n => (isFn(n) ? visit(n, '') : ts.forEachChild(n, top))
  top(sf)
  return rows
}

// The functions over LIMIT, keyed `file::Outer>name`; same-named offenders in a file get `#2`, `#3`.
// shortcut: two same-named offenders (`map` callbacks) swap keys if the first drops under LIMIT;
// the gate then reads the second as 'went up'. Name the callback if it happens.
export function measureTree(frontend) {
  const out = []
  const walk = dir => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.tsx?$/.test(e.name) && !/\.test\.|generated/.test(e.name)) {
        const file = path.relative(frontend, p).split(path.sep).join('/')
        const seen = new Map()
        for (const r of measure(p, readFileSync(p, 'utf8'))) {
          if (r.value <= LIMIT) continue
          const n = (seen.get(r.name) ?? 0) + 1
          seen.set(r.name, n)
          out.push({ ...r, key: `${file}::${r.name}${n > 1 ? `#${n}` : ''}`, file })
        }
      }
    }
  }
  walk(path.join(frontend, 'src'))
  return out
}

function main() {
  const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const baselineFile = path.join(frontend, 'complexity-baseline.json')
  const baseline = JSON.parse(readFileSync(baselineFile, 'utf8'))
  const now = new Map(measureTree(frontend).map(r => [r.key, r]))
  const failures = []
  for (const r of now.values()) {
    const was = baseline[r.key]
    if (was === undefined) failures.push(`${r.file}:${r.line} ${r.key} is ${r.value}, over ${LIMIT}: split it`)
    else if (r.value > was) failures.push(`${r.file}:${r.line} ${r.key} went up from ${was} to ${r.value}: split it`)
  }
  const kept = {}
  let shrinkable = 0
  for (const [key, was] of Object.entries(baseline)) {
    const value = now.get(key)?.value
    if (value === undefined || value < was) shrinkable++
    if (value !== undefined) kept[key] = Math.min(value, was)
  }
  if (process.argv.includes('--update')) {
    const sorted = Object.fromEntries(Object.entries(kept).sort(([a], [b]) => a.localeCompare(b)))
    writeFileSync(baselineFile, JSON.stringify(sorted, null, 2) + '\n')
    console.log(`complexity: baseline rewritten, ${Object.keys(sorted).length} entries`)
  } else if (shrinkable) {
    console.log(`complexity: you can lower or remove ${shrinkable} baseline entries (npm run check:complexity -- --update)`)
  }
  for (const f of failures) console.error(f)
  if (failures.length) process.exit(1)
  console.log(`complexity: ${now.size} over ${LIMIT}, all baselined, none went up`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
