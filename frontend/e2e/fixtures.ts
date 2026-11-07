// What every spec imports in place of '@playwright/test' (slice 94): a spec's own calls to the API carry the
// page key, the browser's never - the page has only what the link gave it (`/#key=`, `LINK` in helpers.ts),
// so a request of the page's that forgets the key fails here as it would for the user.
import { test as base } from '@playwright/test'
import { APP_URL, PAGE_KEY } from './paths.mjs'

export * from '@playwright/test'

export const test = base.extend({
  // (`give`, not `use`: the linter takes that name for a React hook.)
  request: async ({ playwright }, give) => {
    const api = await playwright.request.newContext({ baseURL: APP_URL, extraHTTPHeaders: { 'X-KOLONI-Key': PAGE_KEY } })
    await give(api)
    await api.dispose()
  },
  // `page.request` would share the browser's headers, which carry no key: it is the one above.
  page: async ({ page, request }, give) => {
    Object.defineProperty(page, 'request', { value: request })
    await give(page)
  },
})
