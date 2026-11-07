import { times } from '../shell/repeats'

/**
 * What KOLONİ told an agent in the middle of its work about a fact it had been given from
 * memory when it started: that its source changed, or that you removed it. KOLONİ's words,
 * not the agent's and not yours. `count`: how many times in a row it was told the same.
 */
export function MemoryTold({ content, className = 'msg-from', count = 1 }: { content: string; className?: string; count?: number }) {
  return (
    <div role="note" aria-label="Told by KOLONİ about its memory" className={className}>
      <div className="asked-by mono">told by KOLONİ, about what it was given from memory{times(count)}</div>
      <div className="msg-quote">{content}</div>
    </div>
  )
}
