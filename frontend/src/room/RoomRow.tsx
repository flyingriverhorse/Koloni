import { UsersThree } from '@phosphor-icons/react'
import type { Room } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { isRunning, roomTag, waitsForYou } from './roomText'

/** A turn's room as the chat names it, under the message that was its goal or the call that opened it: one line, "Room · <topic> · done · 1 of 1 · open", that opens its window. */
export function RoomRow({ state, room, onOpen }: { state: ConvState; room: Room; onOpen: () => void }) {
  return (
    <div className="tool-row">
      <button type="button" className="tool-row-head" title="Open the room" data-room-line={room.id} onClick={onOpen}>
        <span style={{ color: 'var(--tool-team)', display: 'grid' }}>
          <UsersThree size={13} className={isRunning(room) ? 'pulse' : undefined} />
        </span>
        <span className="tool-row-summary">
          <strong>Room</strong> <span className="muted">· {room.goal}</span>
        </span>{' '}
        <span className="tool-row-status mono muted">
          {roomTag(state, room)} · <span className="link-btn">Open</span>
        </span>
        {waitsForYou(state, room) && <>{' '}<span className="tag tag-warn">waits for you</span></>}
      </button>
    </div>
  )
}
