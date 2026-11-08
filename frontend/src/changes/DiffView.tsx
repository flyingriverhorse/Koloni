import { useEffect, useMemo, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { LONGEST_COLOURED, MOST_COLOURED, colourLines, languageOf } from './highlight'
import { type DiffLine, parseDiff } from './parseDiff'

/** Unchanged lines kept beside a change; a longer run of them is folded. */
const AROUND = 3
const LEAST_FOLDED = 4
const HUNK = /^@@ -(\d+)/

/**
 * A line, by its place in the parsed diff; or unchanged lines not shown - `at` the first one's
 * number before the change, `count` how many, `sent` whether they are in the diff (or only
 * counted between the hunks sent, to be read with the whole file).
 */
type Piece = number | { at: number; count: number; sent: boolean }
type Fold = Exclude<Piece, number>
type Row = Fold | [number | null, number | null]

/** The lines shown: an unchanged run kept to AROUND lines beside a change, unless opened. */
function piecesOf(lines: DiffLine[], opened: ReadonlySet<number>): Piece[] {
  const out: Piece[] = []
  // The next line before the change, by its number: what the next hunk skips is counted from it.
  let next = 1
  for (let i = 0; i < lines.length; ) {
    const line = lines[i]
    if (line.kind === 'hunk') {
      const start = Number(HUNK.exec(line.text)?.[1] ?? 0)
      if (start > next) out.push({ at: next, count: start - next, sent: false })
      i++
      continue
    }
    if (line.kind !== 'ctx') {
      if (line.oldNo !== null) next = line.oldNo + 1
      out.push(i++)
      continue
    }
    let end = i
    while (end < lines.length && lines[end].kind === 'ctx') end++
    // (at a file's or a hunk's start or end, nothing is kept on that side)
    const head = i === 0 || lines[i - 1].kind === 'hunk' ? 0 : AROUND
    const tail = end === lines.length || lines[end].kind === 'hunk' ? 0 : AROUND
    const count = end - i - head - tail
    const at = lines[i + head]?.oldNo ?? 0
    for (let k = i; k < end; k++) {
      if (count < LEAST_FOLDED || opened.has(at) || k !== i + head) out.push(k)
      else {
        out.push({ at, count, sent: true })
        k += count - 1
      }
    }
    next = (lines[end - 1].oldNo ?? 0) + 1
    i = end
  }
  return out
}

/** Side by side: a removed line across from the one added in its place, an unchanged one on both sides. */
function rowsOf(lines: DiffLine[], pieces: Piece[]): Row[] {
  const rows: Row[] = []
  const kind = (p: number) => (typeof pieces[p] === 'number' ? lines[pieces[p] as number].kind : null)
  for (let p = 0; p < pieces.length; ) {
    const piece = pieces[p]
    if (typeof piece !== 'number') rows.push(pieces[p++] as Fold)
    else if (lines[piece].kind === 'ctx') rows.push([piece, pieces[p++] as number])
    else {
      const [gone, came]: number[][] = [[], []]
      while (kind(p) === 'del') gone.push(pieces[p++] as number)
      while (kind(p) === 'add') came.push(pieces[p++] as number)
      for (let k = 0; k < Math.max(gone.length, came.length); k++) rows.push([gone[k] ?? null, came[k] ?? null])
    }
  }
  return rows
}

const SIGNS = { add: ['+', 'added '], del: ['−', 'removed '] } as const

/** Not in colour only: a sign to see, and a word for a screen reader. */
function Sign({ kind }: { kind: DiffLine['kind'] }) {
  if (kind !== 'add' && kind !== 'del') return <span className="diff-sign" />
  return (
    <>
      <span className="diff-sign" aria-hidden>
        {SIGNS[kind][0]}
      </span>
      <span className="visually-hidden">{SIGNS[kind][1]}</span>
    </>
  )
}

interface Props {
  diff: string
  /** The file's name: its language colours it (slice 42a). */
  path?: string
  /** Before and after side by side. */
  split?: boolean
  /** Reads the diff with all of the file around it: what lies between the hunks then opens. */
  readWhole?: () => Promise<string>
}

/**
 * A unified diff as numbered lines, what did not change folded past AROUND lines beside a change;
 * `split` puts before and after side by side. A fold opens on a click, and the focus goes to the
 * first line it showed.
 */
export function DiffView({ diff, path, split = false, readWhole }: Props) {
  // The whole file's diff, once read - for this diff only.
  const [whole, setWhole] = useState<{ of: string; diff: string } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [opened, setOpened] = useState<ReadonlySet<number>>(new Set())
  const [focus, setFocus] = useState<number | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const shown = whole?.of === diff ? whole.diff : diff
  const lines = useMemo(() => parseDiff(shown), [shown])
  const language = path ? languageOf(path) : null
  // (how long the file is, as far as its line numbers tell)
  const large = language !== null && lines.some(line => Math.max(line.oldNo ?? 0, line.newNo ?? 0) > MOST_COLOURED)
  // (highlight.js's own output, which escapes the text: the only HTML set here)
  const html = useMemo(() => {
    if (!language || large) return null
    // Each side coloured as one text - before (unchanged and removed lines), after (unchanged and added) - so a
    // string over several lines is one (a line too long to colour stands in it empty).
    const out: (string | null)[] = lines.map(() => null)
    for (const changed of ['del', 'add']) {
      const side = lines.flatMap((line, i) => (line.kind === 'ctx' || line.kind === changed ? [i] : []))
      const coloured = colourLines(side.map(i => (lines[i].text.length > LONGEST_COLOURED ? '' : lines[i].text)).join('\n'), language)
      side.forEach((i, n) => {
        if (lines[i].text.length <= LONGEST_COLOURED) out[i] = coloured[n]
      })
    }
    return out
  }, [lines, language, large])
  useEffect(() => {
    if (focus !== null) box.current?.querySelector<HTMLElement>('[data-focus]')?.focus()
  }, [focus])
  if (lines.length === 0) return <p className="muted diff-empty">No textual difference.</p>

  function open(fold: Fold) {
    const shows = () => {
      setOpened(new Set([...opened, fold.at]))
      setFocus(fold.at)
    }
    if (fold.sent) return shows()
    readWhole?.().then(
      read => {
        setWhole({ of: diff, diff: read })
        shows()
      },
      error => setFailed(errorText(error)),
    )
  }
  const text = (i: number) =>
    html?.[i] != null ? (
      <span className="diff-text" dangerouslySetInnerHTML={{ __html: html[i] }} />
    ) : (
      <span className="diff-text">{lines[i].text}</span>
    )
  // The first line a fold showed takes the focus (from the script only: not a tab stop).
  const focusOf = (i: number | null) => (i !== null && lines[i].kind === 'ctx' && lines[i].oldNo === focus ? { 'data-focus': '', tabIndex: -1 } : {})
  const fold = (piece: Fold, key: number) =>
    piece.sent || readWhole ? (
      <button key={key} type="button" className="diff-fold" onClick={() => open(piece)}>
        {piece.count} unchanged lines <span aria-hidden>▸</span>
      </button>
    ) : (
      <div key={key} className="diff-fold">
        {piece.count} unchanged lines
      </div>
    )
  const half = (i: number | null, side: 'oldNo' | 'newNo') =>
    i === null ? (
      <div className="diff-half diff-none" />
    ) : (
      <div className={`diff-half diff-${lines[i].kind}`}>
        <span className="diff-no">{lines[i][side]}</span>
        <Sign kind={lines[i].kind} />
        {text(i)}
      </div>
    )
  const pieces = piecesOf(lines, opened)
  // shortcut: what follows the last hunk sent is not counted (the diff does not say how long the file is); upgrade if it is missed.
  return (
    <>
      {large && <p className="muted diff-note">plain text, file too large to colour</p>}
      {failed && (
        <p className="muted diff-note" role="status">
          {failed}
        </p>
      )}
      {split ? (
        <div ref={box} className="diff diff-split mono">
          {rowsOf(lines, pieces).map((row, key) =>
            Array.isArray(row) ? (
              <div key={key} className="diff-row" {...focusOf(row[0])}>
                {half(row[0], 'oldNo')}
                {half(row[1], 'newNo')}
              </div>
            ) : (
              fold(row, key)
            ),
          )}
        </div>
      ) : (
        <div ref={box} className="diff mono">
          {pieces.map((piece, key) =>
            typeof piece === 'number' ? (
              <div key={key} className={`diff-line diff-${lines[piece].kind}`} {...focusOf(piece)}>
                <span className="diff-no">{lines[piece].oldNo ?? ''}</span>
                <span className="diff-no">{lines[piece].newNo ?? ''}</span>
                <Sign kind={lines[piece].kind} />
                {text(piece)}
              </div>
            ) : (
              fold(piece, key)
            ),
          )}
        </div>
      )}
    </>
  )
}
