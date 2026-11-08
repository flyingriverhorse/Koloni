import type { ReactNode } from 'react'

/**
 * A card's longer notes, folded under Details (sample A, 7 Nov): only what explains its buttons. What warns of what a
 * thing runs, sends or spends stays in sight on the card (Hint.test), and no button or field goes in here.
 */
export function CardMore({ children }: { children: ReactNode }) {
  return (
    <details className="card-more">
      <summary>Details</summary>
      <div className="card-more-body">{children}</div>
    </details>
  )
}
