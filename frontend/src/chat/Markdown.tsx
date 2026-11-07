import type { Element } from 'hast'
import { type ReactNode, createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import ReactMarkdown, { type Components, type UrlTransform, defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { LONGEST_COLOURED, MOST_COLOURED, canColour, colour } from '../changes/highlight'
import { codeKind } from './codeKind'

/** The words being rendered, and whether they are written to their end: a mermaid block reads them to see whether its fence has closed yet. */
const Source = createContext({ text: '', written: false })

/**
 * B-182: a link into an agent's working copy (".../copies/<its folder>/tree/notes.md", seen live in a report) leads
 * nowhere the user can open: it stands as the file's path in the project, as text. Kept past the renderer's own check
 * only to be told so - never as an address. A path on this machine only (file:// or none): a web address that has
 * such a path (https://github.com/x/copies/y/tree/z) stays a link.
 */
const IN_COPY = /^(?!(?!file:)[a-z][a-z\d+.-]*:\/\/).*?[\\/]copies[\\/][^\\/]+[\\/]tree[\\/]([^?#]+)/i
const urlTransform: UrlTransform = (url, key, node) => (node?.tagName === 'a' && key === 'href' && IN_COPY.test(url) ? url : defaultUrlTransform(url))

/**
 * No image in a model's or an agent's words is drawn: drawing it would fetch its address
 * unasked - a way out for what the words carry, around every approval. A remote one stands
 * as its alt text and its address, which the user opens with a click of their own, in a
 * tab of its own; one with no address left (a `data:` image, or one the renderer will not
 * link to) as its alt text alone.
 */
const components: Components = {
  img: ({ src, alt }) => (
    <span className="md-image">
      [{alt || 'image'}]
      {typeof src === 'string' && src && (
        <>
          {' '}
          <a href={src} target="_blank" rel="noreferrer noopener">
            {src}
          </a>
        </>
      )}
    </span>
  ),
  a: ({ node: _node, href, children, ...props }) => {
    const inCopy = typeof href === 'string' ? IN_COPY.exec(href) : null
    if (!inCopy) return <a href={href} {...props}>{children}</a>
    const path = inCopy[1].replaceAll('\\', '/')
    return (
      <code className="md-path" title={`${path}, in the project`}>
        {typeof children === 'string' && IN_COPY.test(children) ? path : children}
      </code>
    )
  },
  // An inline span that names a path or a command is coloured so (K-sohbet-renk). A fenced block's text ends in a line
  // end; it keeps its own colouring.
  code: ({ node, className, ...props }) => {
    const text = node ? textOf(node) : ''
    const kind = text.endsWith('\n') ? null : codeKind(text)
    return <code {...props} className={kind ? `md-${kind}` : className} />
  },
  pre: function Pre({ node, ...props }) {
    const { text: source, written } = useContext(Source)
    const child = node?.children[0]
    const code = child?.type === 'element' && child.tagName === 'code' ? child : null
    const language = code && [code.properties.className].flat().map(String).find(name => name.startsWith('language-'))?.slice('language-'.length)
    const text = code ? textOf(code) : ''
    // Coloured as a file is (slice 85a): highlight.js's own output, which escapes the text. (Once per text: an
    // answer being written renders again on every token.)
    const coloured = useMemo(() => {
      const lines = text.split('\n')
      if (!language || language === 'mermaid' || !canColour(language) || lines.length > MOST_COLOURED || lines.some(line => line.length > LONGEST_COLOURED)) return null
      return colour(text, language)
    }, [text, language])
    const block = <pre {...props} />
    if (!code) return block
    if (language !== 'mermaid') {
      if (coloured === null) return block
      return (
        <pre {...props}>
          <code className={`language-${language}`} dangerouslySetInnerHTML={{ __html: coloured }} />
        </pre>
      )
    }
    // A block still being written (no closing fence yet) stays code: drawing it on every token would only fail.
    // Written to their end, the words' last block may run to it unclosed (CommonMark): that is drawn.
    const at = node?.position
    const lines = at ? source.slice(at.start.offset, at.end.offset).trimEnd().split('\n') : null
    if (lines && !written && !closes(lines)) return block
    return <Diagram text={text}>{block}</Diagram>
  },
}

/** Closed by a fence of the opening one's character, at least as long, alone on the last line (CommonMark). */
function closes(lines: string[]) {
  const open = lines[0].match(/^[\s>]*(`{3,}|~{3,})/)?.[1]
  const close = lines.at(-1)!.match(/^[\s>]*(`{3,}|~{3,})\s*$/)?.[1]
  return lines.length > 1 && !!open && !!close && close[0] === open[0] && close.length >= open.length
}

/** Each drawing its own id: mermaid first takes away the element with the id it is given - the one shown. */
let drawings = 0

const textOf = (code: Element) => code.children.map(child => (child.type === 'text' ? child.value : '')).join('')

/** The app's theme is the `dark` class on the page (theme/theme.ts); a diagram is drawn anew when it changes. */
const watchTheme = (changed: () => void) => {
  const watch = new MutationObserver(changed)
  watch.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return () => watch.disconnect()
}
const isDark = () => document.documentElement.classList.contains('dark')

/**
 * A ```mermaid block drawn as a diagram (slice 68). mermaid is fetched only once a diagram is on
 * screen - its own chunk - and draws strictly: the text is a model's or a file's, so no HTML or
 * click in it is honoured, and what is put on the page is mermaid's own sanitised SVG.
 */
function Diagram({ text, children }: { text: string; children: ReactNode }) {
  const dark = useSyncExternalStore(watchTheme, isDark)
  const [drawn, setDrawn] = useState<{ svg: string; type: string } | { error: string } | null>(null)
  const [source, setSource] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let gone = false
    import('mermaid')
      .then(async ({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          htmlLabels: false,
          suppressErrorRendering: true,
          theme: dark ? 'dark' : 'default',
          // mermaid 12 lays out with ELK by default; elkjs is not shipped (vite.config.ts), so dagre - and for the
          // two kinds that have a layout of their own, theirs
          layout: 'dagre',
          mindmap: { layout: 'cose-bilkent' },
          swimlane: { layout: 'swimlane' },
          // mermaid's own list, and what a diagram's %%{init}%% or front matter would use to bring back HTML labels,
          // pick its own theme or layout, or add CSS that fetches (themeCSS is not in mermaid's list)
          secure: ['secure', 'securityLevel', 'startOnLoad', 'maxTextSize', 'suppressErrorRendering', 'maxEdges', 'htmlLabels', 'theme', 'themeVariables', 'themeCSS', 'fontFamily', 'altFontFamily', 'darkMode', 'layout'],
        })
        const { svg, diagramType } = await mermaid.render(`mermaid-${++drawings}`, text)
        if (!gone) setDrawn({ svg, type: diagramType })
      })
      .catch((error: unknown) => !gone && setDrawn({ error: String(error instanceof Error ? error.message : error).split('\n')[0] }))
    return () => {
      gone = true
    }
  }, [text, dark])
  const svg = drawn && 'svg' in drawn ? drawn.svg : null
  useLayoutEffect(() => {
    const drawing = box.current?.querySelector('svg')
    if (!drawing || !drawn || !('type' in drawn)) return
    drawing.setAttribute('role', 'img')
    // (mermaid's own, e.g. "flowchart-v2", would be read out in place of "image")
    drawing.removeAttribute('aria-roledescription')
    // Its own title (mermaid's accTitle) if it was given one; else what kind of diagram it is.
    const title = drawing.querySelector(':scope > title')?.textContent?.trim()
    drawing.setAttribute('aria-label', title || `Diagram: ${drawn.type.replace(/-v\d+$|Diagram$/, '')}`)
  }, [drawn])
  return (
    <div className="md-diagram">
      {svg && <div ref={box} className="md-diagram-drawing" dangerouslySetInnerHTML={{ __html: svg }} />}
      {(!svg || source) && children}
      {drawn && 'error' in drawn && <p className="muted">Could not draw this diagram: {drawn.error}</p>}
      {svg && (
        <button type="button" className="link-btn" aria-expanded={source} onClick={() => setSource(shown => !shown)}>
          {source ? 'Hide source' : 'Show source'}
        </button>
      )}
    </div>
  )
}

/**
 * Markdown as every place that shows a model's or an agent's words renders it. Raw HTML is not rendered.
 * `written`: the words are whole (a file, a finished answer), not still coming in.
 */
export function Markdown({ children, written = false }: { children: string | null | undefined; written?: boolean }) {
  const source = useMemo(() => ({ text: children ?? '', written }), [children, written])
  return (
    <Source.Provider value={source}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={urlTransform}>
        {children}
      </ReactMarkdown>
    </Source.Provider>
  )
}

/**
 * A fenced block alone on its lines: three or more backticks (no backtick after them on the line: that is
 * inline code) or tildes, closed by the same.
 * shortcut: the closing fence must be the opening one exactly, not CommonMark's "at least as long"; upgrade if a longer one is met.
 */
const FENCED = /^ {0,3}(?:(`{3,})[^`\n]*\n(?:[\s\S]*?\n)? {0,3}\1|(~{3,})[^\n]*\n(?:[\s\S]*?\n)? {0,3}\2)[ \t]*$/gm

/**
 * The user's own words (slice 85a): as written, a `*` or `#` of theirs kept, but for their fenced
 * code, shown as it is in an answer - coloured, a diagram drawn.
 */
export function UserText({ children }: { children: string }) {
  const parts: ReactNode[] = []
  let at = 0
  for (const block of children.matchAll(FENCED)) {
    // (the line ends around the block are the box's own edge)
    parts.push(
      children.slice(at, block.index).replace(/\n$/, ''),
      <div key={block.index} className="markdown">
        <Markdown>{block[0]}</Markdown>
      </div>,
    )
    at = block.index + block[0].length + (children[block.index + block[0].length] === '\n' ? 1 : 0)
  }
  parts.push(children.slice(at))
  return <>{parts}</>
}
