import { useState, type ReactNode } from 'react'
import type { BacklogDraft, DraftStory, NewBacklogTask, TodoTreeAdded, TodoTreeIn } from '../api/types'
import { useAsk } from '../memory/useAsk'

type Task = NewBacklogTask
type Shaped = { title: string; notes: string[]; tasks: Task[] }

interface Props {
  draft: BacklogDraft
  /** Adds this part of it: what was added - the goal made, so that the rest goes under it. Throws ApiError. */
  onAdd: (tree: TodoTreeIn) => Promise<TodoTreeAdded>
  /** Nothing of it is left. */
  onDrop: () => void
  /** A task's fields beyond its title, as a task's form has them. */
  taskFields: (id: string, task: Task, onTask: (task: Task) => void) => ReactNode
}

// An empty detail or criteria is none.
const clean = (task: Task): Task => ({
  ...task,
  title: task.title.trim(),
  detail: task.detail?.trim() || null,
  criteria: task.criteria?.trim() || null,
})
const editable = (task: Task): Task => ({ ...task, detail: task.detail ?? '', criteria: task.criteria ?? '' })
const shapedOf = (story: DraftStory): Shaped => ({ ...story, tasks: story.tasks.map(editable) })

/**
 * The Hive keeper's draft (0.1.8): a goal, its stories - each with its notes and tasks - and the tasks that stand
 * alone, all to change as you like; a story's Add adds it (under the goal), Add all the rest, ✕ leaves a task out.
 * Nothing is saved until added.
 */
export function DraftTree({ draft, onAdd, onDrop, taskFields }: Props) {
  const adding = useAsk()
  const [goal, setGoal] = useState(draft.goal ?? null)
  const [goalId, setGoalId] = useState<string | null>(null)
  const [stories, setStories] = useState<Shaped[]>((draft.stories ?? []).map(shapedOf))
  const [loose, setLoose] = useState<Task[]>(draft.tasks.map(editable))
  const left = (nextStories: Shaped[], nextLoose: Task[]) => {
    setStories(nextStories)
    setLoose(nextLoose)
    if (!nextStories.length && !nextLoose.length) onDrop()
  }
  const add = (some: Shaped[], alone: Task[]) =>
    void adding.ask(async () => {
      const added = await onAdd({
        goal: goalId ? null : goal?.trim() || null,
        goal_id: goalId,
        stories: some.map(one => ({ title: one.title.trim(), notes: one.notes, tasks: one.tasks.map(clean) })),
        tasks: alone.map(clean),
      }).catch(err => {
        setGoalId(null) // (the goal it made may be gone since: the next Add names it again)
        throw err
      })
      if (added.goal_id) setGoalId(added.goal_id)
      left(
        stories.filter(one => !some.includes(one)),
        loose.filter(one => !alone.includes(one)),
      )
    })
  const setTask = (story: Shaped | null, one: Task, next: Task) =>
    story
      ? setStories(now => now.map(s => (s === story ? { ...s, tasks: s.tasks.map(t => (t === one ? next : t)) } : s)))
      : setLoose(now => now.map(t => (t === one ? next : t)))
  const drop = (story: Shaped | null, one: Task) =>
    story
      ? left(
          stories
            .map(s => (s === story ? { ...s, tasks: s.tasks.filter(t => t !== one) } : s))
            .filter(s => s.tasks.length),
          loose,
        )
      : left(
          stories,
          loose.filter(t => t !== one),
        )
  // Each draft is numbered through the tree: "Draft 3" is the third task wherever it stands.
  let n = 0
  const taskRow = (story: Shaped | null, one: Task) => {
    const i = ++n
    return (
      <div key={i} role="group" aria-label={`Draft ${i}`} className="field todo-draft-task">
        <div className="field">
          <label htmlFor={`draft-${i}-title`}>Title</label>
          <input
            id={`draft-${i}-title`}
            className="input"
            maxLength={200}
            value={one.title}
            onChange={e => setTask(story, one, { ...one, title: e.target.value })}
          />
        </div>
        {taskFields(`draft-${i}`, one, next => setTask(story, one, next))}
        <button
          type="button"
          className="btn btn-small"
          aria-label={`Remove draft ${i}`}
          onClick={() => drop(story, one)}
        >
          ✕
        </button>
      </div>
    )
  }
  const untitled = (tasks: Task[]) => tasks.some(one => !one.title.trim())
  return (
    <section className="backlog-add" aria-label="Drafted tasks">
      <p className="muted">Written by {draft.by}: change them as you like. Nothing is saved until you add it.</p>
      {/* Held while adding: a draft changed then would be another, and added twice. */}
      <fieldset className="recipe-rows" disabled={adding.busy}>
        {goal !== null && !goalId && (
          <div className="field todo-draft-goal">
            <label htmlFor="draft-goal">Goal</label>
            <input
              id="draft-goal"
              className="input"
              maxLength={200}
              value={goal}
              onChange={e => setGoal(e.target.value)}
            />
          </div>
        )}
        {stories.map((story, s) => (
          <div key={s} role="group" aria-label={`Story ${s + 1}`} className="field todo-draft-story">
            <div className="field">
              <label htmlFor={`draft-story-${s}`}>Story</label>
              <input
                id={`draft-story-${s}`}
                className="input"
                maxLength={200}
                value={story.title}
                onChange={e =>
                  setStories(now => now.map(one => (one === story ? { ...one, title: e.target.value } : one)))
                }
              />
            </div>
            {story.notes.length > 0 && (
              <ul className="muted todo-draft-notes" aria-label={`Notes of ${story.title}`}>
                {story.notes.map((note, i) => (
                  <li key={i}>
                    <span aria-hidden="true">📓</span> {note}
                  </li>
                ))}
              </ul>
            )}
            {story.tasks.map(one => taskRow(story, one))}
            <div className="memory-actions">
              <button
                type="button"
                className="btn btn-small btn-primary"
                disabled={!story.title.trim() || untitled(story.tasks)}
                onClick={() => add([story], [])}
              >
                Add
              </button>
            </div>
          </div>
        ))}
        {loose.length > 0 && (
          <div role="group" aria-label="Without a story" className="field todo-draft-story">
            {stories.length > 0 && <span className="kicker">Without a story</span>}
            {loose.map(one => taskRow(null, one))}
            <div className="memory-actions">
              <button
                type="button"
                className="btn btn-small btn-primary"
                disabled={untitled(loose)}
                onClick={() => add([], loose)}
              >
                Add
              </button>
            </div>
          </div>
        )}
        <div className="memory-actions">
          <button
            type="button"
            className="btn btn-small"
            disabled={stories.some(one => !one.title.trim() || untitled(one.tasks)) || untitled(loose)}
            onClick={() => add(stories, loose)}
          >
            Add all
          </button>
        </div>
      </fieldset>
      {adding.error && (
        <div role="alert" className="alert">
          {adding.error}
        </div>
      )}
    </section>
  )
}
