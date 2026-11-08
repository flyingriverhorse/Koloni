import { Question } from '@phosphor-icons/react'
import { useEffect, useRef } from 'react'
import { usePanel } from './usePanel'

/** What the keys do, as they are wired: here, in the palette (Palette.tsx), the chat and every panel. */
const SHORTCUTS: [keys: string, what: string][] = [
  ['Ctrl+K', 'Find a page, conversation, role, model, tool server or setting (⌘K on a Mac)'],
  ['?', 'These shortcuts'],
  ['/', 'Write a message: the focus goes to the message box'],
  ['/ in the box', 'Commands, at the start of the message box: /new, /room, /stop, /model, /mode, a role and its task - /coder fix the tests, or one of your own (Settings › This project › Slash commands)'],
  ['C', 'Open the chat, where it is closed'],
  ['Enter', 'Send the message; Shift+Enter starts a new line'],
  ['Esc', 'Close the panel, window or chat the focus is in; the focus goes back where it was'],
]

/** Whether a key pressed there is being typed into something. */
const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))

/** Help, in the top bar: the keyboard shortcuts (also on `?`), and the first steps shown again. */
export function Help({ onFirstSteps }: { onFirstSteps: () => void }) {
  const { open, setOpen, close, button, panel } = usePanel()
  // Opened by `?`: closed, the focus goes back to where the key was pressed, not to the Help button.
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (open || !opener.current) return
    // (Unless the click that closed it put the focus somewhere else.)
    const at = document.activeElement
    if (opener.current.isConnected && (!at || at === document.body || at === button.current)) opener.current.focus()
    opener.current = null
  }, [open, button])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return
      if (event.key === '?') {
        event.preventDefault()
        if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) opener.current = document.activeElement
        setOpen(true)
      }
      // (Its closed line opens it, as a click on it does.)
      if (event.key.toLowerCase() === 'c' && !event.shiftKey) document.querySelector<HTMLElement>('.chat-line')?.click()
      const box = event.key === '/' && document.querySelector<HTMLElement>('.composer-input')
      if (box) {
        event.preventDefault() // the "/" is not typed into it
        box.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [setOpen])
  return (
    <>
      <button ref={button} type="button" className="icon-btn" aria-label="Help" aria-expanded={open} onClick={() => (open ? close() : setOpen(true))}>
        <Question size={16} />
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel" role="dialog" aria-label="Help">
          <div className="kicker">Keyboard shortcuts</div>
          <dl className="shortcuts">
            {SHORTCUTS.map(([keys, what]) => (
              <div key={keys}>
                <dt>
                  <kbd className="mono">{keys}</kbd>
                </dt>
                <dd>{what}</dd>
              </div>
            ))}
          </dl>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => {
              close()
              onFirstSteps()
            }}
          >
            Show the first steps
          </button>
        </div>
      )}
    </>
  )
}
