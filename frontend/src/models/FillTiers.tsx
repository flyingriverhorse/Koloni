import { useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { TIERS, type FillAll, type FilledProvider, type Provider, type Tier } from '../api/types'

interface Props {
  providers: Provider[]
  /** Every provider's tiers proposed from the catalogue; nothing is saved. Throws ApiError. */
  onFillAll?: () => Promise<FillAll>
  /** What was shown, as the user left it, saved in one go. Throws ApiError. */
  onSaveFillAll?: (providers: FilledProvider[]) => Promise<void>
  /** The Models page's way (81a): no box, a button that is always there, and the preview in a window. */
  button?: boolean
}

/**
 * While no model has a tier every role runs on the conversation's model: a line says so at the top
 * of Agents, and its link opens one preview of every provider's tiers from the catalogue. Nothing changes
 * before Save.
 */
export function FillTiers({ providers, onFillAll, onSaveFillAll, button: asButton = false }: Props) {
  const [shown, setShown] = useState<FillAll | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Where the keyboard goes once the preview opens or closes: its heading, the box's button, or what Save said.
  // (Set with the change that opens or closes it, taken once that is drawn.)
  const focus = useRef<'preview' | 'box' | 'saved' | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const said = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (!focus.current) return
    ;({ preview: heading, box: button, saved: said })[focus.current].current?.focus()
    focus.current = null
  })
  // In its window, Esc leaves it wherever the focus is (not while it saves).
  const open = asButton && shown !== null && !busy
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      focus.current = 'box'
      setShown(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  const none = providers.length > 0 && !providers.some(p => p.models.some(m => m.tier))
  if (!onFillAll || !onSaveFillAll) return null
  if (!shown && !none && !asButton)
    return saved ? (
      <p ref={said} role="status" tabIndex={-1} className="muted provider-note fill-tiers">
        {saved}
      </p>
    ) : null

  async function act(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const change = (id: string, patch: (p: FilledProvider) => Partial<FilledProvider>) =>
    setShown(all => all && { ...all, providers: all.providers.map(p => (p.id === id ? { ...p, ...patch(p) } : p)) })
  const notes = shown?.notes ?? {}
  const setTier = (p: FilledProvider, index: number, tier: Tier | null) =>
    change(p.id, was => ({
      models: was.models.map((m, at) =>
        at !== index
          ? m
          : // A note the catalogue gave for the old tier becomes its note for the new one: never one that says otherwise.
            { ...m, tier, note: m.note && Object.values(notes).includes(m.note) ? ((tier && notes[tier]) ?? null) : m.note },
      ),
      // A provider the catalogue does not know is ticked once you give it a tier (design §3b).
      ...(tier && !p.catalogued ? { for_agents: true } : {}),
    }))
  const alert = error && (
    <div role="alert" className="alert">
      {error}
    </div>
  )

  const opener = (
    <button
      ref={button}
      type="button"
      className={asButton ? 'btn btn-small' : 'link-btn'}
      disabled={busy}
      onClick={() =>
        void act(async () => {
          const told = await onFillAll()
          focus.current = 'preview'
          setShown(told)
        })
      }
    >
      {asButton ? 'Fill tiers' : 'Fill the tiers'}
    </button>
  )
  if (!shown && asButton)
    return (
      <>
        {opener}
        {saved && (
          <span role="status" className="visually-hidden">
            {saved}
          </span>
        )}
        {alert}
      </>
    )
  if (!shown)
    return (
      // One calm line (spec 81: no strip), as the Models page says its empty slots.
      <section className="muted provider-note fill-tiers" aria-label="No model has a tier">
        <span>No model has a tier yet, so the Orchestrator cannot pick one: every role runs on the conversation’s model.</span>{' '}
        {opener}
        {alert}
      </section>
    )
  const preview = (
    <section className={`fill-tiers fill-tiers-open${asButton ? ' fill-tiers-window' : ''}`} aria-labelledby="fill-tiers-heading">
      <h3 id="fill-tiers-heading" ref={heading} tabIndex={-1}>
        Tiers from the catalogue
      </h3>
      <p className="muted provider-note">
        Look them over: nothing changes until you save them. A CLI on your plan whose command is on this machine comes
        ticked for agents; a provider paid by the token stays as it was, for you to tick.
      </p>
      {shown.providers.map(p => (
        <fieldset key={p.id} className="provider-server">
          <legend>{p.name}</legend>
          <label className="choice" htmlFor={`fill-${p.id}`}>
            <input
              id={`fill-${p.id}`}
              type="checkbox"
              aria-label={`Agents may choose this: ${p.name}`}
              checked={p.for_agents}
              onChange={e => change(p.id, () => ({ for_agents: e.target.checked }))}
            />
            <span>Agents may choose this</span>
          </label>
          {p.models.length === 0 ? (
            <p className="muted provider-note">No catalogue and no models listed: add its models on the Models page.</p>
          ) : (
            // A narrow window scrolls the table, not the page.
            <div className="fill-tiers-scroll">
              <table className="usage-table fill-tiers-table" aria-label={`${p.name}: models and tiers`}>
                <thead>
                  <tr>
                    <th scope="col">Model</th>
                    <th scope="col">Tier</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {p.models.map((m, index) => (
                    <tr key={m.name}>
                      <th scope="row" className="mono">
                        {m.name}
                      </th>
                      <td>
                        <select
                          className="input"
                          aria-label={`Tier of ${m.name} on ${p.name}`}
                          value={m.tier ?? ''}
                          onChange={e => setTier(p, index, (e.target.value || null) as Tier | null)}
                        >
                          <option value="">no tier</option>
                          {TIERS.map(tier => (
                            <option key={tier} value={tier}>
                              {tier}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="muted">{m.note ?? '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </fieldset>
      ))}
      {alert}
      <div className="role-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() =>
            void act(async () => {
              await onSaveFillAll(shown.providers)
              focus.current = asButton ? 'box' : 'saved'
              setShown(null)
              setSaved('The tiers are saved: each role now runs on the first model of its tier that may be picked for it.')
            })
          }
        >
          Save these tiers
        </button>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => {
            focus.current = 'box'
            setShown(null)
          }}
        >
          Cancel
        </button>
      </div>
    </section>
  )
  return asButton ? (
    <div className="dialog-back">
      <div className="provider-dialog" role="dialog" aria-modal="true" aria-labelledby="fill-tiers-heading">
        {preview}
      </div>
    </div>
  ) : (
    preview
  )
}
