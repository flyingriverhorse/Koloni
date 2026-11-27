import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { api, errorText } from '../../api/client'
import type { AnswerLanguage, ExperimentalClis } from '../../api/types'
import { experimentalChanged } from '../../models/experimental'
import { GUIDE } from '../guide'
import { LANGUAGES } from '../ProjectSettings'
import { useJudgeModel } from './JudgeModel'
import { fromOf, Legend, Marked, More, Row, Said, SaveBar } from './part'
import { appSaid } from './said'

type WholeKey =
  'compact_at' | 'max_steps' | 'max_files' | 'max_mb' | 'stuck_minutes' | 'turn_hours' | 'runs_at_once' | 'workers'

/**
 * One whole-number setting of the app - `key` at `path`, from `low` to `high` - as the server keeps it (undefined
 * until read) and as typed: `at` is what is sent, undefined for anything else. `empty`: left empty it is null (none).
 */
function useWhole(
  path: string,
  key: WholeKey,
  low: number,
  high: number,
  failed: (why: string) => void,
  empty = false,
) {
  const [kept, setKept] = useState<number | null | undefined>(undefined)
  const [text, setText] = useState('')
  useEffect(() => {
    api.get<Record<string, number | null>>(path).then(
      read => {
        setKept(read[key])
        setText(read[key] === null ? '' : String(read[key]))
      },
      err => failed(errorText(err)),
    )
  }, [path, key, failed])
  const typed = text.trim()
  const value = Number(typed)
  const at = empty && typed === '' ? null : /^\d+$/.test(typed) && value >= low && value <= high ? value : undefined
  return {
    kept,
    text,
    setText,
    at,
    now: at === undefined ? kept : at,
    bad: kept !== undefined && at === undefined,
    changed: kept !== undefined && at !== kept,
    save: async () => setKept((await api.put<Record<string, number | null>>(path, { [key]: at }))[key]),
  }
}

/** A `useWhole` setting's line: its cell, its input, its why behind ⓘ, and what it takes where what is typed is not
 *  that. `usual`: what it is in a new KOLONİ. */
function WholeRow({
  id,
  label,
  why,
  setting,
  low,
  high,
  usual,
  also,
  placeholder,
}: {
  id: string
  label: string
  why: string
  setting: ReturnType<typeof useWhole>
  low: number
  high: number
  usual: number | null
  also?: ReactNode
  placeholder?: string
}) {
  return (
    <Row
      label={label}
      htmlFor={id}
      whyId={`${id}-more`}
      doc={GUIDE.settingsApp}
      why={why}
      from={setting.bad ? 'dirty' : fromOf(setting.at, setting.kept, usual)}
      warn={
        <>
          {setting.bad && (
            <span className="choice-note">
              A whole number from {low} to {high}
              {placeholder && ', or empty'}.
            </span>
          )}
          {also}
        </>
      }
    >
      <input
        id={id}
        className="input mono set-short"
        inputMode="numeric"
        value={setting.text}
        placeholder={placeholder}
        disabled={setting.kept === undefined}
        aria-invalid={setting.bad || undefined}
        aria-describedby={`${id}-more`}
        onChange={e => setting.setText(e.target.value)}
      />
    </Row>
  )
}

const TREE_HINT =
  'For every project: knowledge from a repository or a folder stops before it reads more than this. A learning at work keeps what it started with.'

/** Where Continue's extra steps are set: each project's. */
function ContinueNote({ toLimits }: { toLimits?: () => void }) {
  return (
    <span className="choice-note">
      Continue’s extra steps are each project’s:{' '}
      {toLimits ? (
        <button type="button" className="link-btn" onClick={toLimits}>
          This project › Limits and money
        </button>
      ) : (
        'This project › Limits and money'
      )}
      .
    </span>
  )
}

/** "Answer in" as it is sent: spaces once between its words, "auto" in any case as ''. */
const tidied = (text: string) => (/^auto$/i.test(text.trim()) ? '' : text.trim().replace(/ +/g, ' '))
/** Auto (''), or a language's name: at most 40 letters, spaces and hyphens. */
const isLanguage = (sent: string) => sent === '' || (sent.length <= 40 && /^\p{L}+(?:[ -]\p{L}+)*$/u.test(sent))

/**
 * Settings › The app › Agents: what holds in every project - the language agents write in, when a chat is compacted;
 * under More limits (closed unless asked open, each time with a new count: the project's link to the step limit) how
 * many steps an agent may take and how long a turn nobody watches may go; then, each kept as it is changed, whether
 * experimental features are offered and the model KOLONİ's judges ask.
 */
export function AppAgents({ toLimits, moreAsked }: { toLimits?: () => void; moreAsked?: number }) {
  const [readError, setReadError] = useState<string | null>(null)
  const language = useAnswerIn(setReadError)
  const compaction = useWhole('/compaction', 'compact_at', 50, 95, setReadError)
  const steps = useWhole('/steps', 'max_steps', 5, 200, setReadError)
  // (app/away.py STUCK_RANGE, CEILING_RANGE: the source of truth)
  const stuck = useWhole('/unattended', 'stuck_minutes', 5, 1440, setReadError)
  const ceiling = useWhole('/unattended', 'turn_hours', 1, 72, setReadError, true)
  // (app/knowledge.py FILES_RANGE, MB_RANGE: the source of truth)
  const treeFiles = useWhole('/knowledge-limits', 'max_files', 100, 1_000_000, setReadError)
  const treeMb = useWhole('/knowledge-limits', 'max_mb', 1, 10_240, setReadError)
  // (app/proof.py TEST_RUNS_RANGE, TEST_WORKERS_RANGE: the source of truth)
  const testRuns = useWhole('/test-load', 'runs_at_once', 1, 4, setReadError)
  const testWorkers = useWhole('/test-load', 'workers', 1, 16, setReadError)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const wholes = [compaction, steps, stuck, ceiling, treeFiles, treeMb, testRuns, testWorkers]
  const valid = language.valid && wholes.every(one => !one.bad)
  const changed = language.changed || wholes.some(one => one.changed)
  // (Under More limits, one not at its default: app/config.py max_steps, app/away.py STUCK_MINUTES and CEILING_HOURS,
  // app/knowledge.py MAX_CLONE_FILES and MAX_CLONE_BYTES, app/proof.py TEST_RUNS and TEST_WORKERS.)
  const usual: [typeof steps, number][] = [
    [steps, 25],
    [stuck, 30],
    [ceiling, 8],
    [treeFiles, 50_000],
    [treeMb, 300],
    [testRuns, 1],
    [testWorkers, 2],
  ]
  const set = usual.filter(([one, value]) => one.kept !== undefined && one.at !== value).length
  const judge = useJudgeModel()
  const experimental = useExperimental()
  // (What the save bar says changed, by name.)
  const named: [{ changed: boolean }, string][] = [
    [language, 'Answer in'],
    [compaction, 'Summarise a long context at (%)'],
    [steps, 'Steps an agent may take'],
    [stuck, 'Stuck after this many minutes with no progress'],
    [ceiling, 'An unattended turn runs at most (hours)'],
    [treeFiles, 'Knowledge reads at most (files)'],
    [treeMb, 'Knowledge reads at most (MB)'],
    [testRuns, 'KOLONİ’s test runs at once'],
    [testWorkers, 'Test processes per run'],
  ]

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      for (const one of wholes) if (one.changed) await one.save()
      if (language.changed) await language.save()
      setSaved(true)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className="settings-app-form" aria-label="App settings" onSubmit={submit}>
        <Said title="Agents">
          {appSaid({
            language: language.now,
            compactAt: compaction.now,
            judge: judge.judge,
            experimental: experimental.show,
          })}
        </Said>
        {readError && (
          <p role="alert" className="alert">
            The app’s settings could not be read: {readError}
          </p>
        )}
        {language.row}
        <WholeRow
          id="compact-at"
          usual={75}
          label="Summarise a long context at (%)"
          setting={compaction}
          low={50}
          high={95}
          why="For every project: once an agent’s context passes this much of its model’s window, the older part is summarised before its next step."
        />
        <More label="More limits" count={usual.length} set={set} bad={usual.some(([one]) => one.bad)} asked={moreAsked}>
          <WholeRow
            id="max-steps"
            usual={25}
            label="Steps an agent may take"
            setting={steps}
            low={5}
            high={200}
            why="For every project: the most model steps one sub-agent takes on a job before it stops. A team’s coordinator gets more for its recipe’s steps; a role’s own limit, where lower, still holds. The Orchestrator counts no steps: it stops when it goes round in circles, or at the Lead role’s own limit if you set one."
            also={<ContinueNote toLimits={toLimits} />}
          />
          <WholeRow
            id="stuck-minutes"
            usual={30}
            label="Stuck after this many minutes with no progress"
            setting={stuck}
            low={5}
            high={1440}
            why="For every project, in a To-do task’s turn and in a job while you’re away: the Orchestrator’s turn ends, its work kept, once nothing has moved for this long - no file of the turn changed, no agent finished its work, no failing command passed. A card waiting for you, a command or a model step under way, or an agent below it at work is not nothing."
          />
          <WholeRow
            id="turn-hours"
            usual={8}
            label="An unattended turn runs at most (hours)"
            setting={ceiling}
            low={1}
            high={72}
            placeholder="No limit"
            why="For every project: a To-do task’s turn or a job while you’re away ends after this many hours however it goes, its work kept - a last resort. Empty: no limit - a turn that keeps working (changes, agents at work, messages between agents) can then run without end."
          />
          <WholeRow
            id="tree-files"
            usual={50_000}
            label="Knowledge reads at most (files)"
            setting={treeFiles}
            low={100}
            high={1_000_000}
            why={TREE_HINT}
          />
          <WholeRow
            id="tree-mb"
            usual={300}
            label="Knowledge reads at most (MB)"
            setting={treeMb}
            low={1}
            high={10_240}
            why={TREE_HINT}
          />
          <WholeRow
            id="test-runs"
            usual={1}
            label="KOLONİ’s test runs at once"
            setting={testRuns}
            low={1}
            high={4}
            why="For every project: how many of the test runs KOLONİ makes at a turn’s end go at the same time; the rest wait their turn. More finishes sooner and loads the machine more. Agents’ own commands are not counted."
          />
          <WholeRow
            id="test-workers"
            usual={2}
            label="Test processes per run"
            setting={testWorkers}
            low={1}
            high={16}
            why="For every project: how many processes one of KOLONİ’s test runs may start, where its runner reads it (pytest-xdist’s -n auto). Agents’ own commands are not limited."
          />
        </More>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        <SaveBar
          changed={changed || !valid}
          valid={valid}
          busy={busy}
          said={named.filter(([one]) => one.changed).map(([, name]) => name)}
          saved={saved && !changed ? 'Saved' : ''}
        />
      </form>
      {experimental.view}
      {judge.view}
      <Legend />
    </>
  )
}

/** The app's Answer in: as the server keeps it (undefined until read) and as typed, '' Auto - tidied as it is sent, a
 *  language's name only: it goes into every agent's brief. `now`: what the section's sentence says, once read. */
function useAnswerIn(failed: (why: string) => void) {
  const [kept, setKept] = useState<string | undefined>(undefined)
  const [text, setText] = useState('')
  useEffect(() => {
    api.get<AnswerLanguage>('/answer-in').then(
      read => {
        setKept(read.answer_in ?? '')
        setText(read.answer_in ?? '')
      },
      err => failed(errorText(err)),
    )
  }, [failed])
  const sent = tidied(text)
  const valid = isLanguage(sent)
  return {
    now: kept === undefined ? undefined : sent,
    valid,
    changed: kept !== undefined && sent !== kept,
    save: async () =>
      setKept((await api.put<AnswerLanguage>('/answer-in', { answer_in: sent || null })).answer_in ?? ''),
    row: (
      <Row
        label="Answer in"
        htmlFor="answer-in"
        whyId="answer-in-more"
        doc={GUIDE.settingsApp}
        why="The language the agents write in, in every project. Auto: the language you write in. KOLONİ’s own screens stay in English."
        from={kept === undefined ? undefined : !valid ? 'dirty' : fromOf(sent, kept, '')}
        warn={!valid && <span className="choice-note">A language’s name: at most 40 letters, spaces and hyphens.</span>}
      >
        <input
          id="answer-in"
          className="input"
          list="answer-in-languages"
          value={text}
          placeholder="Auto"
          disabled={kept === undefined}
          aria-invalid={!valid || undefined}
          aria-describedby="answer-in-more"
          onChange={e => setText(e.target.value)}
        />
        <datalist id="answer-in-languages">
          {LANGUAGES.map(name => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </Row>
    ),
  }
}

/** Settings › The app › Agents, under its Save: whether the Models page offers what is experimental (0.1.8: agy;
 *  0.1.10: a CLI run Native) - kept as it is changed. */
function useExperimental() {
  const [show, setShow] = useState<boolean | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<ExperimentalClis>('/experimental-clis').then(
      read => setShow(read.show),
      err => setError(errorText(err)),
    )
  }, [])
  async function change(on: boolean) {
    setError(null)
    try {
      const saved = (await api.put<ExperimentalClis>('/experimental-clis', { show: on })).show
      setShow(saved)
      experimentalChanged(saved)
    } catch (err) {
      setError(errorText(err))
    }
  }
  return {
    show,
    view: (
      <div className="settings-app-form">
        <Marked from={fromOf(show, show, false)}>
          <label className="choice">
            <input
              type="checkbox"
              checked={show ?? false}
              disabled={show === undefined}
              onChange={e => void change(e.target.checked)}
            />
            <span>
              Show experimental features
              <span className="choice-note">
                Kept as you change it. Offers agy, and Native (a CLI with its own tools), under Experimental on the
                Models page: they are less measured than the rest. A provider already set up so works either way, tagged
                Experimental.
              </span>
            </span>
          </label>
        </Marked>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
      </div>
    ),
  }
}
