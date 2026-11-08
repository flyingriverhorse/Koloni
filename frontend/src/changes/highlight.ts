/**
 * Coloured code (slice 42a): highlight.js's core and the languages agents write most, bundled
 * with the app - nothing is fetched. A language is told by the file's name; one not here is
 * plain text.
 */
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

for (const [name, language] of Object.entries({ bash, css, javascript, json, markdown, python, sql, typescript, xml, yaml })) hljs.registerLanguage(name, language)

const BY_ENDING: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  html: 'xml',
  htm: 'xml',
  xml: 'xml',
  svg: 'xml',
  css: 'css',
  json: 'json',
  md: 'markdown',
  yml: 'yaml',
  yaml: 'yaml',
  sh: 'bash',
  bash: 'bash',
}

/** Past this many lines a file is not coloured; nor is a line past this many characters. */
export const MOST_COLOURED = 5000
export const LONGEST_COLOURED = 2000

/** A fence's language (or one of its other names: py, ts, sh) that is coloured here. */
export const canColour = (language: string) => hljs.getLanguage(language) !== undefined

export function languageOf(path: string): string | null {
  const ending = path.split('.').at(-1)?.toLowerCase() ?? ''
  // (its own keys only: "a.constructor" is not a language)
  return Object.hasOwn(BY_ENDING, ending) ? BY_ENDING[ending] : null
}

/** A text as highlight.js's HTML: escaped by it, so safe to set as HTML. */
export const colour = (text: string, language: string) => hljs.highlight(text, { language, ignoreIllegals: true }).value

/**
 * A text's lines as highlight.js's HTML, coloured as a whole: a string or a comment over several
 * lines is so on each of them - the spans open at a line's end are closed there and opened again
 * on the next. (Its HTML has no tag but its own spans: the text in it is escaped.)
 */
export function colourLines(text: string, language: string): string[] {
  const open: string[] = []
  return colour(text, language)
    .split('\n')
    .map(line => {
      const html = open.join('') + line
      for (const [tag] of line.matchAll(/<span[^>]*>|<\/span>/g)) {
        if (tag === '</span>') open.pop()
        else open.push(tag)
      }
      return html + '</span>'.repeat(open.length)
    })
}
