import type { BacklogTask } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { usePanel } from '../shell/usePanel'
import { useApp } from '../state/store'
import { tickable } from './tree'

/** What the selection dock says under its button (the spec's words, 24 Nov). */
export const DOCK_SAYS =
  'Each story goes into its own topic; a task without a story gets a topic of its own. They wait in the chat’s queue.'

/** The chat a selection may go to: the one open now, when it is a chat of this folder. */
export interface LastChat {
  id: string
  title: string
}

interface Props {
  /** The ticked tasks, in the tree's order. */
  selected: BacklogTask[]
  lastChat: LastChat | null
  onDo: (taskIds: string[], conversationId: string | null) => Promise<void>
}

/** 0.1.8: under the tree while tasks are ticked - "N selected · Do in chat ▾": this chat, or a new one. */
export function SelectionDock({ selected, lastChat, onDo }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const { busy, error, ask } = useAsk()
  if (!selected.length) return null
  const ids = selected.map(task => task.id)
  const go = (conversationId: string | null) => {
    close()
    void ask(() => onDo(ids, conversationId))
  }
  return (
    <section className="todo-dock" aria-label="Selected tasks">
      <div className="todo-dock-row">
        <span>{selected.length} selected</span>
        <span aria-hidden="true">·</span>
        <span className="allow-list">
          <button
            ref={button}
            type="button"
            className="btn btn-primary btn-small"
            aria-haspopup="menu"
            aria-expanded={open}
            disabled={busy}
            onClick={() => (open ? close() : setOpen(true))}
          >
            Do in chat <span aria-hidden="true">▾</span>
          </button>
          {open && (
            <div ref={panel} tabIndex={-1} className="allow-list-panel msg-menu" role="menu" aria-label="Do in chat">
              <button
                type="button"
                role="menuitem"
                disabled={!lastChat}
                title={lastChat ? undefined : 'Open a chat of this folder first'}
                onClick={() => lastChat && go(lastChat.id)}
              >
                {lastChat ? `This chat — “${lastChat.title}”` : 'This chat'}
              </button>
              <button type="button" role="menuitem" onClick={() => go(null)}>
                A new chat
              </button>
            </div>
          )}
        </span>
      </div>
      <p className="muted todo-dock-says">{DOCK_SAYS}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}

/** The dock as the To-do page has it: the ticked tasks still to do, the chat open now when it is one of this folder. */
export function TodoDock({
  listed,
  selected,
  onSelect,
  projectId,
  onDo,
}: {
  listed: BacklogTask[]
  selected: Set<string>
  onSelect: (taskIds: string[], on: boolean) => void
  projectId?: string
  onDo?: (taskIds: string[], conversationId: string | null) => Promise<void>
}) {
  const conv = useApp(s => s.conv)
  if (!onDo) return null
  const here = conv && projectId && conv.conversation.project_id === projectId ? conv.conversation : null
  const ticked = listed.filter(task => selected.has(task.id) && tickable(task))
  return (
    <SelectionDock
      selected={ticked}
      lastChat={here && !here.archived_at ? { id: here.id, title: here.title } : null}
      onDo={async (ids, cid) => {
        await onDo(ids, cid)
        onSelect(ids, false)
      }}
    />
  )
}
