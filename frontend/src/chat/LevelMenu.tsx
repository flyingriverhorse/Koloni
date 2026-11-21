import { Check } from '@phosphor-icons/react'
import { type KeyboardEvent, useId } from 'react'
import type { PermissionMode } from '../api/types'
import { usePanel } from '../shell/usePanel'
import { LEVELS, PLAN_FIRST } from './levels'

const MODES = Object.keys(LEVELS) as PermissionMode[]

/** The arrows move the focus to the level before or after, no further than the first and the last. */
function moveBetween(event: KeyboardEvent<HTMLDivElement>) {
  const by = { ArrowDown: 1, ArrowUp: -1 }[event.key]
  if (!by) return
  event.preventDefault()
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role=menuitemradio]'))
  const at = items.indexOf(document.activeElement as HTMLElement)
  items[Math.max(0, Math.min(items.length - 1, at + by))]?.focus()
}

/** A hexagon of the comb, its center at `x`. */
const cell = (x: number) => `${x},1 ${x + 4.5},3.5 ${x + 4.5},10.5 ${x},13 ${x - 4.5},10.5 ${x - 4.5},3.5`

/** How far the agents may go, as comb cells: one filled for Ask, two for Auto-edit, three for Full auto. Drawn only. */
function Comb({ cells }: { cells: number }) {
  return (
    <svg className="comb" width="34" height="14" viewBox="0 0 34 14" aria-hidden>
      {[5, 17, 29].map((x, i) => (
        <polygon key={x} points={cell(x)} data-cell={i < cells ? 'on' : 'off'} />
      ))}
    </svg>
  )
}

interface Props {
  mode: PermissionMode
  onMode: (mode: PermissionMode) => void
  planFirst: boolean
  /** Turn Plan first on or off; without it there is no conversation to set it on. */
  onPlanFirst?: (on: boolean) => void
}

/**
 * The permission level in the message box's row (0.1.5): its comb and its short name - with Plan first on, " · plan"
 * after it -; a click opens each level with a line on what it does, and Plan first. Esc closes it, the focus back on its
 * button.
 */
export function LevelMenu({ mode, onMode, planFirst, onPlanFirst }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const id = useId()
  const level = LEVELS[mode]
  return (
    <div className="allow-list composer-level-menu">
      <button
        ref={button}
        type="button"
        className="btn btn-small composer-level"
        data-level={mode}
        aria-label={`Permission level: ${level.name}${planFirst ? ', Plan first on' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={`${level.name}: ${level.says}${planFirst ? `. Plan first on: ${PLAN_FIRST.toLowerCase()}` : ''}`}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <Comb cells={level.cells} />
        <span className="composer-level-name">{level.short}</span>
        {planFirst && (
          <>
            {' '}
            <span className="composer-level-plan">· plan</span>
          </>
        )}
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Permission level" className="allow-list-panel level-panel">
          <div className="kicker">Permission level</div>
          {/* Chosen by a click, Enter or Space only: the arrows move between them (a radio group chose by moving, and
              wrapped round to Full auto). */}
          <div role="menu" aria-label="Permission level" className="level-list" onKeyDown={moveBetween}>
            {MODES.map(m => (
              <button
                key={m}
                type="button"
                role="menuitemradio"
                className="level-row"
                aria-checked={m === mode}
                aria-labelledby={`${id}-${m}`}
                aria-describedby={`${id}-${m}-says`}
                onClick={() => onMode(m)}
              >
                <span className="level-mark" aria-hidden>
                  {m === mode && <Check size={12} />}
                </span>
                <span className="level-words">
                  <span id={`${id}-${m}`} className="level-name">
                    {LEVELS[m].name}
                  </span>
                  <span id={`${id}-${m}-says`} className="level-says">
                    {LEVELS[m].says}
                  </span>
                </span>
              </button>
            ))}
          </div>
          {onPlanFirst && (
            <>
              <hr className="level-sep" />
              <label className="level-row">
                <input
                  type="checkbox"
                  role="switch"
                  className="switch"
                  checked={planFirst}
                  aria-labelledby={`${id}-plan`}
                  aria-describedby={`${id}-plan-says`}
                  onChange={e => onPlanFirst(e.target.checked)}
                />
                <span className="level-words">
                  <span id={`${id}-plan`} className="level-name">
                    Plan first
                  </span>
                  <span id={`${id}-plan-says`} className="level-says">
                    {PLAN_FIRST}
                  </span>
                </span>
              </label>
            </>
          )}
        </div>
      )}
    </div>
  )
}
