export interface DiffLine {
  kind: 'hunk' | 'add' | 'del' | 'ctx'
  oldNo: number | null
  newNo: number | null
  text: string
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** Turn a unified diff into numbered lines; everything before the first hunk is header. */
export function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = []
  let oldNo = 0
  let newNo = 0
  let inHunk = false
  for (const raw of diff.split('\n')) {
    const header = HUNK.exec(raw)
    if (header) {
      oldNo = Number(header[1])
      newNo = Number(header[2])
      inHunk = true
      lines.push({ kind: 'hunk', oldNo: null, newNo: null, text: raw })
      continue
    }
    if (!inHunk || raw.startsWith('\\')) continue
    const text = raw.slice(1)
    if (raw.startsWith('+')) lines.push({ kind: 'add', oldNo: null, newNo: newNo++, text })
    else if (raw.startsWith('-')) lines.push({ kind: 'del', oldNo: oldNo++, newNo: null, text })
    else lines.push({ kind: 'ctx', oldNo: oldNo++, newNo: newNo++, text })
  }
  return lines
}
