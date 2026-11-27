import { useLayoutEffect, useRef } from 'react'
import { CELL } from '../ready/cells'
import type { ReadyItem } from '../ready/ready'
import { kindWord } from '../ready/ReadyViews'
import { Cell } from './Cell'
import { CHAT_WORD, type ChatStands, nowSaid } from './chatStands'

/** The comb shows at most this many cells; the rest are said as a number. */
const MOST = 30

/** What a cell of the comb says: a chat's name and how it stands, or what waits and where. */
const waitsLabel = (item: ReadyItem) =>
  `${kindWord(item)}${item.what === 'card' ? ` in “${item.state.conversation.title}”` : ''}: ${CHAT_WORD.yours}`

/** Now's height on the page, as `--now-h`: a row the keyboard reaches is scrolled into view under Now, not behind it. */
function useRoomUnder() {
  const strip = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const at = strip.current
    const page = at?.parentElement
    if (!at || !page || typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(() => page.style.setProperty('--now-h', `${at.offsetHeight}px`))
    watch.observe(at)
    return () => watch.disconnect()
  }, [])
  return strip
}

/**
 * The Chats page's Now (0.1.10), over every folder, on top of the page and in sight while the list scrolls: a cell for
 * each chat at work, for each thing that waits for your word - Ready for you's rows, as the top bar's pill counts them -
 * and for each chat stuck or done today; one sentence that counts them, and the way to Ready for you, where what waits
 * is answered. Then what the cells mean.
 */
export function ChatsNow({
  items,
  working,
  stuck,
  done,
  read,
  onReady,
}: {
  items: ReadyItem[]
  /** The names of the chats at work, stuck today and done today. */
  working: string[]
  stuck: string[]
  done: string[]
  /** Whether the Board was read: how each chat stands is known. */
  read: boolean
  onReady?: () => void
}) {
  const chats = (titles: string[], stands: ChatStands) =>
    titles.map(title => [stands, `“${title}”: ${CHAT_WORD[stands]}${stands === 'running' ? '' : ' today'}`] as const)
  const cells = [
    ...chats(working, 'running'),
    ...items.map(item => ['yours', waitsLabel(item)] as const),
    ...chats(stuck, 'stuck'),
    ...chats(done, 'done'),
  ]
  const strip = useRoomUnder()
  return (
    <aside ref={strip} className="conv-now" aria-labelledby="conv-now-head">
      <div className="conv-now-strip">
        <h3 id="conv-now-head">
          Now <span className="muted">every folder</span>
        </h3>
        <div className="conv-now-box">
          {cells.length > 0 && (
            <span className="cell-comb">
              {cells.slice(0, MOST).map(([stands, label], at) => (
                <Cell key={at} {...CELL[stands]} label={label} big />
              ))}
              {cells.length > MOST && <span className="muted">+{cells.length - MOST} more</span>}
            </span>
          )}
          <p>
            {nowSaid(working.length, items.length, stuck.length, done.length, read)}
            {items.length > 0 && ' What waits is on Ready for you.'}
          </p>
          {onReady && (
            <button type="button" className="btn btn-small btn-primary" onClick={onReady}>
              Go to Ready
            </button>
          )}
        </div>
        {/* (Each cell's word beside it: a screen reader is told it once.) */}
        <div className="cell-legend" role="group" aria-label="What the cells say">
          {(Object.keys(CHAT_WORD) as ChatStands[]).map(stands => (
            <span key={stands}>
              <Cell {...CELL[stands]} label={CHAT_WORD[stands]} hidden /> {CHAT_WORD[stands]}
            </span>
          ))}
        </div>
      </div>
    </aside>
  )
}
