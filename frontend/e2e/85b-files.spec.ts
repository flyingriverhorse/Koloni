// Slice 85b in the browser: a picture and a code file added from the 📎's file input and a link
// in the words are chips before anything is sent; sent, the message shows them, the Lead hands
// the code file to a Coder by its name, and the canvas puts both files beside the request, the
// code file dashed to the Coder - a click opens what was attached. In both themes.
import { expect, test, type Page } from './fixtures'
import { contrasts, OWN, openFreshConversation, settled, shot, setProject } from './helpers'

test.use({ viewport: { width: 1440, height: 1400 } })

// A PNG of one pixel, and a few lines of code.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')
const CODE = Buffer.from('export function pay() {\n  // waits for the banner\n}\n')

for (const theme of ['light', 'dark'] as const) {
  test(`files and a link are chips, go with the message, and stand on the canvas (${theme})`, async ({ page }: { page: Page }) => {
    await page.addInitScript(theme => localStorage.setItem('koloni-theme', theme), theme)
    const id = await openFreshConversation(page)
    // (The Lead's sub-agent opens without a card: what is looked at here is the file it is handed.)
    await setProject(page, { spawn_approval: 'never' })

    // The 📎 offers the three ways.
    await page.getByRole('button', { name: 'Attach' }).click()
    await expect(page.getByRole('menuitem')).toHaveText(['Files from this computer…', /A screenshot from the clipboard/, 'A file of the project…'])
    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu')).toHaveCount(0)

    await page.locator('.att-menu-box input[type=file]').setInputFiles([
      { name: 'shot85b.png', mimeType: 'image/png', buffer: PNG },
      { name: 'cart85b.ts', mimeType: 'text/plain', buffer: CODE },
    ])
    await page.getByLabel('Message').fill('fix the cart, 85b - see https://stripe.com/docs')
    const chips = page.getByRole('list', { name: 'Attached' })
    await expect(chips.getByRole('listitem')).toHaveText([
      'PNGshot85b.pngimage · 70 B · seen by a model that sees images',
      '.tscart85b.tscode · 52 B · 3 lines',
      'URLstripe.com/docsa link · read only if an agent asks',
    ])
    await expect(page.getByText('2 attached · 122 B')).toBeVisible()
    // (Files added, Send stays on the level's line.)
    const [level, send] = await Promise.all([page.getByLabel('Permission level'), page.getByRole('button', { name: 'Send' })].map(async c => (await c.boundingBox())!.y))
    expect(send).toBe(level)
    expect((await page.locator('.composer').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    if (process.env.KOLONI_SHOTS) await shot(page.locator('.composer'), `85b-composer-${theme}`)

    await page.getByRole('button', { name: 'Send' }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByText('cart85b.ts: the click handler waits for the banner → Coder')).toBeVisible({ timeout: 20_000 })
    const bubble = chat.locator('.msg-user .msg-bubble').last()
    await expect(bubble.locator('.att-mini')).toHaveText(['PNGshot85b.png', '.tscart85b.ts', 'URLstripe.com/docs'])
    await expect(chips).toHaveCount(0) // (gone with the message)
    expect((await bubble.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    if (process.env.KOLONI_SHOTS) await shot(chat, `85b-chat-${theme}`)

    // The canvas: both files beside the request; the code file dashed to the Coder it went to.
    const files = page.locator('.react-flow__node-attachment')
    await expect(files).toHaveCount(2)
    await expect(files.locator('.node-title')).toHaveText(['shot85b.png', 'cart85b.ts'])
    await expect(page.locator('.react-flow__edge.edge-handed')).toHaveCount(1)
    await settled(page)
    if (process.env.KOLONI_SHOTS) await shot(page.locator('.canvas'), `85b-canvas-${theme}`)
    await files.filter({ hasText: 'cart85b.ts' }).click()
    const inspector = page.getByRole('complementary', { name: 'Inspector' })
    await expect(inspector.getByText('handed to Coder')).toBeVisible()
    await expect(inspector.locator('.att-text-preview')).toContainText('export function pay()')
  })
}

// B-106: with ten files the box and Send stay in the chat; what was not added goes with the files it was refused beside;
// the project's file list closes by Esc and a click elsewhere, and what is typed while it is open goes into the box.
test('ten files keep Send in sight; "not added" goes; the project list closes and lets typing through', async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 1280, height: 771 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const many = Array.from({ length: 11 }, (_, at) => ({ name: `many${at + 1}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`file ${at + 1}\n`) }))
  await page.locator('.att-menu-box input[type=file]').setInputFiles(many)
  const chips = page.getByRole('list', { name: 'Attached' })
  await expect(chips.getByText('a message has 10 files at most: not added')).toBeVisible()
  await expect(page.getByText(/^10 attached/)).toBeVisible()
  await page.getByLabel('Message').fill('read them')
  const [send, panel] = [await page.getByRole('button', { name: 'Send' }).boundingBox(), await chat.boundingBox()]
  expect(send!.y + send!.height).toBeLessThanOrEqual(panel!.y + panel!.height)
  expect(send!.y + send!.height).toBeLessThanOrEqual(771)
  // One taken off: what was refused beside it says so no more.
  await chips.getByRole('button', { name: 'Remove many1.txt' }).click()
  await expect(chips.getByText(/not added/)).toHaveCount(0)

  // The project's list: Esc closes it; so does a click elsewhere; a key typed while it is open goes into the box.
  const list = page.getByRole('dialog', { name: 'A file of the project' })
  const open = async () => {
    await page.getByRole('button', { name: 'Attach' }).click()
    await page.getByRole('menuitem', { name: 'A file of the project…' }).click()
    await expect(list).toBeVisible()
  }
  await open()
  await page.keyboard.press('Escape')
  await expect(list).toHaveCount(0)
  await expect(chat).toBeVisible() // (the chat stays open)
  await open()
  await page.locator('.canvas-flow').click({ position: { x: 40, y: 40 } })
  await expect(list).toHaveCount(0)
  await page.getByLabel('Message').fill('')
  await open()
  await page.keyboard.type('hello')
  await expect(list).toHaveCount(0)
  await expect(page.getByLabel('Message')).toHaveValue('hello')
})
