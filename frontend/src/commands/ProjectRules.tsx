import { X } from '@phosphor-icons/react'
import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { ChatRules } from '../api/types'
import { webRule } from './AllowList'

/**
 * Settings › This project › Runs without asking (tek-ev): each chat's "Always run" commands and web rules, by the chat's
 * title, each removed here as it was in the chat. The open chat is listed even with none, so a host can be allowed for it.
 * No <form>: it sits in Project settings' own form, so Enter and the button add the host and never send the settings.
 */
export function ProjectRules({ projectId, chat, sites = 0 }: { projectId: string; chat?: { id: string; title: string }; sites?: number }) {
  const [chats, setChats] = useState<ChatRules[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hosts, setHosts] = useState<Record<string, string>>({})
  const read = useCallback(() => api.get<ChatRules[]>(`/projects/${projectId}/allowed`).then(setChats, err => setError(errorText(err))), [projectId])
  useEffect(() => void read(), [read])

  async function act(work: Promise<unknown>) {
    setError(null)
    try {
      await work
    } catch (err) {
      setError(errorText(err))
    }
    await read()
  }
  const allow = (id: string) => {
    const host = (hosts[id] ?? '').trim()
    if (!host) return
    void act(api.post(`/conversations/${id}/allowed-web`, { host }).then(() => setHosts(was => ({ ...was, [id]: '' }))))
  }

  const listed = chats && chat && !chats.some(c => c.conversation_id === chat.id) ? [{ conversation_id: chat.id, title: chat.title, commands: [], web: [] }, ...chats] : chats
  return (
    <section aria-label="Commands and requests by chat" className="field">
      <h2>Commands and requests, by chat</h2>
      {listed?.length === 0 && <p className="muted">None yet: “Always run” on a card adds one.</p>}
      {listed?.map(rules => (
        <div key={rules.conversation_id} role="group" aria-label={rules.title} className="rules-chat">
          {/* (Counted as the chat's own link counts them: its commands and requests, and the project's sites.) */}
          <div className="kicker">
            {rules.title} · {rules.commands.length + rules.web.length + sites} run without asking
          </div>
          {[
            ...rules.commands.map(rule => ({ id: rule.id, text: rule.prefix, danger: rule.danger, remove: `/allowed-commands/${rule.id}` })),
            ...rules.web.map(rule => ({ id: rule.id, text: webRule(rule), danger: '', remove: `/allowed-web/${rule.id}` })),
          ].map(rule => (
            <div key={rule.id} className="allow-list-rule">
              <span className="mono">{rule.text}</span>
              {/* (A rule kept from before slice 90 for a command that is asked every time now.) */}
              {rule.danger && <span className="muted" title={rule.danger}>covers nothing now - it deletes or names a secret</span>}
              <button type="button" className="icon-btn" aria-label={`Remove rule ${rule.text}`} onClick={() => void act(api.delete(rule.remove))}>
                <X size={12} />
              </button>
            </div>
          ))}
          <div className="allow-list-rule">
            <input
              className="input mono"
              aria-label={`Allow GET to a host in ${rules.title}`}
              placeholder="Allow GET to a host…"
              value={hosts[rules.conversation_id] ?? ''}
              maxLength={500}
              onChange={e => setHosts(was => ({ ...was, [rules.conversation_id]: e.target.value }))}
              onKeyDown={e => {
                if (e.key !== 'Enter') return
                e.preventDefault()
                allow(rules.conversation_id)
              }}
            />
            <button type="button" className="btn btn-small" disabled={!hosts[rules.conversation_id]?.trim()} onClick={() => allow(rules.conversation_id)}>
              Allow
            </button>
          </div>
        </div>
      ))}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
