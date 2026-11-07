import { useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { OwnCommand } from '../api/types'
import { useApp } from '../state/store'

const EMPTY = { name: '', description: '', template: '', role: '', every: false }

/**
 * The user's own slash commands (slice 53): listed, added, changed and deleted here, each
 * saved at once - not by the project's Save. Every button is type="button": this sits in the
 * settings' form, whose submit would send the project's settings.
 */
export function OwnCommands({ projectId }: { projectId: string }) {
  const commands = useApp(s => s.ownCommands)
  // Not the Lead: the message goes to it anyway.
  const roles = useApp(s => s.roles).filter(r => r.name !== 'Lead')
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const nameInput = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLUListElement>(null)
  // The row a delete leaves the focus at: the next one once the list is read again, or the name when none is left.
  const after = useRef<number | null>(null)
  useEffect(() => {
    // (Once the buttons are on again: a disabled one takes no focus.)
    if (after.current === null || busy) return
    const edits = list.current?.querySelectorAll<HTMLButtonElement>('button[data-edit]') ?? []
    ;(edits[Math.min(after.current, edits.length - 1)] ?? nameInput.current)?.focus()
    after.current = null
  }, [commands, busy])
  const set = (change: Partial<typeof EMPTY>) => {
    setSaved(false)
    setForm({ ...form, ...change })
  }

  async function act(work: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function edit(command: OwnCommand | null) {
    setEditing(command?.id ?? null)
    setError(null)
    setSaved(false)
    if (!command) return setForm(EMPTY)
    nameInput.current?.focus()
    const { name, description, template } = command
    // A role deleted since is not sent back: the list shows "No role" for it.
    const role = roles.some(r => r.name === command.role) ? command.role! : ''
    setForm({ name, description, template, role, every: command.project_id === null })
  }

  const save = () =>
    act(async () => {
      const { every, ...values } = form
      await useApp.getState().saveOwnCommand(editing, { ...values, name: values.name.trim(), role: values.role || null, project_id: every ? null : projectId })
      edit(null)
      setSaved(true)
    })

  return (
    <>
      <h2>Slash commands</h2>
      <span className="choice-note">
        Your own commands in the message box’s / menu: <span className="mono">/name</span> and what you type after it put the text
        in the box, <span className="mono">{'{args}'}</span> replaced by what you typed, to change before you send it.
      </span>
      {commands.length === 0 ? (
        <p className="muted">None yet.</p>
      ) : (
        <ul ref={list} className="own-commands" aria-label="Your slash commands">
          {commands.map((command, index) => (
            <li key={command.id} className="also-in-row">
              <span>
                <span className="mono">/{command.name}</span>{' '}
                <span className="muted">
                  {[command.description, command.project_id === null ? 'every project' : 'this project', command.role && `to ${command.role}`].filter(Boolean).join(' · ')}
                </span>
              </span>
              <span>
                <button type="button" className="btn btn-small" aria-label={`Edit /${command.name}`} data-edit disabled={busy} onClick={() => edit(command)}>
                  Edit
                </button>{' '}
                <button type="button" className="btn btn-small" aria-label={`Delete /${command.name}`} disabled={busy} onClick={() => {
                    after.current = index
                    // (Refused, nothing went: the focus is on this row's Edit, the reason said below.)
                    void act(() => useApp.getState().deleteOwnCommand(command.id))
                  }}>
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <h3>{editing ? 'Change the command' : 'Add a command'}</h3>
      <div className="field">
        <label htmlFor="own-name">Name</label>
        <input ref={nameInput} id="own-name" className="input mono" value={form.name} maxLength={40} placeholder="test-yaz" aria-describedby="own-name-note" onChange={e => set({ name: e.target.value })} />
        <span id="own-name-note" className="choice-note">
          No spaces; not one of the box’s own (new, room, stop, model, mode, plan).
        </span>
      </div>
      <div className="field">
        <label htmlFor="own-description">What it does</label>
        <input id="own-description" className="input" value={form.description} maxLength={200} onChange={e => set({ description: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="own-template">Text it puts in the box</label>
        <textarea id="own-template" className="input mono" rows={3} value={form.template} maxLength={4000} placeholder="Write tests for {args}" onChange={e => set({ template: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="own-role">Hand it to a role</label>
        <select id="own-role" className="input" value={form.role} onChange={e => set({ role: e.target.value })}>
          <option value="">No role</option>
          {roles.map(role => (
            <option key={role.id} value={role.name}>
              {role.name}
            </option>
          ))}
        </select>
      </div>
      <label className="choice">
        <input type="checkbox" checked={form.every} onChange={e => set({ every: e.target.checked })} />
        <span>In every project</span>
      </label>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="role-actions">
        <button type="button" className="btn btn-primary" disabled={busy || !form.name.trim() || !form.template.trim()} onClick={save}>
          {editing ? 'Save command' : 'Add command'}
        </button>
        {editing && (
          <button type="button" className="btn" onClick={() => edit(null)}>
            Cancel
          </button>
        )}
        <span role="status" className="muted">
          {saved ? 'Saved' : ''}
        </span>
      </div>
    </>
  )
}
