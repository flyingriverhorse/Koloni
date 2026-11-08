import type { AwayJob } from '../api/types'

/**
 * A night's job that waits, on Ready for you: what it asks, whole, and the way to its chat - where the real card is.
 * No Allow or Take in here (tek-ev decision 1): a night's ask names an agent or a path, not what would run or change.
 */
export function NightRow({ job, onOpen }: { job: AwayJob; onOpen: (conversationId: string) => void }) {
  const asks = job.asks.map(one => one.text)
  const chat = job.conversation_id
  return (
    <div className="ready-night">
      <b>{job.title}</b>
      {job.why && !asks.includes(job.why) && <div className="muted">{job.why}</div>}
      {asks.map(text => (
        <div key={text} className="mono">
          {text}
        </div>
      ))}
      {job.kept.length > 0 && <div className="muted">Its work waits in a copy, for Take in in its chat.</div>}
      {chat && (
        <button type="button" className="btn btn-small btn-primary" onClick={() => onOpen(chat)}>
          Open its chat to answer
        </button>
      )}
    </div>
  )
}
