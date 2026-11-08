// K-drawio in the browser: a .drawio file of the project opens in the Workspace on the vendored draw.io viewer, in a
// sandboxed frame - drawn, with its pages. The viewer itself asks nothing of any address but the app's own; what a
// diagram names elsewhere (a picture, a font on the web) is tried by the page and refused by its policy before it is
// sent - no answer comes from outside the app. Save as PNG writes the picture beside it.
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { openFreshConversation } from './helpers'
import { APP_URL, PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const DIAGRAM = path.join(PROJECT_DIR, 'flow-drawio.drawio')
const PICTURE = path.join(PROJECT_DIR, 'flow-drawio.png')
const box = (id: string, label: string, x: number) =>
  `<mxCell id="${id}" value="${label}" style="rounded=1;html=1;fillColor=#dae8fc;" vertex="1" parent="1"><mxGeometry x="${x}" y="40" width="140" height="60" as="geometry"/></mxCell>`
// A cell that names the web: a picture, and a font from a font service.
const OUTSIDE = 'https://example.com/k-drawio.png'
const FONTS = 'https://fonts.googleapis.com/css?family=Lobster'
const hostile = `<mxCell id="9" value="Web" style="shape=image;image=${OUTSIDE};fontFamily=Lobster;fontSource=${encodeURIComponent(FONTS)};" vertex="1" parent="1"><mxGeometry x="560" y="40" width="60" height="60" as="geometry"/></mxCell>`
const XML = `<mxfile><diagram id="a" name="First"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>${box('2', 'Start &lt;b&gt;here&lt;/b&gt;', 40)}${box('3', 'End', 300)}${hostile}<mxCell id="4" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel></diagram><diagram id="b" name="Second"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>${box('5', 'Page two', 40)}</root></mxGraphModel></diagram></mxfile>`
const filesOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })

test.beforeEach(() => writeFileSync(DIAGRAM, XML))
test.afterEach(() => [DIAGRAM, PICTURE].forEach(file => rmSync(file, { force: true })))

test('a .drawio opens on the viewer, drawn with its pages; what it names on the web is refused before it is sent; Save as PNG writes it beside', async ({ page }) => {
  test.setTimeout(60_000)
  const requests: string[] = []
  const answered: string[] = []
  const refused: string[] = []
  page.on('request', request => requests.push(request.url()))
  page.on('response', response => answered.push(response.url()))
  page.on('console', message => /Content Security Policy|Refused to/i.test(message.text()) && refused.push(message.text()))
  await openFreshConversation(page)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  const files = filesOf(page)
  const item = files.getByRole('tree', { name: 'Files' }).getByRole('treeitem', { name: 'flow-drawio.drawio' })
  await expect(item).toBeVisible({ timeout: 10_000 })
  await item.click()
  const frame = page.frameLocator('.view-panel iframe')
  await expect(files.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  // drawn: its shapes in the viewer's SVG, and its page count in the viewer's own toolbar
  await expect(frame.locator('svg').getByText('End', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(frame.getByText('1 / 2')).toBeVisible()
  // (a blank frame of this size is a PNG of under 1 KB)
  const shot = await files.locator('iframe').screenshot({ path: test.info().outputPath('drawn.png') })
  expect(shot.length).toBeGreaterThan(2_000)

  await files.getByRole('button', { name: 'Save as PNG' }).click()
  await expect(files.getByRole('status')).toHaveText('Saved as flow-drawio.png.', { timeout: 10_000 })
  expect(existsSync(PICTURE)).toBe(true)
  expect(readFileSync(PICTURE).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')

  // Every answer came from the app (the viewer's files, the file's text, the API) or carried its data in itself.
  const outside = (url: string) => !url.startsWith(`${APP_URL}/`) && !/^(data|blob):/.test(url)
  expect(answered.filter(outside)).toEqual([])
  expect(requests.some(url => url.startsWith(`${APP_URL}/drawio/viewer-static.min.js`))).toBe(true)
  // The page tried only what the diagram names - the picture and the font - and its policy refused both. (Playwright
  // lists a request the policy refuses before it is sent: the log alone is no proof, the refusal is.)
  expect(new Set(requests.filter(outside).map(url => new URL(url).host))).toEqual(new Set(['example.com', 'fonts.googleapis.com']))
  expect(refused.some(line => line.includes(OUTSIDE))).toBe(true)
  expect(refused.some(line => line.includes('fonts.googleapis.com'))).toBe(true)
  expect(refused.every(line => line.includes(OUTSIDE) || line.includes('fonts.googleapis.com'))).toBe(true)
})
