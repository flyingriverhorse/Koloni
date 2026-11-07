import http from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, type Page, test } from './fixtures'
import { chatSheet, e2eProject, openFreshConversation, OWN, shot } from './helpers'

// K-tarayici-disari: the agent's browser opens outside sites the user allows. A site is a name of a test's own (*.test)
// for a server of this spec's on loopback: the stand-in browser (KOLONI_BROWSER_FAKE) takes it there, and the backend
// asks no DNS of it (KOLONI_E2E_NAMES). Nothing leaves the machine.
const DOCS = '<!doctype html><html><head><title>Docs page</title></head><body><h1>Docs</h1></body></html>'
const ORDER = '<!doctype html><html><head><title>Order</title></head><body><form method="post" action="/order"><button>Send order</button></form></body></html>'

let server: http.Server
let port = 0

test.beforeAll(async () => {
  server = http.createServer((asked, answer) => {
    answer.writeHead(200, { 'Content-Type': 'text/html' })
    answer.end(asked.url === '/order' ? ORDER : DOCS)
  })
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done))
  port = (server.address() as AddressInfo).port
})

test.afterAll(() => new Promise<void>(done => server.close(() => done())))

// The sites are the project's, which every spec shares: none is left for the next.
test.afterEach(async ({ page }) => {
  const sites = await page.request.get(`/api/projects/${await e2eProject(page)}/sites`, { headers: OWN })
  for (const site of await sites.json()) await page.request.delete(`/api/allowed-web/${site.id}`, { headers: OWN })
})

async function level(page: Page, id: string, mode: 'auto_edit' | 'full_auto') {
  const set = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: mode }, headers: OWN })
  expect((await set.json()).permission_mode).toBe(mode)
}

test('at Auto-edit an unlisted site is a card: This time keeps nothing, Allow this site lists it for the project', async ({ page }) => {
  const id = await openFreshConversation(page)
  await level(page, id, 'auto_edit')
  await page.getByLabel('Message').fill(`k-tarayici-disari open http://site.test:${port}/ http://other.test:${port}/`)
  await page.getByRole('button', { name: 'Send' }).click()

  const chat = page.getByRole('region', { name: 'Chat' })
  const card = chat.locator('.cmd-approval').filter({ hasText: 'Open this site?' })
  await expect(card).toContainText('site.test', { timeout: 20_000 })
  await shot(card, 'k-tarayici-disari-site-card')
  await card.getByRole('button', { name: 'This time' }).click()
  await expect(card).toContainText('other.test', { timeout: 20_000 })
  await card.getByRole('button', { name: 'Allow this site' }).click()
  await expect(chat.getByText('Opened the sites.')).toBeVisible({ timeout: 20_000 })

  // The chat's link to what runs without asking (⚙ Chat) opens Settings › This project › Runs without asking (tek-ev): the
  // project's sites first - other.test alone, with its Ask first mark; one is added by hand, a refused one says why.
  await (await chatSheet(page)).getByRole('button', { name: '1 run without asking →' }).click()
  const sites = page.getByRole('form', { name: 'Project settings' }).getByRole('region', { name: 'Sites agents open' })
  const mark = sites.getByRole('checkbox', { name: 'Ask first for other.test' })
  await expect(mark).not.toBeChecked()
  await expect(sites.getByText('site.test', { exact: true })).toHaveCount(0)
  await mark.click()
  await expect(mark).toBeChecked()
  const host = sites.getByLabel('Allow a site')
  await host.fill('printer')
  await sites.getByRole('button', { name: 'Allow site' }).click()
  await expect(sites.getByRole('alert')).toContainText('printer is on this machine or its network')
  await host.fill('third.test')
  await sites.getByRole('button', { name: 'Allow site' }).click()
  await expect(sites.getByRole('checkbox', { name: 'Ask first for third.test' })).not.toBeChecked()
  await shot(sites, 'k-tarayici-disari-project-sites')
  await sites.getByRole('button', { name: 'Remove site third.test' }).click()
  await expect(sites.getByText('third.test')).toHaveCount(0)
  await expect(sites.getByText('other.test')).toBeVisible()
})

test('at Full auto an unlisted site opens unasked, but sending its form waits on a card', async ({ page }) => {
  const id = await openFreshConversation(page)
  await level(page, id, 'full_auto')
  await page.getByLabel('Message').fill(`k-tarayici-disari order http://shop.test:${port}/order`)
  await page.getByRole('button', { name: 'Send' }).click()

  const chat = page.getByRole('region', { name: 'Chat' })
  const card = chat.locator('.cmd-approval').filter({ hasText: 'Send this form?' })
  await expect(card).toContainText('shop.test', { timeout: 20_000 })
  await expect(card).toContainText('Send order')
  await expect(chat.getByText('Open this site?')).toHaveCount(0)
  await shot(card, 'k-tarayici-disari-form-card')
  await card.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('The order was not sent.')).toBeVisible({ timeout: 20_000 })
  // (Full auto's open put nothing on the list.)
  const sites = await page.request.get(`/api/projects/${await e2eProject(page)}/sites`, { headers: OWN })
  expect(await sites.json()).toEqual([])
})
