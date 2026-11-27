import { type ReactNode, useState } from 'react'
import type { MemoryRecord, ProjectMemory } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { KEPT_IN_FOLDER } from '../shell/ProjectSettings'
import { FolderRules, ProjectNotes, RulesBox } from './forms'
import { Suggestion } from './records'

const TOLD_MORE =
  'Your preferences are yours in every project: every agent is told them as your instructions, before the project’s rules - language, tone, commit rules, whatever holds wherever you work. This project’s rules are like an AGENTS.md or CLAUDE.md file: every agent working in this project is given them each turn. Only you write either. At Full auto, with Full auto’s judge’s box for your words on (Settings › This project › Asking and away - once its measurement has passed), a harmful-looking command runs without a card when a line here names it and what it touches: “You may delete build/ and dist/.”, “Pushing branches other than main is fine.” One a line here forbids is not run: “Never push to main.”'

/** One of your texts, on paper: apart from what agents wrote. */
function Paper({ title, why, children }: { title: string; why?: string; children: ReactNode }) {
  return (
    <section className="memory-paper" aria-label={title}>
      <h4>{title}</h4>
      {why && <p className="muted memory-why">{why}</p>}
      {children}
    </section>
  )
}

/** The rules in the box: the folder's where it is read - but the saved ones where they differ, which Full auto's check reads (K-yargıç). */
const boxRules = (memory: ProjectMemory) => (memory.rules_differ ? (memory.rules_saved ?? null) : memory.rules)

interface Props {
  memory: ProjectMemory
  onSavePreferences: (text: string) => Promise<void>
  onAddPreference: (id: string) => Promise<void>
  onReject: (id: string) => Promise<void>
  onSaveRules: (rules: string) => Promise<void>
  onSaveProjectNotes: (text: string) => Promise<void>
  /** The other projects Search deeper and Recall also look in, by name; and the way to change them. */
  linked?: string[]
  onLinked?: () => void
}

/**
 * 0.1.10: your words, beside what agents wrote - your preferences with what is suggested for them, this project's rules
 * (and where the folder's rules.md says other), and the Project notes. Only you write them; each is said to agents as
 * the page's three ways say.
 */
export function YourWords({ memory, linked, onLinked, ...on }: Props) {
  // Whether .koloni/rules.md was there before the last save of the rules: the save that put it there says so, once.
  const [keptBefore, setKeptBefore] = useState(true)
  return (
    <section className="memory-area memory-words" aria-label="Your words">
      <h3>
        Your words <span className="muted memory-hint">only you write these</span>
      </h3>
      <span className="muted memory-hint">
        Said to every agent, always. <Hint doc={GUIDE.memoryKinds}>{TOLD_MORE}</Hint>
      </span>
      <Paper title="Your preferences" why="Yours in every project.">
        {/* Keyed by what is saved, so the text follows a save made here or elsewhere. */}
        <RulesBox
          key={memory.preferences ?? ''}
          rules={memory.preferences ?? null}
          what="preferences"
          onSave={on.onSavePreferences}
        />
        <Suggested records={memory.suggestions ?? []} onAdd={on.onAddPreference} onReject={on.onReject} />
      </Paper>
      <Paper title="This project’s rules" why="Kept in the folder’s .koloni/rules.md too, so they go into git.">
        {/* Keyed by what is saved, so the text follows a save made here or elsewhere. */}
        <RulesBox
          key={boxRules(memory) ?? ''}
          rules={boxRules(memory)}
          onSave={rules => {
            setKeptBefore(memory.rules_kept ?? true)
            return on.onSaveRules(rules)
          }}
        />
        {memory.rules_differ && <FolderRules rules={memory.rules} onUse={on.onSaveRules} />}
        {!keptBefore && memory.rules_kept && (
          <p role="status" className="muted">
            {KEPT_IN_FOLDER}
          </p>
        )}
        {memory.rules_not_read && <p className="alert">{memory.rules_not_read}</p>}
      </Paper>
      <Paper title="Project notes">
        <ProjectNotes text={memory.project_notes} onSave={on.onSaveProjectNotes} />
      </Paper>
      {linked && onLinked && (
        <p className="muted memory-hint">
          {linked.length > 0
            ? `Search deeper and Recall also look in the memory of ${linked.join(', ')}.`
            : 'Search deeper and Recall look in no other project’s memory.'}{' '}
          <button type="button" className="link-btn" onClick={onLinked}>
            Change
          </button>
        </p>
      )}
    </section>
  )
}

/** What KOLONİ's summariser suggests for your preferences (22b), under them: added by you, or not. Never by itself. */
function Suggested({
  records,
  onAdd,
  onReject,
}: {
  records: MemoryRecord[]
  onAdd: (id: string) => Promise<void>
  onReject: (id: string) => Promise<void>
}) {
  if (records.length === 0) return null
  return (
    <div role="group" aria-label="Suggested for your preferences" className="memory-section">
      <div className="muted memory-hint">
        {/* (What Add does is read before it is clicked: in sight, the rest behind the "?".) */}
        <span className="tag">suggested</span> Added, it is told to every agent in every project as your instruction.{' '}
        <Hint doc={GUIDE.memoryKinds}>
          What KOLONİ’s summariser took for a preference of yours from a finished message. Nothing enters your
          preferences unless you add it.
        </Hint>
      </div>
      {records.map(record => (
        <Suggestion key={record.id} record={record} onAdd={onAdd} onReject={onReject} />
      ))}
    </div>
  )
}
