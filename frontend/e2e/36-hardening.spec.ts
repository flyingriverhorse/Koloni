// Slice 36 in the browser: an image in a model's answer is not fetched before the user's own
// click; a message not sent survives another page and a hidden chat; no page of another
// origin can put the app in a frame.
import { expect, test } from './fixtures'
import { openFreshConversation, rail } from './helpers'
import { APP_URL, MODEL_URL } from './paths.mjs'

test('an image the model names is not fetched until the user clicks its address', async ({ page, context }) => {
  // Every request to the image's address, from this page or from any tab it opens.
  const asked: string[] = []
  context.on('request', request => {
    if (request.url().includes('/pixel.png')) asked.push(request.url())
  })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('show me a picture')
  await page.getByRole('button', { name: 'Send' }).click()

  const address = `${MODEL_URL}/pixel.png?carried=secret`
  const link = chat.getByRole('link', { name: address })
  await expect(link).toBeVisible()
  await expect(chat.getByText('[the chart]')).toBeVisible()
  await expect(chat.locator('img')).toHaveCount(0)
  // Everything the answer brought is on the page: had it been fetched, it would have been by now.
  await page.waitForLoadState('networkidle')
  expect(asked).toEqual([])

  // The user's own click opens it, in a tab of its own.
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  const opened = page.waitForEvent('popup')
  await link.click()
  await (await opened).waitForLoadState()
  expect(asked).toEqual([address])
})

test('a message written and not sent is there again after another page and a hidden chat', async ({ page }) => {
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('a thought not sent yet')

  await rail(page, 'Memory').click()
  await expect(page.getByLabel('Message')).toHaveCount(0) // the chat is gone with the page
  await rail(page, 'Canvas').click()
  await expect(page.getByLabel('Message')).toHaveValue('a thought not sent yet')

  await page.getByRole('button', { name: 'Hide chat' }).click()
  // (closed, the chat is a small box: the draft is in its one line - slice 38e)
  await expect(page.getByRole('tab', { name: 'Chat' })).toBeHidden()
  await expect(page.getByLabel('Message')).toHaveValue('a thought not sent yet')
  await page.getByRole('button', { name: /^Chat\b/ }).click() // its closed line
  await expect(page.getByLabel('Message')).toHaveValue('a thought not sent yet')
})

test('a page of another origin on this machine cannot put the app in a frame', async ({ page }) => {
  // A page served as if from the stand-in model's origin: another port, so another origin.
  const outside = `${MODEL_URL}/framing.html`
  // Beside it, for a measure, a frame of an address that says nothing against it.
  const allowed = `${MODEL_URL}/v1/models`
  await page.route(outside, route =>
    route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><iframe name="app" src="${APP_URL}/"></iframe><iframe name="other" src="${allowed}"></iframe>`,
    }),
  )
  await page.goto(outside)
  const frame = (name: string) => page.frames().find(one => one.name() === name)?.url()
  await expect.poll(() => frame('other')).toBe(allowed)
  // The browser refuses the app's: an error page stands in the frame, nothing of the app.
  await expect.poll(() => frame('app')).toMatch(/^chrome-error:/)
  // What it was refused by: the app's own answer says so.
  const answer = await page.request.get(`${APP_URL}/`)
  expect(answer.headers()['content-security-policy']).toContain("frame-ancestors 'none'")
  expect(answer.headers()['x-frame-options']).toBe('DENY')
})
