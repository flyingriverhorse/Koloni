/**
 * Pasted text that reads as code (slice 85a), fenced for the message box: with its language when a
 * strong sign names it, else a bare fence. Prose, a line or two, or text already fenced: null.
 * shortcut: signs line by line, not a parser - short code, code inside prose, or prose full of
 * operators can be taken wrong (the note under the box puts it back as pasted); upgrade to a real
 * classifier if it misleads often.
 */

/** A line that looks like code rather than words. */
const CODE_LINE = [
  /^(?!\s*\p{Lu}[\p{L} ]*: ).*[;{}([]\s*$/u, // ends a statement, opens or closes a block - not a "Label: a; b;" line
  /^\s*[}\])]/, // closes one
  /^(\t| {2,})(?![-*+•] |\d+[.)] |[a-z]\) )\S/, // indented, and not a list's item
  // a keyword, with something of code after it: "return the old one" is words
  /^\s*(def|class|function|const|let|var|return|elif|async|await|export|interface|public|private|package|fn|func)\b.*([(){}[\]=;<>]|:\s*$)/,
  /^\s*((from [\w.]+ )?import [\w.]+(\s+as \w+)?(,\s*[\w.]+)*\s*$|import\b.*['"]|#include\s*[<"]|#define \w)/,
  /^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|WITH|FROM|WHERE|JOIN|ORDER BY|GROUP BY)\b/,
  /^#!/,
  /^\s*(\/\/|\/\*)/,
  /[=!]==?|=>|&&|\|\||::/,
  /^\s*[\w.[\]]+\s*[-+*/]?=\s*\S/, // an assignment
  /^\s*[\w.]+\(.*\)\s*;?$/, // a call
  /^\s*"[^"]*"\s*:/, // a JSON key
]

/** A stack trace, code in no one language: Python's header, or two of a trace's lines (one alone may be words: "at 14:30"). */
const TRACE_LINE = /^([ \t]+at .+:\d+|[ \t]*File ".+", line \d+)/
const isTrace = (code: string) => /^Traceback \(most recent call last\)/m.test(code) || code.split('\n').filter(line => TRACE_LINE.test(line)).length >= 2

/** The strong signs, in the order they are tried. */
const LANGUAGES: [string, RegExp][] = [
  ['sql', /^\s*(select\b[\s\S]*\bfrom\b|insert\s+into\b|update\s+\w+\s+set\b|delete\s+from\b|create\s+(table|index|view)\b)/im],
  ['python', /^\s*(def \w+\(.*\)\s*(->.*)?:|class \w+(\(.*\))?:|(from [\w.]+ )?import [\w.]+(\s+as \w+)?(,\s*[\w.]+)*|elif\b.*:|except\b.*:|if __name__ == )\s*$/m],
  ['typescript', /^\s*(export\s+)?(interface|type)\s+\w+[^=]*[={]|\w\??:\s*(string|number|boolean|void|unknown)\b/m],
  ['javascript', /^\s*(import .+ from ['"]|(export\s+)?(const|let) \w+ = |(export\s+)?(async\s+)?function\s*\w*\s*\()|console\.log\(|require\(['"]/m],
]

const SHEBANG: [string, RegExp][] = [
  ['python', /^#!.*\bpython/],
  ['bash', /^#!.*\b(ba)?sh\b/],
  ['javascript', /^#!.*\bnode\b/],
]

function languageOf(code: string): string | null {
  if (isTrace(code)) return null
  if (/^[{[]/.test(code)) {
    try {
      JSON.parse(code)
      return 'json'
    } catch {
      // not JSON: on to the others
    }
  }
  if (code.startsWith('#!')) return SHEBANG.find(([, sign]) => sign.test(code))?.[0] ?? null
  return LANGUAGES.find(([, sign]) => sign.test(code))?.[0] ?? null
}

export function asCode(pasted: string): { text: string; language: string | null } | null {
  const code = pasted.replace(/\r\n?/g, '\n').replace(/^\s*\n/, '').trimEnd()
  const lines = code.split('\n')
  if (lines.length < 3 || /^ {0,3}(```|~~~)/m.test(code)) return null
  const said = lines.filter(line => line.trim())
  const looks = said.filter(line => CODE_LINE.some(sign => sign.test(line))).length
  if (looks < said.length * 0.6 && !isTrace(code)) return null
  const language = languageOf(code)
  return { text: `\`\`\`${language ?? ''}\n${code}\n\`\`\``, language }
}
