/**
 * K-belge-ciktilari: the document viewer's own script, in /office/viewer.html - a frame of no origin (`sandbox="allow-scripts"`)
 * whose page loads nothing but its own files and fetches nothing (`app.views.VIEWER_HEADERS`). The app reads the file and
 * posts its bytes in; this draws a Word document, a workbook or a slide deck, and says it drew it or why not.
 * shortcut: npm audit names an XSS in echarts (pptx-preview's charts) and a moderate one in uuid. Both run here only, in no
 * origin, holding no data but the file's own: a hostile file can still send the frame itself to an address of the web - a
 * beacon that it was opened (the app takes the frame off at its second load, after that request). Upgrade when pptx-preview
 * takes a fixed echarts.
 */
import { renderAsync } from 'docx-preview'
import { init } from 'pptx-preview'
import { read, utils } from 'xlsx'

export type OfficeKind = 'docx' | 'xlsx' | 'pptx'
/** What the app posts: the file's kind and bytes. */
export interface Asked {
  kind: OfficeKind
  data: ArrayBuffer
}
/** What the frame says back. */
export type Said = { shown: true } | { failed: string }

/** A sheet is drawn to this many rows; the rest is said, not drawn. */
export const MOST_ROWS = 1000

export async function draw({ kind, data }: Asked, into: HTMLElement): Promise<void> {
  into.replaceChildren()
  if (kind === 'docx') {
    // (Its pictures and fonts as data: URLs - the page's policy takes no blob: font.)
    await renderAsync(data, into, undefined, { useBase64URL: true, breakPages: true })
  } else if (kind === 'xlsx') {
    const book = read(data, { type: 'array', sheetRows: MOST_ROWS })
    for (const name of book.SheetNames) {
      const sheet = book.Sheets[name]
      const title = document.createElement('h2')
      title.className = 'sheet-name'
      title.textContent = name
      const table = document.createElement('div')
      table.className = 'sheet'
      // (SheetJS writes each cell's text escaped; and nothing here runs a script the page did not bring.)
      table.innerHTML = utils.sheet_to_html(sheet, { header: '', footer: '' })
      into.append(title, table)
      if (sheet['!fullref'] && sheet['!fullref'] !== sheet['!ref']) {
        const more = document.createElement('p')
        more.className = 'sheet-more'
        more.textContent = `Only its first ${MOST_ROWS} rows are shown.`
        into.append(more)
      }
    }
  } else {
    const width = Math.max(320, into.clientWidth || document.documentElement.clientWidth)
    await init(into, { width, height: Math.round((width * 9) / 16), mode: 'list' }).preview(data)
  }
}

/** Hears the app - its parent alone, of the origin this page is served from - and draws what it posts. */
export function listen(into: HTMLElement): void {
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== new URL(location.href).origin || !event.data || typeof event.data !== 'object') return
    const asked = event.data as Asked
    if (!['docx', 'xlsx', 'pptx'].includes(asked.kind) || !(asked.data instanceof ArrayBuffer)) return
    // (Its address's origin - the app's - though the page itself is of no origin; not `location.origin`, which a browser may say as 'null'.)
    const tell = (said: Said) => window.parent.postMessage(said, new URL(location.href).origin)
    draw(asked, into).then(
      () => tell({ shown: true }),
      error => tell({ failed: error instanceof Error ? error.message : String(error) }),
    )
  })
}

const into = typeof document !== 'undefined' ? document.getElementById('document') : null
if (into) listen(into)
