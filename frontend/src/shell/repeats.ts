/**
 * The same KOLONİ-made line several times in a row, as one line with how many times it came:
 * each item kept with its count, the repeats after it left out. `line` is the line's words, or
 * null for words that are somebody's own (the user's, an agent's): those are never merged.
 * `anywhere`: folded into its first wherever it comes again, not only right after it (a room's
 * posts, where others speak between a member's same words).
 */
export function foldRepeats<T>(items: T[], line: (item: T) => string | null, anywhere = false): [T, number][] {
  const kept: [T, number][] = []
  const first = new Map<string, [T, number]>()
  let before: string | null = null
  for (const item of items) {
    const said = line(item)
    const into = said === null ? undefined : anywhere ? first.get(said) : said === before ? kept[kept.length - 1] : undefined
    if (into) into[1] += 1
    else {
      const one: [T, number] = [item, 1]
      kept.push(one)
      if (said !== null) first.set(said, one)
    }
    before = said
  }
  return kept
}

/** " ×8" after a line that came 8 times in a row; nothing after one that came once. */
export const times = (n: number) => (n > 1 ? ` ×${n}` : '')
