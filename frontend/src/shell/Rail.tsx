import { Books, Brain, ChatsCircle, CheckSquare, Clock, Cpu, GearSix, Graph, Kanban, ListChecks, Moon, Plugs, Robot, Sun, Table } from '@phosphor-icons/react'
import type { Ref } from 'react'
import type { Theme } from '../theme/theme'

export type View = 'canvas' | 'conversations' | 'ready' | 'board' | 'backlog' | 'agents' | 'models' | 'tools' | 'memory' | 'knowledge' | 'triggers' | 'usage'

interface Props {
  /** The page shown; null while none of these is (Settings is). */
  view: View | null
  onView: (view: View) => void
  theme: Theme
  onToggleTheme: () => void
  /** How many things wait for your word anywhere: Ready for you's rows. */
  waiting: number
  /** Settings (tek-ev): its own page, opened and closed by ⚙; the focus comes back to it. */
  settingsOpen?: boolean
  onSettings?: () => void
  gear?: Ref<HTMLButtonElement>
}

/** Each button says its name under its icon (slice 66), a word of its aria-label (WCAG 2.5.3); assistive tech reads the aria-label. */
export function Rail({ view, onView, theme, onToggleTheme, waiting, settingsOpen = false, onSettings, gear }: Props) {
  return (
    <nav className="rail" aria-label="Main">
      <div className="rail-mark" title="KOLONİ">
        {/* The bee, the favicon itself: one file to keep. */}
        <img src="/favicon.svg" width={28} height={28} alt="" aria-hidden="true" />
      </div>
      <button
        className="icon-btn"
        aria-pressed={view === 'canvas'}
        aria-label="Canvas"
        onClick={() => onView('canvas')}
      >
        <Graph size={19} />
        <span className="rail-label" aria-hidden="true">Canvas</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'conversations'}
        aria-label="Chats"
        onClick={() => onView('conversations')}
      >
        <ChatsCircle size={19} />
        <span className="rail-label" aria-hidden="true">Chats</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'ready'}
        aria-label="Ready"
        aria-describedby={waiting > 0 ? 'rail-waiting' : undefined}
        onClick={() => onView('ready')}
      >
        <CheckSquare size={19} />
        <span className="rail-label" aria-hidden="true">Ready</span>
        {/* What waits for your word, anywhere: the top bar's pill says the same number (tek-ev §1). */}
        {waiting > 0 && (
          <>
            <span className="tag tag-warn rail-badge" aria-hidden="true">
              {waiting}
            </span>
            <span id="rail-waiting" className="visually-hidden">{`${waiting} waiting`}</span>
          </>
        )}
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'board'}
        aria-label="Board"
        onClick={() => onView('board')}
      >
        <Kanban size={19} />
        <span className="rail-label" aria-hidden="true">Board</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'backlog'}
        aria-label="To-do"
        onClick={() => onView('backlog')}
      >
        <ListChecks size={19} />
        <span className="rail-label" aria-hidden="true">To-do</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'agents'}
        aria-label="Agents"
        onClick={() => onView('agents')}
      >
        <Robot size={19} />
        <span className="rail-label" aria-hidden="true">Agents</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'models'}
        aria-label="Models"
        onClick={() => onView('models')}
      >
        <Cpu size={19} />
        <span className="rail-label" aria-hidden="true">Models</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'tools'}
        aria-label="Tools"
        onClick={() => onView('tools')}
      >
        <Plugs size={19} />
        <span className="rail-label" aria-hidden="true">Tools</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'memory'}
        aria-label="Memory"
        onClick={() => onView('memory')}
      >
        <Brain size={19} />
        <span className="rail-label" aria-hidden="true">Memory</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'knowledge'}
        aria-label="Knowledge"
        onClick={() => onView('knowledge')}
      >
        <Books size={19} />
        <span className="rail-label" aria-hidden="true">Knowledge</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'triggers'}
        aria-label="Triggers"
        onClick={() => onView('triggers')}
      >
        <Clock size={19} />
        <span className="rail-label" aria-hidden="true">Triggers</span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'usage'}
        aria-label="Usage"
        onClick={() => onView('usage')}
      >
        <Table size={19} />
        <span className="rail-label" aria-hidden="true">Usage</span>
      </button>
      <div className="rail-spacer" />
      <button ref={gear} className="icon-btn" aria-pressed={settingsOpen} aria-label="Settings" onClick={onSettings}>
        <GearSix size={19} />
        <span className="rail-label" aria-hidden="true">Settings</span>
      </button>
      <button
        className="icon-btn"
        aria-label={theme === 'dark' ? 'Theme: switch to light' : 'Theme: switch to dark'}
        onClick={onToggleTheme}
      >
        {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
        <span className="rail-label" aria-hidden="true">Theme</span>
      </button>
    </nav>
  )
}
