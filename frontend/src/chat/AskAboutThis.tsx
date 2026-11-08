import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChatCircleText } from '@phosphor-icons/react'
import { useApp } from '../state/store'
import { linesIn, type Picked, quoteOf, writerOf } from './askAbout'

/**
 * Slice 80: text selected in a `[data-ask]` place - a file view, a diff, the chat's messages (its value: the file's path,
 * or empty) - shows a small "Ask about this" by it. It puts a quote into the message box, which goes to the Orchestrator
 * as any message. The first Tab goes to it, and Esc puts it away; it never takes the selection (read as it changes).
 */
export function AskAboutThis() {
  const [shown, setShown] = useState<{ picked: Picked; x: number; y: number } | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  // What was said of this selection - Esc, the first Tab - holds till another is made: a scroll only moves the button.
  const held = useRef<{ at: unknown[]; dismissed: boolean; offered: boolean }>({ at: [], dismissed: false, offered: false })
  useEffect(() => {
    const gone = () => {
      held.current.at = [] // (the same text selected again is a new selection)
      setShown(null)
    }
    const look = () => {
      const selection = document.getSelection()
      const typing = document.activeElement?.matches('input, textarea, [contenteditable="true"]')
      if (!selection || selection.isCollapsed || !selection.rangeCount || typing) return gone()
      const range = selection.getRangeAt(0)
      const node = range.commonAncestorContainer
      const root = (node instanceof Element ? node : node.parentElement)?.closest('[data-ask]')
      const said = selection.toString()
      if (!root || !said.trim()) return gone()
      const at = [range.startContainer, range.startOffset, range.endContainer, range.endOffset]
      if (at.some((one, i) => one !== held.current.at[i])) held.current = { at, dismissed: false, offered: false }
      if (held.current.dismissed) return setShown(null)
      const box = range.getBoundingClientRect()
      setShown({ picked: { path: root.getAttribute('data-ask') || null, ...linesIn(root, range, said) }, x: box.right, y: box.bottom })
    }
    const key = (event: KeyboardEvent) => {
      if (!button.current) return
      if (event.key === 'Escape') {
        // (first Esc puts this away, not the window the text is in)
        event.stopPropagation()
        held.current.dismissed = true
        setShown(null)
      } else if (event.key === 'Tab' && !event.shiftKey && !held.current.offered) {
        // (once: from it on, Tab goes on as it would)
        held.current.offered = true
        event.preventDefault()
        button.current.focus()
      }
    }
    document.addEventListener('selectionchange', look)
    // (the text moves under a fixed button as its place scrolls)
    document.addEventListener('scroll', look, true)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('selectionchange', look)
      document.removeEventListener('scroll', look, true)
      document.removeEventListener('keydown', key, true)
    }
  }, [])
  if (!shown) return null

  async function ask(picked: Picked) {
    held.current.dismissed = true
    setShown(null)
    const state = useApp.getState()
    // (the branch the Workspace reads: one looked at, else the project's own)
    const branch = (state.filesRef ?? state.gitBranch)?.replace(/^refs\/heads\//, '') ?? null
    const quote = quoteOf(picked, picked.path ? await writerOf(picked.path) : null, picked.path ? branch : null)
    const key = state.conv?.conversation.id ?? `new in ${state.projectId ?? ''}`
    const was = state.drafts[key] ?? ''
    state.setDraft(key, `${was}${was && !was.endsWith('\n\n') ? (was.endsWith('\n') ? '\n' : '\n\n') : ''}${quote}`)
    state.showChatTab('Chat', true)
    requestAnimationFrame(() => {
      const box = document.querySelector<HTMLTextAreaElement>('.composer-input')
      box?.focus()
      box?.setSelectionRange(box.value.length, box.value.length)
    })
  }

  return createPortal(
    <button
      ref={button}
      type="button"
      className="btn btn-primary ask-about"
      style={{ left: Math.min(shown.x, window.innerWidth - 170), top: Math.min(shown.y + 6, window.innerHeight - 40) }}
      // (a press here leaves the selection as it is)
      onMouseDown={event => event.preventDefault()}
      onClick={() => void ask(shown.picked)}
    >
      <ChatCircleText size={16} weight="bold" aria-hidden />
      Ask about this
    </button>,
    document.body,
  )
}
