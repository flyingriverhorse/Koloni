import { createContext } from 'react'

/** Opens or closes a group by the id of its node; the canvas provides it. */
export const ToggleGroup = createContext<(nodeId: string) => void>(() => {})

/** What a node asks of the canvas it is drawn on. */
export interface Actions {
  /** Open Ready for you's panel, where what waits for you is answered (tek-ev §1). */
  openList?: () => void
  /** Stop one of the chat's teams, by its team's id. */
  stopTeam?: (teamId: string) => Promise<void>
  /** Finish now on a team's looped recipe: its work to Ready for you with what was found so far (batch-17). */
  finishTeam?: (teamId: string) => Promise<void>
  /** Show who said what on a talk line, by its id, and only that line (K-canvas-dili). */
  showTalk?: (edgeId: string) => void
  /** K-shared-bagli: light a card and its team's line - or a team's frame and its card - by its node's id. */
  light?: (nodeId: string) => void
  /** Open the Memory page, from a block's memory row. */
  openMemory?: () => void
  /** Open the To-do page, from the Assistant PO's node. */
  openTodo?: () => void
}

export const NodeActions = createContext<Actions>({})
