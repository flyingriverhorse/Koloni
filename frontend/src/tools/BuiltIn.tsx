import { type CSSProperties, useState } from 'react'
import { errorText } from '../api/client'
import type { BuiltinTool } from '../api/types'
import { ROLE_TOOLS, TOOL_GROUPS } from '../agents/roleTools'
import { Cell } from '../shell/Cell'
import { builtinRuns, runsCell } from './cells'

/** Its name as a role's tile says it. */
const tileOf = (name: string) => ROLE_TOOLS.find(tool => tool.name === name)?.label ?? name

/** What each of KOLONİ's own switchable tools does; one the server lists that is not here shows by its name. */
const BUILT_IN: Record<string, { label: string; line: string }> = {
  web_search: { label: tileOf('web_search'), line: 'Looks things up on the web: a few results with their addresses' },
  http_request: { label: tileOf('http_request'), line: 'Calls an address on the internet and reads its answer' },
  read_attachment: {
    label: 'Read attached files',
    line: 'Reads the text of files you attach to a message: code, PDF, Word',
  },
  recall_output: {
    label: 'Read earlier output again',
    line: 'Reads the whole output of an earlier command or tool in this chat that was cut short',
  },
  diagram_image: {
    label: tileOf('diagram_image'),
    line: 'Draws a draw.io diagram of the project as a PNG or SVG picture beside it',
  },
}

/** Where a switchable tool no role's tile lists goes: with the tools it reads after. */
const GROUP_OF: Record<string, string> = { read_attachment: 'Files', recall_output: 'Commands' }

/** A row of the tab: a role's tile, or a switchable tool no tile lists (`RoleTool.asks`: neither asks). */
interface Row {
  name: string
  label: string
  line: string
  asks: boolean
}

/** Each group's rows, as a role's Tools tab has them, the switchable ones no tile lists among them - or in "Other". */
function groupsOf(tools: BuiltinTool[]): [string, Row[]][] {
  const extra = tools.filter(tool => !ROLE_TOOLS.some(one => one.name === tool.name))
  const rows = (group: string): Row[] => [
    ...ROLE_TOOLS.filter(tool => tool.group === group).map(tool => ({ ...tool, asks: !!tool.asks })),
    ...extra
      .filter(tool => (GROUP_OF[tool.name] ?? 'Other') === group)
      .map(tool => ({
        name: tool.name,
        label: BUILT_IN[tool.name]?.label ?? tool.name,
        line: BUILT_IN[tool.name]?.line ?? '',
        asks: false,
      })),
  ]
  return [...TOOL_GROUPS, 'Other'].map(group => [group, rows(group)] as [string, Row[]]).filter(([, of]) => of.length)
}

/**
 * KOLONİ's own tools (0.1.10), grouped as a role's Tools tab has them, each with its cell: how it runs. A role's tools
 * are given on its Tools tab; the few with a switch here are switched off for every agent, whatever its role lists.
 */
export function BuiltIn({
  tools,
  onSwitch,
}: {
  tools: BuiltinTool[]
  onSwitch: (name: string, on: boolean) => Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  return (
    <section className="tools-builtin" aria-label="KOLONİ’s tools">
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="tools-groups">
        {groupsOf(tools).map(([group, rows]) => (
          <div
            key={group}
            className="tool-block tools-group"
            style={{ '--c': `var(--tool-${group.toLowerCase()}, var(--muted))` } as CSSProperties}
          >
            <h4>
              <span className="tool-mark" aria-hidden="true">
                {group[0]}
              </span>
              {group}
            </h4>
            {rows.map(row => {
              const switched = tools.find(tool => tool.name === row.name)
              const line = (switched && BUILT_IN[row.name]?.line) || row.line
              return (
                <div key={row.name} className="tools-tool">
                  <Cell {...runsCell(builtinRuns(row.asks, switched?.on ?? true))} />
                  <span className="tools-tool-text">
                    {switched ? <label htmlFor={`builtin-${row.name}`}>{row.label}</label> : row.label}
                    <span id={`builtin-${row.name}-line`} className="choice-note">
                      {line}
                    </span>
                  </span>
                  {switched ? (
                    <input
                      id={`builtin-${row.name}`}
                      type="checkbox"
                      role="switch"
                      className="switch"
                      aria-label={row.label}
                      aria-describedby={line ? `builtin-${row.name}-line` : undefined}
                      checked={switched.on}
                      onChange={() => {
                        setError(null)
                        onSwitch(row.name, !switched.on).catch(err => setError(errorText(err)))
                      }}
                    />
                  ) : (
                    <span className="muted tools-by-role" title="Given on a role’s Tools tab">
                      by role
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </section>
  )
}
