import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ModelFacts, ModelInput } from '../api/types'
import { InputIcons, inputsLine, inputText, MarkInputs, withMarks } from './inputs'

const facts = (inputs: ModelFacts['inputs']): ModelFacts => ({
  efforts: null, context_window: null, max_output: null, price: null, tier: null, deprecated: null, sources: {}, catalogue_date: null, failed: false, inputs,
})

describe('what a model takes besides text', () => {
  it('says who said it, and only icons for what it takes', () => {
    render(<InputIcons facts={facts([{ kind: 'image', takes: true, source: 'tried' }, { kind: 'video', takes: false, source: 'models.dev' }])} />)
    expect(screen.getByRole('img', { name: 'images ✓ (seen)' })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /video/ })).toBeNull()
    expect(inputText({ kind: 'video', takes: true, source: 'models.dev' })).toBe('takes video, said by models.dev')
    expect(inputText({ kind: 'image', takes: false, source: 'tried' })).toBe('doesn’t take images (tried)')
  })

  it('shows nothing where nothing is known', () => {
    const { container } = render(<InputIcons facts={facts([])} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('says all it takes on one line, each source once', () => {
    expect(inputsLine([
      { kind: 'image', takes: true, source: 'models.dev' }, { kind: 'video', takes: true, source: 'models.dev' },
      { kind: 'audio', takes: false, source: 'models.dev' }, { kind: 'pdf', takes: true, source: 'models.dev' },
    ])).toBe('images, video, PDFs; not audio (models.dev)')
    expect(inputsLine([{ kind: 'image', takes: true, source: 'tried' }, { kind: 'pdf', takes: false, source: 'models.dev' }]))
      .toBe('images (tried) · not PDFs (models.dev)')
    expect(inputsLine([])).toBeNull()
  })

  it('shows what is known in the boxes until the user marks, and a click starts from there', async () => {
    const changed: ModelInput[][] = []
    render(<MarkInputs name="m" marked={null} onChange={inputs => changed.push(inputs)}
      known={[{ kind: 'image', takes: true, source: 'models.dev' }, { kind: 'pdf', takes: true, source: 'models.dev' },
        { kind: 'pdf', takes: false, source: 'tried' }]} />)
    expect(screen.getByLabelText('m takes images')).toBeChecked()
    expect(screen.getByLabelText('m takes PDFs')).not.toBeChecked() // (what was tried wins)
    await userEvent.click(screen.getByLabelText('m takes video'))
    expect(changed).toEqual([['image', 'video']])
  })

  it('takes the user’s marks at once, under what was tried', () => {
    const marked = withMarks(facts([{ kind: 'image', takes: false, source: 'tried' }]), ['image', 'pdf'])!
    expect(marked.inputs.find(i => i.kind === 'image')).toEqual({ kind: 'image', takes: false, source: 'tried' })
    expect(marked.inputs.find(i => i.kind === 'pdf')).toEqual({ kind: 'pdf', takes: true, source: 'you' })
  })
})
