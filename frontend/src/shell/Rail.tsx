import {
  Brain,
  ChatsCircle,
  CheckSquare,
  Cpu,
  GearSix,
  Graph,
  Moon,
  Plugs,
  Robot,
  Sun,
  Table,
} from '@phosphor-icons/react'
import type { Ref } from 'react'
import type { Theme } from '../theme/theme'

// (0.1.10: To-do is Ready for you's right half - no page of its own.)
export type View =
  'canvas' | 'conversations' | 'ready' | 'agents' | 'models' | 'tools' | 'memory' | 'knowledge' | 'usage'

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
        <span className="rail-label" aria-hidden="true">
          Canvas
        </span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'conversations'}
        aria-label="Chats"
        onClick={() => onView('conversations')}
      >
        <ChatsCircle size={19} />
        <span className="rail-label" aria-hidden="true">
          Chats
        </span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'ready'}
        aria-label="Ready"
        aria-describedby={waiting > 0 ? 'rail-waiting' : undefined}
        onClick={() => onView('ready')}
      >
        <CheckSquare size={19} />
        <span className="rail-label" aria-hidden="true">
          Ready
        </span>
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
        aria-pressed={view === 'agents'}
        aria-label="Agents"
        onClick={() => onView('agents')}
      >
        <Robot size={19} />
        <span className="rail-label" aria-hidden="true">
          Agents
        </span>
      </button>
      <button
        className="icon-btn"
        aria-pressed={view === 'models'}
        aria-label="Models"
        onClick={() => onView('models')}
      >
        <Cpu size={19} />
        <span className="rail-label" aria-hidden="true">
          Models
        </span>
      </button>
      <button className="icon-btn" aria-pressed={view === 'tools'} aria-label="Tools" onClick={() => onView('tools')}>
        <Plugs size={19} />
        <span className="rail-label" aria-hidden="true">
          Tools
        </span>
      </button>
      {/* 0.1.10: Memory and its sources (once Knowledge) are one page, one button. */}
      <button
        className="icon-btn"
        aria-pressed={view === 'memory' || view === 'knowledge'}
        aria-label="Memory"
        onClick={() => onView('memory')}
      >
        <Brain size={19} />
        <span className="rail-label" aria-hidden="true">
          Memory
        </span>
      </button>
      <button className="icon-btn" aria-pressed={view === 'usage'} aria-label="Usage" onClick={() => onView('usage')}>
        <Table size={19} />
        <span className="rail-label" aria-hidden="true">
          Usage
        </span>
      </button>
      <div className="rail-spacer" />
      <button ref={gear} className="icon-btn" aria-pressed={settingsOpen} aria-label="Settings" onClick={onSettings}>
        <GearSix size={19} />
        <span className="rail-label" aria-hidden="true">
          Settings
        </span>
      </button>
      <button
        className="icon-btn"
        aria-label={theme === 'dark' ? 'Theme: switch to light' : 'Theme: switch to dark'}
        onClick={onToggleTheme}
      >
        {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
        <span className="rail-label" aria-hidden="true">
          Theme
        </span>
      </button>
    </nav>
  )
}
