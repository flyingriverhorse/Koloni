import { Component, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/**
 * A page that throws while drawing shows a short note in its place instead of taking the
 * whole app down with it: the rail and the other pages keep working.
 */
export class PageGuard extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="conv-page" role="alert">
        <h2>This page could not be shown</h2>
        <p className="muted">
          Often the page and the server are different versions: restart KOLONİ, then reload. The other pages still work.
        </p>
        <p className="mono muted">{this.state.error.message}</p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    )
  }
}
