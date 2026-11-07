import { expect, test, type Page } from './fixtures'
import { contrasts, openFreshConversation, OWN, rail, shot } from './helpers'

// Slice 74: an MCP server added by pasting the block from its README. Nothing is started or
// downloaded, and the token in the block is never on the page once it is read.
test.use({ viewport: { width: 1440, height: 900 } })

const TOKEN = 'ghp_e2eFakeToken0123456789'
// JSONC as READMEs write it (slice 74c): a comment and a trailing comma, read and masked like JSON.
const BLOCK = `// Claude Desktop\n${JSON.stringify(
  {
    mcpServers: {
      github: { command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: TOKEN } },
      fetch: { command: 'uvx', args: ['mcp-server-fetch'] },
    },
  },
  null,
  2,
).replace(/\n}$/, ',\n}')}`

/** The token is nowhere in the page: not its text, not a field's value, not an attribute. */
async function nowhere(page: Page) {
  expect(await page.content()).not.toContain(TOKEN)
  const values = await page.locator('input, textarea').evaluateAll(fields => fields.map(field => (field as HTMLInputElement).value))
  expect(values.join('\n')).not.toContain(TOKEN)
}

for (const theme of ['light', 'dark'] as const)
  test(`a pasted block: compact cards, one opened, the token never shown, one server added and nothing started (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // One of the two is already added.
    expect((await request.post('/api/mcp-servers', { headers: OWN, data: { name: 'fetch', command: ['uvx', 'mcp-server-fetch'] } })).status()).toBe(201)
    try {
      await openFreshConversation(page)
      await rail(page, 'Tools').click()
      // One layout (slice 74b): the heading row stays where it is, whatever is open, and the page never splits.
      const heading = page.getByRole('heading', { name: 'Tools' })
      const at = async () => JSON.stringify(await heading.boundingBox())
      // (Once its fonts are in: drawn in the fallback font first, its width moved by 2px as the font came - 46.8 vs 48.7.)
      await heading.evaluate(async shown => {
        shown.getBoundingClientRect() // (laid out: the fonts it needs are asked for)
        await document.fonts.ready
      })
      const first = await at()
      await expect(page.locator('.agents-page, .agents-list, .composer-warning')).toHaveCount(0)
      await expect(page.getByText('How this works')).toHaveCount(0)
      // each way from the Add menu (0.1.0-ui)
      const way = async (name: RegExp) => {
        await page.getByRole('button', { name: 'Add', exact: true }).click()
        await page.getByRole('menuitem', { name }).click()
      }
      for (const name of [/^A server, by hand/, /^A server, ready-made/, /^A server, from its page/]) {
        await way(name)
        expect(await at()).toBe(first)
      }
      const text = page.getByRole('textbox', { name: '1 · What you pasted' })
      // A paste event as the browser sends one, without the machine's clipboard, which is the user's.
      await text.focus()
      await text.evaluate((box, block) => {
        const data = new DataTransfer()
        data.setData('text/plain', block)
        box.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data }))
      }, BLOCK)
      await expect(text).toHaveValue(/"GITHUB_PERSONAL_ACCESS_TOKEN": "••••••••"/)
      await nowhere(page)

      const panel = page.getByRole('region', { name: 'A server, from its page' })
      const card = (name: string) => panel.getByRole('button', { name: new RegExp(`^${name}`) })
      await expect(card('github')).toHaveAttribute('aria-expanded', 'false')
      await expect(card('github')).toContainText('npx … server-github')
      await expect(card('github')).toContainText('new')
      await expect(card('github')).toContainText('key kept secret')
      await expect(card('github')).toContainText('downloads on first read')
      await expect(card('fetch')).toContainText('already added — will be skipped')
      await expect(panel.getByRole('checkbox', { name: 'Add fetch' })).toBeDisabled()
      // what was pasted and what was read, side by side
      const [left, right] = [await text.boundingBox(), await panel.getByRole('heading', { name: '2 · What KOLONİ read from it' }).boundingBox()]
      expect(right!.x).toBeGreaterThan(left!.x + left!.width - 1)
      await shot(page, `74-paste-${theme}`)

      await card('github').click()
      await expect(card('github')).toHaveAttribute('aria-expanded', 'true')
      const body = panel.locator(`#${await card('github').getAttribute('aria-controls')}`)
      await expect(body.getByText('The token was in what you pasted:')).toBeVisible()
      await expect(body.getByText('Downloads on first read:')).toBeVisible()
      await expect(body).toContainText('GITHUB_PERSONAL_ACCESS_TOKEN kept secret')
      await nowhere(page)
      await shot(page, `74-paste-open-${theme}`)
      const all = await panel.evaluate(contrasts)
      expect(all.length).toBeGreaterThan(15)
      expect(all.filter(piece => piece.ratio < 4.5)).toEqual([])

      // At 900 px nothing scrolls sideways; narrower still, the two are one under the other, and nothing scrolls sideways.
      await page.setViewportSize({ width: 900, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
      expect(await page.locator('.tools-page').evaluate(box => box.scrollWidth > box.clientWidth)).toBe(false)
      await page.setViewportSize({ width: 720, height: 900 })
      const [narrowLeft, narrowRight] = [await text.boundingBox(), await panel.getByRole('heading', { name: '2 · What KOLONİ read from it' }).boundingBox()]
      expect(narrowRight!.y).toBeGreaterThan(narrowLeft!.y + narrowLeft!.height - 1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
      await page.setViewportSize({ width: 1440, height: 900 })

      // "Edit before adding": the form filled, the token in its secret field's value only - not in the markup.
      await panel.getByRole('button', { name: 'Edit before adding' }).click()
      const hand = page.getByRole('region', { name: 'A server, by hand' })
      await expect(hand.getByLabel('Name', { exact: true })).toHaveValue('github')
      await expect(hand.getByLabel('Value 1', { exact: true })).toHaveValue(TOKEN)
      expect(await page.content()).not.toContain(TOKEN)
      await shot(page, `74-hand-${theme}`)
      const handAll = await hand.evaluate(contrasts)
      expect(handAll.filter(piece => piece.ratio < 4.5)).toEqual([])
      // back to what was pasted, as it was left
      await way(/^A server, from its page/)
      await expect(card('github')).toHaveAttribute('aria-expanded', 'true')

      await panel.getByRole('button', { name: 'Add 1 server' }).click()
      // Added: the server is shown, its variable by name only, its tools not read - nothing was started.
      await expect(page.getByRole('region', { name: /^A server/ })).toHaveCount(0)
      const form = page.locator('form.tools-editor')
      await form.getByRole('button', { name: 'Edit', exact: true }).click()
      await expect(form.getByLabel('Name', { exact: true })).toHaveValue('github')
      await expect(form.getByLabel('New value of GITHUB_PERSONAL_ACCESS_TOKEN')).toHaveValue('')
      await expect(page.getByText(/Its tools have not been read yet: no agent is offered any\./)).toBeVisible()
      await nowhere(page)
      // the server open under its row, across the page; the heading where it was, the tab's one line over the list
      expect(await at()).toBe(first)
      await expect(page.getByRole('button', { name: /^github/ })).toHaveAttribute('aria-expanded', 'true')
      expect((await form.boundingBox())!.width).toBeGreaterThan(1000)
      await expect(page.locator('#tools-panel-servers .tools-lead')).toContainText('Programs that give agents more tools.')
      await shot(page, `74b-server-open-${theme}`)
      const serverAll = await page.locator('.tools-page').evaluate(contrasts)
      expect(serverAll.filter(piece => piece.ratio < 4.5)).toEqual([])
      const servers: { name: string; command: string[]; env_names: string[]; read_at: string | null; tools: unknown[] }[] = await (
        await request.get('/api/mcp-servers')
      ).json()
      expect(servers.map(s => s.name)).toEqual(['fetch', 'github'])
      expect(servers[1]).toMatchObject({ command: ['npx', '-y', '@modelcontextprotocol/server-github'], env_names: ['GITHUB_PERSONAL_ACCESS_TOKEN'], read_at: null, tools: [] })
      expect(servers[0]).toMatchObject({ read_at: null, tools: [] })
    } finally {
      // Put back, so that the specs after start from an empty Tools page.
      for (const { id } of (await (await request.get('/api/mcp-servers')).json()) as { id: string }[])
        await request.delete(`/api/mcp-servers/${id}`, { headers: OWN })
    }
  })
