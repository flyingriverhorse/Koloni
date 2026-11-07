import { type ReactNode, useState } from 'react'

const key = (page: string) => `koloni-how:${page}`

/** A page's long explanation, folded under "How this works": closed at first, then as it was last left on that page. */
export function HowItWorks({ page, children }: { page: string; children: ReactNode }) {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(key(page)) === '1'
    } catch {
      return false // storage is closed to the page
    }
  })
  return (
    <details
      className="more"
      open={open}
      onToggle={event => {
        const now = event.currentTarget.open
        setOpen(now)
        try {
          localStorage.setItem(key(page), now ? '1' : '0')
        } catch {
          // storage is closed to the page: it is only not remembered
        }
      }}
    >
      <summary>How this works</summary>
      {children}
    </details>
  )
}
