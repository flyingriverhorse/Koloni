export interface OutputPreview {
  head: string
  tail: string
  /** Lines left out between head and tail; 0 when the whole output is in `head`. */
  omitted: number
}

/** The start and end of a command's output, for a compact view in the chat. */
export function outputPreview(output: string, headLines = 20, tailLines = 40): OutputPreview {
  const lines = output.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n')
  if (output === '' || lines.length <= headLines + tailLines) {
    return { head: output === '' ? '' : lines.join('\n'), tail: '', omitted: 0 }
  }
  return {
    head: lines.slice(0, headLines).join('\n'),
    tail: lines.slice(-tailLines).join('\n'),
    omitted: lines.length - headLines - tailLines,
  }
}
