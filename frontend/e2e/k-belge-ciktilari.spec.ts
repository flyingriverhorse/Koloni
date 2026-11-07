// K-belge-ciktilari in the browser: a Word document and a workbook of the project open in the Workspace on the document
// viewer, in a sandboxed frame of no origin - drawn, with nothing refused by its policy and nothing asked of any address
// but the app's own.
import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import JSZip from 'jszip'
import { utils, write } from 'xlsx'
import { expect, test, type Page } from './fixtures'
import { openFreshConversation } from './helpers'
import { APP_URL, PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const DOCX = path.join(PROJECT_DIR, 'plan-k-belge.docx')
const XLSX = path.join(PROJECT_DIR, 'sums-k-belge.xlsx')
const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const R = 'http://schemas.openxmlformats.org/package/2006/relationships'

/** The smallest Word document: one paragraph. */
async function docx(text: string): Promise<Buffer> {
  const zip = new JSZip()
  zip.file(
    '[Content_Types].xml',
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
  )
  zip.file('_rels/.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${R}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`)
  zip.file('word/_rels/document.xml.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${R}"></Relationships>`)
  zip.file('word/document.xml', `<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="${W}"><w:body><w:p><w:r><w:t>${text}</w:t></w:r></w:p></w:body></w:document>`)
  return zip.generateAsync({ type: 'nodebuffer' })
}

function xlsx(): Buffer {
  const book = utils.book_new()
  utils.book_append_sheet(book, utils.aoa_to_sheet([['item', 'total'], ['apples', 12]]), 'Sums')
  return write(book, { type: 'buffer', bookType: 'xlsx' })
}

const filesOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })

test.beforeEach(async () => {
  writeFileSync(DOCX, await docx('Hello from a Word document'))
  writeFileSync(XLSX, xlsx())
})
test.afterEach(() => [DOCX, XLSX].forEach(file => rmSync(file, { force: true })))

test('a .docx and an .xlsx open on the document viewer, in a frame of no origin; nothing refused, nothing asked outside', async ({ page }) => {
  test.setTimeout(60_000)
  const answered: string[] = []
  const refused: string[] = []
  page.on('response', response => answered.push(response.url()))
  page.on('console', message => /Content Security Policy|Refused to|EvalError/i.test(message.text()) && refused.push(message.text()))
  await openFreshConversation(page)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  const files = filesOf(page)
  const tree = files.getByRole('tree', { name: 'Files' })
  const frame = page.frameLocator('.view-panel iframe')

  await tree.getByRole('treeitem', { name: 'plan-k-belge.docx' }).click()
  await expect(files.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(files.locator('iframe')).toHaveAttribute('src', '/office/viewer.html')
  await expect(frame.getByText('Hello from a Word document')).toBeVisible({ timeout: 15_000 })

  await tree.getByRole('treeitem', { name: 'sums-k-belge.xlsx' }).click()
  await expect(frame.getByRole('heading', { name: 'Sums' })).toBeVisible({ timeout: 15_000 })
  await expect(frame.getByRole('cell', { name: 'apples' })).toBeVisible()

  expect(refused).toEqual([])
  const outside = (url: string) => !url.startsWith(`${APP_URL}/`) && !/^(data|blob):/.test(url)
  expect(answered.filter(outside)).toEqual([])
  expect(answered.some(url => url.startsWith(`${APP_URL}/office/viewer.js`))).toBe(true)
})
