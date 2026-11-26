import { useState } from 'react'
import { useConfirm } from '../shell/Confirm'
import { spaced } from './memoryText'
import { MAX_ABOUT, MAX_TEXT, useAsk } from './useAsk'

type Told = 'rules' | 'preferences' | 'notes'
const MOST: Record<Told, number> = { rules: 1500, preferences: 1500, notes: 4000 }
const LABEL: Record<Told, string> = { rules: 'Rules', preferences: 'Preferences', notes: 'Project notes' }
const EXAMPLE: Record<Told, string> = {
  rules: 'For example: sign off every commit.',
  preferences: 'For example: answer in Turkish; keep answers short.',
  notes: 'A line each, as you added them at the end of a turn (Add to Project notes?).',
}

interface RulesProps {
  rules: string | null
  onSave: (rules: string) => Promise<void>
  /** The same box for your preferences (22b): one text for every project - and (0.1.10) for the Project notes. */
  what?: Told
}

const RULES_DIFFER = 'The folder’s rules.md differs from what you saved here; Full auto’s check goes by what you saved.'

/**
 * K-yargıç: the folder's rules.md where it says other than the rules saved here, which Full auto's check of a harmful-looking
 * command goes by (a pull or a script may have changed the file) - and one click, in sight, to take it here.
 */
export function FolderRules({ rules, onUse }: { rules: string | null; onUse: (rules: string) => Promise<void> }) {
  const { busy, error, ask } = useAsk()
  return (
    <div className="memory-form">
      <p className="muted">{RULES_DIFFER}</p>
      <pre className="mono">{rules ?? ''}</pre>
      <div className="memory-actions">
        <button
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => void ask(() => onUse(rules ?? ''))}
        >
          Use the folder’s rules here
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/** What agents working in this project are always told, in your words. Only you write it. */
export function RulesBox({ rules, onSave, what = 'rules' }: RulesProps) {
  const { busy, error, ask } = useAsk()
  const [draft, setDraft] = useState(rules ?? '')
  return (
    <form
      className="memory-form"
      onSubmit={event => {
        event.preventDefault()
        void ask(() => onSave(draft))
      }}
    >
      <div className="field">
        <label htmlFor={`memory-${what}`}>{LABEL[what]}</label>
        <textarea
          id={`memory-${what}`}
          className="input"
          rows={5}
          maxLength={MOST[what]}
          value={draft}
          placeholder={EXAMPLE[what]}
          onChange={e => setDraft(e.target.value)}
        />
      </div>
      <div className="memory-actions">
        <button type="submit" className="btn btn-small btn-primary" disabled={busy || draft === (rules ?? '')}>
          Save {what === 'notes' ? 'Project notes' : what}
        </button>
        <span className="mono muted memory-count">
          {spaced(draft.length)} / {spaced(MOST[what])}
        </span>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </form>
  )
}

/**
 * 0.1.10: the rules' second box - the Project notes, what you kept at turns' ends ("Add to Project notes?"), a line
 * each; the Orchestrator is given them every turn as notes, never as your rules.
 */
export function ProjectNotes({ text, onSave }: { text?: string | null; onSave: (text: string) => Promise<void> }) {
  return (
    <>
      <p className="muted memory-hint">
        Project notes: what you kept at the end of a turn (Add to Project notes?), a line each - a fixed finding or a
        change to docs/. The Orchestrator is given them every turn, as notes written from agents’ work: not as your
        instructions, and never in the folder’s rules.md. Adding more waits once they hold 4 000 characters.
      </p>
      {/* Keyed by what is saved, so the text follows a save made here or elsewhere. */}
      <RulesBox key={text ?? ''} rules={text ?? null} what="notes" onSave={onSave} />
    </>
  )
}

export interface NewFact {
  text: string
  about: string | null
  file: string | null
  start_line: number | null
  end_line: number | null
}

const lineOf = (typed: string): number | null => (typed.trim() ? Number(typed) : null)

/**
 * A fact in your own words, straight into the core; with file lines it rests on those. `from`:
 * the words and subject it starts with (a note made a fact) - never the note's file, which it
 * does not rest on.
 */
export function WriteBox({
  onWrite,
  from,
}: {
  onWrite: (fact: NewFact) => Promise<void>
  from?: { text: string; about: string; n: number }
}) {
  const { busy, error, ask } = useAsk()
  const confirm = useConfirm()
  const [text, setText] = useState(from?.text ?? '')
  const [about, setAbout] = useState(from?.about ?? '')
  const [file, setFile] = useState('')
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  // Another note made a fact while the box is open: filled at once if it is empty; what you typed is not lost unasked.
  const [filled, setFilled] = useState(from?.n)
  if (from && from.n !== filled) {
    setFilled(from.n)
    const fill = () => {
      for (const clear of [setFile, setFirst, setLast]) clear('')
      setText(from.text)
      setAbout(from.about)
    }
    if (text.trim() && text !== from.text) confirm.ask('Replace what you typed with the note’s words?', 'Replace', fill)
    else fill()
  }
  return (
    <form
      className="memory-form"
      onSubmit={event => {
        event.preventDefault()
        const fact: NewFact = {
          text: text.trim(),
          about: about.trim() || null,
          file: file.trim() || null,
          start_line: lineOf(first),
          end_line: lineOf(last),
        }
        void ask(() => onWrite(fact)).then(done => {
          if (done) for (const clear of [setText, setAbout, setFile, setFirst, setLast]) clear('')
        })
      }}
    >
      <div className="memory-row memory-add">
        <div className="field memory-grow">
          <label htmlFor="new-fact">Fact</label>
          <input
            id="new-fact"
            className="input"
            maxLength={MAX_TEXT}
            value={text}
            placeholder="One plain statement of what is the case in this project"
            onChange={e => setText(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-small btn-primary" disabled={busy || !text.trim()}>
          Add to the core
        </button>
        <span className="mono muted memory-count">
          {text.length} / {MAX_TEXT}
        </span>
      </div>
      {/* (Open when it starts with a subject: what is filled in is in sight.) */}
      <details className="more" open={Boolean(from?.about)}>
        <summary>Subject, file and lines</summary>
        <div className="memory-row">
          <div className="field memory-grow">
            <label htmlFor="new-about">Subject</label>
            <input
              id="new-about"
              className="input"
              maxLength={MAX_ABOUT}
              value={about}
              placeholder="What it is about; with none it is only found by looking it up"
              onChange={e => setAbout(e.target.value)}
            />
          </div>
          <div className="field memory-grow">
            <label htmlFor="new-file">File</label>
            <input
              id="new-file"
              className="input mono"
              value={file}
              placeholder="Optional; a path in the project"
              onChange={e => setFile(e.target.value)}
            />
          </div>
          <div className="field memory-line">
            <label htmlFor="new-first">First line</label>
            <input
              id="new-first"
              className="input mono"
              type="number"
              min={1}
              value={first}
              onChange={e => setFirst(e.target.value)}
            />
          </div>
          <div className="field memory-line">
            <label htmlFor="new-last">Last line</label>
            <input
              id="new-last"
              className="input mono"
              type="number"
              min={1}
              value={last}
              onChange={e => setLast(e.target.value)}
            />
          </div>
        </div>
        <p className="muted memory-hint">
          With a file and lines, the fact is given to agents only while those lines read as they do now. Without them it
          is kept as your own words, with no source.
        </p>
      </details>
      {confirm.shown()}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </form>
  )
}
