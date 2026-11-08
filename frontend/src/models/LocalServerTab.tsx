import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { LocalServer, LocalServerConfig } from '../api/types'

export type ServerAction = 'start' | 'stop' | 'restart'

/** The flags the form has a box for (the first spelling is the one written); every other argument stays in Advanced. */
const FIELDS = [
  ['model', 'Model', ['-m', '--model']],
  ['ctx', 'Context (-c)', ['-c', '--ctx-size']],
  ['ngl', 'GPU layers (-ngl)', ['-ngl', '--gpu-layers', '--n-gpu-layers']],
  ['effort', 'Default thinking', ['--reasoning-effort']],
  ['temp', 'Temperature', ['--temp']],
  ['topP', 'Top-p', ['--top-p']],
  ['topK', 'Top-k', ['--top-k']],
  ['minP', 'Min-p', ['--min-p']],
] as const
type Field = (typeof FIELDS)[number][0]
export type ServerForm = Record<Field, string> & { advanced: string }

/** A command line's words: spaces part them, double quotes keep a path with spaces whole, backslashes stay as written. */
export const words = (line: string) => [...line.matchAll(/(?:"[^"]*"|[^\s"])+/g)].map(m => m[0].replace(/"/g, ''))
// shortcut: an argument with a double quote in it is not written back as itself; no llama-server argument has one.
const quoted = (word: string) => (word === '' || /\s/.test(word) ? `"${word}"` : word)

/** The arguments as the form shows them: each box's flag (its last, as llama-server reads it) and the word after it, the rest in order. */
export function toForm(args: string[]): ServerForm {
  const form = { advanced: '', ...Object.fromEntries(FIELDS.map(([field]) => [field, ''])) } as ServerForm
  const taken = new Map<number, Field>()
  for (const [field, , flags] of FIELDS) {
    const at = args.findLastIndex((arg, i) => (flags as readonly string[]).includes(arg) && i + 1 < args.length)
    if (at >= 0) taken.set(at, field)
  }
  const rest: string[] = []
  for (let at = 0; at < args.length; at++) {
    const field = taken.get(at)
    if (field) form[field] = args[++at]
    else rest.push(args[at])
  }
  form.advanced = rest.map(quoted).join(' ')
  return form
}

/** The form back into arguments: Advanced as written, then each box that is filled. */
export const toArgs = (form: ServerForm) => [
  ...words(form.advanced),
  ...FIELDS.flatMap(([field, , [flag]]) => (form[field].trim() ? [flag, form[field].trim()] : [])),
]

const gb = (mib: number | null) => (mib === null ? '–' : `${(mib / 1024).toFixed(1)} GB`)

function stateText(told: LocalServer): string {
  if (told.state === 'exited') return `Ended by itself (exit code ${told.exit_code})`
  if (told.state === 'stopped') return 'Stopped'
  return `Running · ${told.model ?? 'loading…'} · n_ctx ${told.n_ctx?.toLocaleString('en-US') ?? '–'}`
}

function gpuOf({ gpu }: LocalServer): string {
  if (!gpu) return 'GPU –'
  return `GPU memory ${gb(gpu.memory_used)} / ${gb(gpu.memory_total)} · load ${gpu.load === null ? '–' : `${gpu.load}%`} · llama-server ${gb(gpu.share)}`
}

const POLL_MS = 3000

/**
 * The model server on this machine (slice 64): started, stopped and set only here, by your buttons - never when KOLONİ
 * opens, never by an agent. While it runs (and this tab is open) it is read again every few seconds.
 */
export function LocalServerTab({
  active,
  onRead,
  onRun,
}: {
  /** Whether its tab is the one open: only then is it read again. */
  active: boolean
  onRead: () => Promise<LocalServer>
  /** Start and Restart keep the form's program and arguments first; Stop sends none. */
  onRun: (action: ServerAction, config?: LocalServerConfig) => Promise<LocalServer>
}) {
  const [told, setTold] = useState<LocalServer | null>(null)
  const [exe, setExe] = useState<string | null>(null)
  const [form, setForm] = useState<ServerForm | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const shown = useCallback((now: LocalServer) => {
    setTold(now)
    // The first reading fills the form; what is typed after that is the user's.
    setExe(was => was ?? now.executable)
    setForm(was => was ?? toForm(now.args))
  }, [])
  const read = useCallback(() => onRead().then(shown, err => setError(errorText(err))), [onRead, shown])
  useEffect(() => void read(), [read])
  const running = told?.state === 'running'
  useEffect(() => {
    if (!running || !active) return
    // Each reading after the last one's answer (each asks nvidia-smi), and none while the page is hidden.
    let timer: ReturnType<typeof setTimeout>
    let live = true
    const next = () => {
      timer = setTimeout(() => void (document.hidden ? Promise.resolve() : read()).finally(() => live && next()), POLL_MS)
    }
    next()
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [running, active, read])

  async function run(action: ServerAction, event?: FormEvent) {
    event?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      shown(await onRun(action, action === 'stop' || !form || exe === null ? undefined : { executable: exe.trim(), args: toArgs(form) }))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  if (!told || !form || exe === null) return error ? <div role="alert" className="alert">{error}</div> : <p className="muted">Reading…</p>
  const set = (field: keyof ServerForm) => (value: string) => setForm({ ...form, [field]: value })
  // The model named stays a choice when it is not in the folder: nothing is lost by opening the form.
  const models = form.model && !told.models.includes(form.model) ? [form.model, ...told.models] : told.models
  return (
    <form className="local-server" onSubmit={e => void run(running ? 'restart' : 'start', e)}>
      <p role="status" className="local-server-state">
        {stateText(told)}
      </p>
      {running && <p className="muted">{gpuOf(told)}</p>}
      <p className="muted provider-note">It starts only when you press Start, and stops when KOLONİ closes. No agent can start it; Start runs exactly what is shown here.</p>
      <div className="field">
        <label htmlFor="local-server-exe">Program</label>
        <input id="local-server-exe" className="input mono" value={exe} onChange={e => setExe(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="local-server-model">Model</label>
        <select id="local-server-model" className="input" value={form.model} onChange={e => set('model')(e.target.value)}>
          <option value="">None (-m not given)</option>
          {models.map(name => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <div className="local-server-fields">
        {FIELDS.slice(1).map(([field, label]) => (
          <div className="field" key={field}>
            <label htmlFor={`local-server-${field}`}>{label}</label>
            <input id={`local-server-${field}`} className="input mono" value={form[field]} onChange={e => set(field)(e.target.value)} />
          </div>
        ))}
      </div>
      <div className="field">
        <label htmlFor="local-server-advanced">Advanced: every other argument, as given</label>
        <textarea id="local-server-advanced" className="input mono" rows={3} value={form.advanced} onChange={e => set('advanced')(e.target.value)} />
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="role-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !exe.trim()}>
          {running ? 'Restart' : 'Start'}
        </button>
        {running && (
          <button type="button" className="btn" disabled={busy} onClick={() => void run('stop')}>
            Stop
          </button>
        )}
      </div>
      <details className="more">
        <summary>Server output</summary>
        <pre className="local-server-output" aria-label="Server output">
          {told.output || 'Nothing printed yet.'}
        </pre>
      </details>
    </form>
  )
}
