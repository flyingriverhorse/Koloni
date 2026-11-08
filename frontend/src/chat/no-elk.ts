// Stands in for elkjs (EPL-2.0) and mermaid's ELK layout module, which are not shipped (slice 68,
// the user's decision): vite.config.ts points both here. Diagrams are laid out with dagre, which
// Markdown's Diagram asks mermaid for; this is reached only if something asks for ELK anyway.
const unavailable = (): never => {
  throw new Error('elk layout is not available')
}

export const render = unavailable

export default class ELK {
  constructor() {
    unavailable()
  }
}
