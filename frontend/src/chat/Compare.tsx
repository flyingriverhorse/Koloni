import { Columns } from '@phosphor-icons/react'
import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { Provider } from '../api/types'
import { type LoadModels, ModelNameInput, ProviderOptions } from '../models/ModelNameInput'
import { usePanel } from '../shell/usePanel'

export interface Second {
  provider_id: string
  model_id: string | null
}

interface Props {
  providers: Provider[]
  /** What the message box holds as Compare is opened: the message, unless it is changed here. */
  content: string
  /** What the conversation's own model is called, the first of the two. */
  first: string
  onCompare: (content: string, second: Second) => Promise<void>
  onModels?: LoadModels
}

/**
 * "Compare…" under More (slice 54): a message goes to the conversation's model and to a second
 * one you choose here, side by side, each in a working copy of its own. Nothing of either reaches
 * the project until you pick one.
 */
export function Compare({ providers, content, first, onCompare, onModels }: Props) {
  const { open, setOpen, close, button, panel } = usePanel<HTMLFormElement>()
  const [message, setMessage] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ready = message.trim().length > 0 && provider !== '' && !sending

  function toggle() {
    if (open) return close()
    setMessage(content)
    setError(null)
    setOpen(true)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready) return
    setSending(true)
    setError(null)
    try {
      await onCompare(message.trim(), { provider_id: provider, model_id: model.trim() || null })
      close()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="allow-list">
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-expanded={open}
        title="Send a message to two models side by side, and keep the work of one"
        onClick={toggle}
      >
        <Columns size={13} />
        Compare…
      </button>
      {open && (
        <form ref={panel} tabIndex={-1} className="allow-list-panel" aria-label="Compare two models" onSubmit={submit}>
          <div className="kicker">Compare two models</div>
          <div className="field">
            <label htmlFor="compare-message">Message</label>
            <textarea id="compare-message" className="input" rows={3} value={message} onChange={e => setMessage(e.target.value)} />
          </div>
          <div className="muted cmd-approval-note">First: {first}</div>
          <div className="field">
            <label htmlFor="compare-provider">Second model’s provider</label>
            <select
              id="compare-provider"
              className="input"
              value={provider}
              onChange={e => {
                setProvider(e.target.value)
                setModel('')
              }}
            >
              <option value="">Choose…</option>
              <ProviderOptions providers={providers} />
            </select>
          </div>
          {provider && (
            <div className="field">
              <label htmlFor="compare-model">Model name</label>
              <ModelNameInput
                id="compare-model"
                value={model}
                placeholder={providers.find(p => p.id === provider)?.default_model ?? 'The provider’s default'}
                providerId={provider}
                loadModels={onModels}
                onChange={setModel}
              />
            </div>
          )}
          <div className="muted cmd-approval-note">
            Each model does the work itself, in a copy of the project of its own, one after the other. Files they write stay in their
            copy until you pick one; the other’s are thrown away. node_modules and .venv are the project’s own, shared: a command that
            installs or deletes there is asked about first, but another can still change them.
          </div>
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          <button type="submit" className="btn btn-small btn-primary" disabled={!ready}>
            Compare
          </button>
        </form>
      )}
    </div>
  )
}
