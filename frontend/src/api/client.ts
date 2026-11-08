export class ApiError extends Error {
  status: number
  detail: string
  /** The server's `detail` as it was sent: a list says where each refusal is (a recipe's step, slice 84a). */
  raw: unknown

  constructor(status: number, detail: string, raw?: unknown) {
    super(detail)
    this.status = status
    this.detail = detail
    this.raw = raw
  }
}

/**
 * The server's word that a turn waits for the user's - over the project's month budget (slice 55), or over the
 * limit of the provider its Lead runs on (81c) - in the words to ask with: asked, not failed. Null for anything else.
 */
export function overWhat(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  // The server's own sentence, whole: a provider's name ("Budget box") is never taken for the budget.
  const said = /^this project is (over this month's budget|over .+'s limit of [\d.]+ \S+ a (?:day|month) \(.+ spent (?:today|this month)\))(?: \(.*\))?(?:: say to go on over it)?$/.exec(err.message)
  if (!said) return null
  return said[1] === "over this month's budget" ? 'Over this month’s budget' : `O${said[1].slice(1)}`
}

/**
 * A refusal that names fields (the server's own check of what was sent): "budget.steps:
 * Input should be less than or equal to 200". Null when it is not of that kind.
 */
function fieldErrors(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null
  const lines = detail.map(item => {
    const { loc, msg } = (item ?? {}) as { loc?: unknown; msg?: unknown }
    const where = Array.isArray(loc) ? loc.filter(part => part !== 'body').join('.') : ''
    return typeof msg === 'string' ? (where ? `${where}: ${msg}` : msg) : null
  })
  return lines.every(line => line !== null) ? lines.join('; ') : null
}

const KEY = 'koloni-key'
// Where the browser keeps nothing: the key this page was opened with, for as long as it is open.
let held: string | null = null

/**
 * The key the link in KOLONİ's window opened the page with (`#key=`, slice 94): kept, and taken out of the address.
 * shortcut: the key stops a plain or prompt-injected curl or script, not a deliberate agent running as the same OS user - that one can
 * read the console, Chrome's command line, its Local Storage on disk, process memory or koloni.db; upgrade by running agents under
 * another OS user or in the Docker executor.
 * A page KOLONİ opened in the browser itself has `#open=` instead: a one-time code, exchanged here for the key (the browser's
 * command line keeps its address, where an agent's command can read it).
 */
export async function takeKey(): Promise<void> {
  // (Only the page itself: a page that frames KOLONİ cannot hand it a key of its choosing.)
  if (window.top !== window) return
  const hash = new URLSearchParams(location.hash.slice(1))
  const code = hash.get('open')
  let given = hash.get('key')
  if (given && !(await takes(given))) given = null
  if (!given && code) {
    const res = await fetch('/api/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) }).catch(() => null)
    // (Refused - used, late: the page says to open it from the link in KOLONİ's window, as for any missing key.)
    given = res?.ok ? ((await res.json()) as { key: string }).key : null
  }
  if (code || hash.has('key')) history.replaceState(null, '', location.pathname + location.search)
  if (!given) return
  held = given
  try {
    localStorage.setItem(KEY, given)
  } catch {
    // (kept in `held` only)
  }
}

/**
 * denetim-010 #20: whether a `#key=` may replace the key the page keeps - any link can carry one (a web page, a model's answer), and
 * a wrong one kept would refuse every request. Yes where none is kept or it is the same; else only once the server takes it.
 */
async function takes(given: string): Promise<boolean> {
  const kept = pageKey()
  if (!kept || kept === given) return true
  // (Not through `send`: its 401 would show the whole page as refused. Any answer but a yes - KOLONİ not reached, slow, a proxy's
  // 500 - keeps the kept one.)
  const res = await fetch('/api/answer-in', { headers: { 'X-KOLONI-Key': given }, signal: AbortSignal.timeout(5000) }).catch(() => null)
  return !!res?.ok
}

function pageKey(): string | null {
  try {
    return localStorage.getItem(KEY) ?? held
  } catch {
    return held
  }
}

/** The page's key as a request to the API carries it: nothing where there is none. */
export function keyHeader(): Record<string, string> {
  const key = pageKey()
  return key ? { 'X-KOLONI-Key': key } : {}
}

/**
 * An address of the API with the page's key in it, only where a header cannot go: an event stream, an image's or a video's source - none
 * of which the browser keeps in its history. A download goes by `download` instead: its address would stay in the list of downloads.
 * (A video's controls offer no Download: `Attach`.)
 * shortcut: an image or video the user opens in a tab of its own puts the key in history, and one saved from its menu ("Save image
 * as…", "Save video as…") in the list of downloads; load them as blobs if that is seen.
 */
export function withKey(address: string): string {
  const key = pageKey()
  return key ? `${address}${address.includes('?') ? '&' : '?'}key=${encodeURIComponent(key)}` : address
}

// Once a request was refused for want of the key, the page can do nothing more: App shows a note instead.
let refused = false
const told = new Set<() => void>()
export const keyRefused = {
  subscribe(listener: () => void) {
    told.add(listener)
    return () => void told.delete(listener)
  },
  now: () => refused,
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await send(method, path, body, signal)
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

/**
 * A file of the API saved as a download, under the name its answer gives: fetched with the key in its header, never in an address the
 * browser keeps (its history, its list of downloads). A POST says its origin, as an export needs. A refusal throws, as any request's.
 * shortcut: the whole file is held in the page's memory until it is saved; stream it to disk if an export ever grows past that.
 */
export async function download(method: 'GET' | 'POST', path: string): Promise<void> {
  const res = await send(method, path)
  const url = URL.createObjectURL(await res.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? 'download'
  link.click()
  // (Later, not now: a browser may still be reading it when the click returns.)
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  // A file goes as the body itself (an attachment, slice 85b): never as JSON.
  const file = body instanceof Blob
  const res = await fetch(`/api${path}`, {
    method,
    headers: { ...keyHeader(), ...(body !== undefined && !file && { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : file ? body : JSON.stringify(body),
    // (Only where one is given: a request that may be given up.)
    ...(signal && { signal }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    const detail = typeof data?.detail === 'string' ? data.detail : (fieldErrors(data?.detail) ?? `${res.status} ${res.statusText}`)
    // (Only the key is asked with a 401: the server's other refusals are 403s.)
    if (res.status === 401 && !refused) {
      refused = true
      told.forEach(listener => listener())
    }
    throw new ApiError(res.status, detail, data?.detail)
  }
  return res
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  /** One file, as the request's body. */
  upload: <T>(path: string, file: Blob) => request<T>('POST', path, file),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  delete: (path: string) => request<void>('DELETE', path),
}

/** The message to show a person for any thrown value. */
export function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error) return String(error.detail)
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
