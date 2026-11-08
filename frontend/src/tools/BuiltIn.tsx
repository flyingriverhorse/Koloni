import { useState } from 'react'
import { errorText } from '../api/client'
import type { BuiltinTool } from '../api/types'
import { ROLE_TOOLS } from '../agents/roleTools'

/** Its name as a role's tile says it. */
const tileOf = (name: string) => ROLE_TOOLS.find(tool => tool.name === name)?.label ?? name

/** What each of KOLONİ's own switchable tools does; one the server lists that is not here shows by its name. */
const BUILT_IN: Record<string, { label: string; line: string }> = {
  web_search: { label: tileOf('web_search'), line: 'Looks things up on the web: a few results with their addresses' },
  http_request: { label: tileOf('http_request'), line: 'Calls an address on the internet and reads its answer' },
  read_attachment: { label: 'Read attached files', line: 'Reads the text of files you attach to a message: code, PDF, Word' },
  recall_output: { label: 'Read earlier output again', line: 'Reads the whole output of an earlier command or tool in this chat that was cut short' },
  diagram_image: { label: tileOf('diagram_image'), line: 'Draws a draw.io diagram of the project as a PNG or SVG picture beside it' },
}

/** KOLONİ's own tools: one switched off is offered to no agent, whatever its role lists. */
export function BuiltIn({ tools, onSwitch }: { tools: BuiltinTool[]; onSwitch: (name: string, on: boolean) => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  return (
    <section className="tool-group tools-builtin" aria-label="Built-in tools">
      {tools.map(tool => {
        const about = BUILT_IN[tool.name]
        return (
          <label key={tool.name} className="tool-row" htmlFor={`builtin-${tool.name}`}>
            <span>
              {about?.label} <span className="mono muted">{tool.name}</span>
              {about && (
                <span id={`builtin-${tool.name}-line`} className="choice-note">
                  {about.line}
                </span>
              )}
            </span>
            <input
              id={`builtin-${tool.name}`}
              type="checkbox"
              role="switch"
              aria-label={about?.label ?? tool.name}
              aria-describedby={about ? `builtin-${tool.name}-line` : undefined}
              checked={tool.on}
              onChange={() => {
                setError(null)
                onSwitch(tool.name, !tool.on).catch(err => setError(errorText(err)))
              }}
            />
          </label>
        )
      })}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
