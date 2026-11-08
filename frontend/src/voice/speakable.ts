/**
 * What of an answer is said aloud (slice 32a): its words, not its markup. A code block is
 * passed over as "Code block, N lines.", a link is read by its name, and tables and addresses
 * are never read.
 */

const FENCE = /^\s*(```|~~~)/
const END = /[.!?…]$/

/**
 * The answer's words, block by block, each ended as a sentence. `open`: it is still being
 * written - an unclosed code block is left out until it closes (its lines are not counted yet).
 */
export function speakable(markdown: string, open = false): string {
  const blocks: string[] = []
  let paragraph: string[] = []
  let code: number | null = null
  const flush = () => {
    const words = paragraph.join(' ').trim()
    if (words) blocks.push(END.test(words) ? words : `${words.replace(/[:;,]$/, '')}.`)
    paragraph = []
  }
  for (const line of markdown.trimEnd().split('\n')) {
    if (FENCE.test(line)) {
      if (code === null) {
        flush()
        code = 0
      } else {
        blocks.push(`Code block, ${code} ${code === 1 ? 'line' : 'lines'}.`)
        code = null
      }
      continue
    }
    if (code !== null) {
      code += 1
      continue
    }
    const text = line.trim()
    // A table's row, and a line between paragraphs.
    if (!text || text.startsWith('|')) {
      flush()
      continue
    }
    const words = inline(text.replace(/^(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)/, ''))
    // A heading or an item of a list is a sentence of its own.
    if (/^(#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(text)) {
      flush()
      paragraph.push(words)
      flush()
    } else paragraph.push(words)
  }
  flush()
  // Written to the end, an unclosed block is passed over as it stands.
  if (code !== null && !open) blocks.push(`Code block, ${code} ${code === 1 ? 'line' : 'lines'}.`)
  return blocks.filter(block => block !== '.').join(' ')
}

/** A line's words: a picture and an address left out, a link by its name, no marks. */
function inline(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<?https?:\/\/\S+>?/g, '')
    .replace(/[`*]|~~|__/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * The finished sentences of a text, and what follows them. A sentence is finished once
 * whitespace follows its end mark: what is still being written stays in `rest`.
 * shortcut: an abbreviation ("e.g. ") ends a sentence early; upgrade to Intl.Segmenter's
 * sentence granularity if a reader hears it break.
 */
export function sentences(text: string): { done: string[]; rest: string } {
  const done: string[] = []
  let at = 0
  // An end mark (closing quotes and brackets with it) with whitespace after it.
  for (const end of text.matchAll(/[.!?…]+["'”’)\]]*\s+/g)) {
    const sentence = text.slice(at, end.index + end[0].length).trim()
    if (sentence) done.push(sentence)
    at = end.index + end[0].length
  }
  return { done, rest: text.slice(at).trim() }
}

/** The first two sentences of an answer's prose: what is said of it where the Lead wrote nothing to say. */
export function firstTwo(markdown: string): string {
  const prose = sentences(`${speakable(markdown)} `).done.filter(sentence => !CODE.test(sentence))
  return prose.slice(0, 2).join(' ')
}

const CODE = /^Code block, \d+ lines?\.$/
