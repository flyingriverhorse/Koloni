/**
 * The same KOLONİ-made line several times in a row, as one line with how many times it came:
 * each item kept with its count, the repeats after it left out. `line` is the line's words, or
 * null for words that are somebody's own (the user's, an agent's): those are never merged.
 */
export function foldRepeats<T>(items: T[], line: (item: T) => string | null): [T, number][] {
  const kept: [T, number][] = []
  let before: string | null = null
  for (const item of items) {
    const said = line(item)
    if (said !== null && said === before) kept[kept.length - 1][1] += 1
    else kept.push([item, 1])
    before = said
  }
  return kept
}

/** " ×8" after a line that came 8 times in a row; nothing after one that came once. */
export const times = (n: number) => (n > 1 ? ` ×${n}` : '')
