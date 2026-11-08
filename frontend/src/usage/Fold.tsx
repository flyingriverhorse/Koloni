import type { ReactNode } from 'react'

/** A section of the Usage page folded under its heading, closed at first; what it holds is counted beside the heading. */
export function Fold({ title, count, id, children }: { title: string; count: string; id?: string; children: ReactNode }) {
  return (
    <section className="memory-section" aria-label={title}>
      <details className="usage-fold" id={id}>
        <summary>
          <h3>{title}</h3>
          <span className="muted">{count}</span>
        </summary>
        {children}
      </details>
    </section>
  )
}
