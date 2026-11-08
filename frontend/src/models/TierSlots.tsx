import { ArrowDown, ArrowUp } from '@phosphor-icons/react'
import { type DragEvent, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import { TIERS, type Tier, type TierOrder, type Tiers } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { modelName } from '../shell/modelName'

const NAMES: Record<Tier, string> = { strongest: 'Strongest', balanced: 'Balanced', fast: 'Fast' }
// A tier shows its first few; "+N more" shows the rest.
const FIRST = 5

interface Props {
  /** Each tier's models in the order they are tried; null while read. */
  tiers: Tiers | null
  /** Why a provider looked down when the page last read it ("not answering"); null: it did not. Shown only: see the guide's tier lists. */
  down: (providerId: string) => string | null
  /** Saves the order; answers it as saved. Throws ApiError. */
  onSave: (order: TierOrder) => Promise<Tiers>
  /** An order was refused: the tiers are read again, as they are now. */
  onRefused?: () => void
}

/** Strongest, Balanced and Fast: each tier's models numbered in the order they are tried. Dragged, or moved with
 *  the arrows, each change is saved at once. */
export function TierSlots({ tiers, down, onSave, onRefused }: Props) {
  const [shown, setShown] = useState(tiers)
  const [error, setError] = useState<string | null>(null)
  const [dragged, setDragged] = useState<{ tier: Tier; at: number } | null>(null)
  // The tiers shown whole.
  const [whole, setWhole] = useState<Partial<Record<Tier, boolean>>>({})
  useEffect(() => setShown(tiers), [tiers])
  if (!shown) return null

  async function move(tier: Tier, from: number, to: number) {
    if (!shown || from === to || to < 0 || to >= shown[tier].length) return
    const list = [...shown[tier]]
    list.splice(to, 0, ...list.splice(from, 1))
    const was = shown
    const order = { ...shown, [tier]: list }
    setShown(order)
    setError(null)
    try {
      setShown(await onSave(order))
    } catch (err) {
      setShown(was)
      setError(errorText(err))
      onRefused?.()
    }
  }
  // The keyboard stays with the model moved: at an end, on its other arrow (the one pressed is off there).
  function arrow(tier: Tier, at: number, by: number) {
    const to = at + by
    // A model moved past the first few stays in sight, and so does the keyboard on it.
    if (to >= FIRST) setWhole(was => ({ ...was, [tier]: true }))
    void move(tier, at, to)
    const end = to === 0 || to === (shown?.[tier].length ?? 0) - 1
    if (end) setTimeout(() => document.getElementById(`move-${tier}-${to}-${by < 0 ? 'down' : 'up'}`)?.focus())
  }
  const none = TIERS.every(tier => shown[tier].length === 0)
  return (
    <section className="tier-slots" aria-label="Tiers">
      {[...TIERS].reverse().map(tier => (
        <section key={tier} className="tier-slot" aria-labelledby={`slot-${tier}`}>
          <h3 id={`slot-${tier}`}>
            <span className={`tier-mark tier-${tier}`} aria-hidden="true" />
            {NAMES[tier]}
            {tier === 'strongest' && (
              <Hint doc={GUIDE.tiers}>
                Each tier is tried in this order: a role that asks for a tier runs on the first of its models that may be
                picked; a model agents may not use is passed over. A sub-agent runs on the first provider that offers its
                role’s tier, in this order - the chat’s own provider is not preferred, and is used only where no model
                has the tier; one whose provider fails before its first word (queued too long, down) is moved once to the
                tier’s next - a card you approve unless the chat’s spawn approval is “never”, and only while you watch
                the turn.
              </Hint>
            )}
          </h3>
          {shown[tier].length > 0 ? (
            <ol className="tier-list">
              {(whole[tier] ? shown[tier] : shown[tier].slice(0, FIRST)).map((one, at) => {
                // (A pick passes it over by the server's own last reading: `app.providers.looked_down`.)
                const off = down(one.provider_id)
                const name = modelName(one.model)
                // Passed over either way: its provider does not run now, or agents may not use it.
                const why = off || !one.agents
                return (
                  <li
                    key={`${one.provider_id} ${one.model}`}
                    className={`tier-item${why ? ' tier-item-down' : ''}${dragged?.tier === tier && dragged.at === at ? ' tier-item-dragged' : ''}`}
                    draggable
                    onDragStart={(event: DragEvent) => {
                      event.dataTransfer?.setData('text/plain', `${tier} ${at}`)
                      setDragged({ tier, at })
                    }}
                    onDragEnd={() => setDragged(null)}
                    // Only within its own tier: the tier itself is set on the provider.
                    onDragOver={event => dragged?.tier === tier && event.preventDefault()}
                    onDrop={event => {
                      event.preventDefault()
                      if (dragged?.tier === tier) void move(tier, dragged.at, at)
                      setDragged(null)
                    }}
                  >
                    <span className="tier-n" aria-hidden="true">
                      {at + 1}
                    </span>
                    <span className="tier-model" title={one.model}>
                      {name}
                    </span>
                    <span className="tier-from muted">
                      {[one.provider_name, off, !one.agents && 'off for agents'].filter(Boolean).join(' · ')}
                    </span>
                    <button
                      type="button"
                      className="icon-btn"
                      id={`move-${tier}-${at}-up`}
                      aria-label={`Move ${name} up`}
                      disabled={at === 0}
                      onClick={() => arrow(tier, at, -1)}
                    >
                      <ArrowUp size={12} />
                    </button>
                    <button
                      type="button"
                      className="icon-btn"
                      id={`move-${tier}-${at}-down`}
                      aria-label={`Move ${name} down`}
                      disabled={at === shown[tier].length - 1}
                      onClick={() => arrow(tier, at, 1)}
                    >
                      <ArrowDown size={12} />
                    </button>
                  </li>
                )
              })}
            </ol>
          ) : (
            !none && <p className="muted provider-note">No model</p>
          )}
          {shown[tier].length > FIRST && (
            <button
              type="button"
              className="btn btn-small tier-more"
              aria-expanded={!!whole[tier]}
              onClick={() => setWhole(was => ({ ...was, [tier]: !was[tier] }))}
            >
              {whole[tier] ? 'Show fewer' : `+${shown[tier].length - FIRST} more`}
            </button>
          )}
        </section>
      ))}
      {none && <p className="muted tier-none">No model has a tier yet. Fill the tiers from the catalogue</p>}
      {error && (
        <div role="alert" className="alert tier-error">
          {error}
        </div>
      )}
    </section>
  )
}
