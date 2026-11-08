import type { ReactNode } from 'react'

interface Props {
  /** The state's colour: one of the theme's (var(--ok), var(--warn), ...). */
  color: string
  /** The state in words. */
  children: ReactNode
}

/**
 * How a state is said - of an agent, a turn, a tool call or a command - wherever it is
 * said: in the chat, in the turn list, on the canvas and on the Board. A dot and the word,
 * in the state's colour; the dot is drawn, so the word alone is what is read out.
 */
export function StatusLabel({ color, children }: Props) {
  return (
    <span className="status" style={{ color }}>
      {children}
    </span>
  )
}
