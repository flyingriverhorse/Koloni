import type { BacklogTask } from '../api/types'

/** A To-do task's turn in the chat: its label, its title, what makes it done - its whole brief folded under. */
export function TodoMessage({ task, label, brief }: { task: BacklogTask; label: string; brief: string }) {
  return (
    <div className="msg msg-user msg-todo" role="group" aria-label={label}>
      <div className="kicker">{label}</div>
      <div className="msg-todo-title">{task.title}</div>
      {task.criteria && (
        <p className="msg-todo-done">
          <span className="muted">Done when: </span>
          {task.criteria}
        </p>
      )}
      <details>
        <summary className="muted">The whole brief</summary>
        <pre className="backlog-pre">{brief}</pre>
      </details>
    </div>
  )
}
