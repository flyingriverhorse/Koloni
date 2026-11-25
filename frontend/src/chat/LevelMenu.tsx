import { Check } from '@phosphor-icons/react'
import { type KeyboardEvent, useId } from 'react'
import type { PermissionMode } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { usePanel } from '../shell/usePanel'
import {
  type Checks,
  checksOn,
  checksSaid,
  checksValue,
  type JudgeWords,
  LEVELS,
  NO_CHECKS_AT_FULL_AUTO,
  PLAN_FIRST,
} from './levels'

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
  /** 0.1.9: Full auto's judge, the project's - and its setter, none in a plain chat. */
  judge?: boolean
  onJudge?: (on: boolean) => void
  /** §8: what the judge does with your words - its box off, on, or on but not until its measurement. */
  judgeWords?: JudgeWords
  /** What it does with a command it finds risky, the project's (Settings › This project › Asking and away). */
  judgeRisky?: JudgeRisky
  /** S10: Check after a change for this chat; without it (a plain chat, nothing to check) no switch. */
  checks?: Checks
}

type JudgeRisky = 'refuse' | 'ask'
const JUDGE =
  'Before a command runs at Full auto or while you’re away, a small model looks at it first: one the list doesn’t stop '
const RISKY: Record<JudgeRisky, string> = {
  refuse: 'is refused if it looks risky (while you’re away, it waits for you)',
  ask: 'waits for you if it looks risky',
}
const JUDGE_WORDS = '; a harmful-looking one runs without a card only where a line of yours names it'
/** The judge's line: what it does with a risky command, its part for your words only where its box is on, and " (after
 *  its measurement)" until then. */
const judgeSays = (words: JudgeWords, risky: JudgeRisky) =>
  `${JUDGE}${RISKY[risky]}${words === 'off' ? '' : JUDGE_WORDS}${words === 'unmeasured' ? ' (after its measurement)' : ''}.`

/** A switch row of the panel: its name and what it does. */
function SwitchRow({
  id,
  name,
  says,
  on,
  onChange,
}: {
  id: string
  name: string
  says: string
  on: boolean
  onChange: (on: boolean) => void
}) {
  return (
    <label className="level-row">
      <input
        type="checkbox"
        role="switch"
        className="switch"
        checked={on}
        aria-labelledby={id}
        aria-describedby={`${id}-says`}
        onChange={e => onChange(e.target.checked)}
      />
      <span className="level-words">
        <span id={id} className="level-name">
          {name}
        </span>
        <span id={`${id}-says`} className="level-says">
          {says}
        </span>
      </span>
    </label>
  )
}

/** Behind the switch's ⓘ: the guide's Checked page says the rest. */
const CHECKS_WHY =
  'What KOLONİ tests and reviews after a turn that changed code, and what each line under the answer means.'

/** S10: Test and review changes, beside Plan first - its ⓘ the guide's Checked page; at Full auto with it off, one line on what that leaves (never locked). */
function ChecksRow({ id, mode, checks }: { id: string; mode: PermissionMode; checks: Checks }) {
  const on = checksOn(checks)
  return (
    <>
      <div className="level-row-hint">
        <SwitchRow
          id={`${id}-checks`}
          name="Test and review changes"
          says={checksSaid(checks)}
          on={on}
          onChange={next => checks.onChange(checksValue(next, checks.project))}
        />
        <Hint doc={GUIDE.checked}>{CHECKS_WHY}</Hint>
      </div>
      {mode === 'full_auto' && !on && <p className="level-says level-warn">{NO_CHECKS_AT_FULL_AUTO}</p>}
    </>
  )
}

/** Under the levels, the project's own switch at Full auto: its judge (0.1.9; Check what I said first is its question
 *  since §8) - none without its setter (a plain chat). */
function ProjectSwitches(p: {
  id: string
  judge: boolean
  onJudge?: (on: boolean) => void
  words: JudgeWords
  risky: JudgeRisky
}) {
  if (!p.onJudge) return null
  return (
    <SwitchRow
      id={`${p.id}-judge`}
      name="Full auto’s judge"
      says={judgeSays(p.words, p.risky)}
      on={p.judge}
      onChange={p.onJudge}
    />
  )
}

/**
 * The permission level in the message box's row (0.1.5): its comb and its short name - with Plan first on, " · plan"
 * after it, and " · no checks" where this chat's changes are not checked -; a click opens each level with a line on what
 * it does, Plan first and Check after a change. Esc closes it, the focus back on its button.
 */
export function LevelMenu({
  mode,
  onMode,
  planFirst,
  onPlanFirst,
  judge = true,
  onJudge,
  judgeWords = 'off',
  judgeRisky = 'refuse',
  checks,
}: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const id = useId()
  const level = LEVELS[mode]
  const unchecked = checks !== undefined && !checksOn(checks)
  return (
    <div className="allow-list composer-level-menu">
      <button
        ref={button}
        type="button"
        className="btn btn-small composer-level"
        data-level={mode}
        aria-label={`Permission level: ${level.name}${planFirst ? ', Plan first on' : ''}${unchecked ? ', no checks' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={`${level.name}: ${level.says}${planFirst ? `. Plan first on: ${PLAN_FIRST.toLowerCase()}` : ''}${unchecked ? '. No checks: KOLONİ does not check this chat’s changes' : ''}`}
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
        {unchecked && (
          <>
            {' '}
            <span className="composer-level-plan">· no checks</span>
          </>
        )}
      </button>
      {open && (
        <div
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-label="Permission level"
          className="allow-list-panel level-panel"
        >
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
          <ProjectSwitches id={id} judge={judge} onJudge={onJudge} words={judgeWords} risky={judgeRisky} />
          {onPlanFirst && (
            <>
              <hr className="level-sep" />
              <SwitchRow id={`${id}-plan`} name="Plan first" says={PLAN_FIRST} on={planFirst} onChange={onPlanFirst} />
            </>
          )}
          {checks && <ChecksRow id={id} mode={mode} checks={checks} />}
        </div>
      )}
    </div>
  )
}
