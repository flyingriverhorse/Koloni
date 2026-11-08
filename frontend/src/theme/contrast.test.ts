// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'

const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8')
const base = readFileSync(new URL('./base.css', import.meta.url), 'utf8')
// Every text colour of the theme, on every ground it is drawn on, by the WCAG 2 ratio: 4.5 or more.
const block = (selector: string) => css.slice(css.indexOf(selector), css.indexOf('}', css.indexOf(selector)))
const colours = (text: string) =>
  Object.fromEntries([...text.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map(m => [m[1], m[2]]))
const rgb = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
const hex = (c: number[]) => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('')
// The see-through grounds, as colour and alpha: --hover is an rgba(), --accent-soft a colour mixed with transparent.
const layers = (text: string) => {
  const hover = text.match(/--hover:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/)
  const soft = text.match(/--accent-soft:\s*color-mix\(in srgb,\s*(#[0-9a-f]{6})\s+(\d+)%,\s*transparent\)/i)
  return {
    hover: hover && { rgb: hover.slice(1, 4).map(Number), alpha: Number(hover[4]) },
    soft: soft && { rgb: rgb(soft[1]), alpha: Number(soft[2]) / 100 },
  }
}
// How the browser draws a colour at `alpha` over an opaque ground.
const over = (top: number[], alpha: number, ground: string) =>
  hex(top.map((v, i) => v * alpha + rgb(ground)[i] * (1 - alpha)))
const luminance = (hex: string) => {
  const [r, g, b] = rgb(hex)
    .map(c => c / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}
// Each tag's ground and text, from base.css: an opaque mix, so the row under it does not matter.
const tags = [
  ...base.matchAll(
    /\.(tag(?:-\w+)?) \{[^}]*?background: color-mix\(in srgb, var\((--[\w-]+)\) (\d+)%, var\((--[\w-]+)\)\);\s*color: var\((--[\w-]+)\)/g,
  ),
].map(m => ({ name: m[1], tint: m[2], pct: Number(m[3]) / 100, ground: m[4], fg: m[5] }))

const texts = ['--text', '--muted', '--faint', '--accent', '--ok', '--warn', '--del', '--request']
const flats = ['--bg', '--surface', '--panel']
const light = colours(block(':root'))
const darkOwn = colours(block('.dark'))
const dark = { ...light, ...darkOwn }

test('the dark theme sets each colour itself, and every tag has an opaque ground', () => {
  for (const token of [...texts, ...flats, '--accent-fg', '--accent-fill', '--border-strong'])
    expect(darkOwn[token], `${token} in .dark`).toMatch(/^#[0-9a-f]{6}$/i)
  for (const own of [layers(block(':root')), layers(block('.dark'))]) {
    expect(own.hover, '--hover').not.toBeNull()
    expect(own.soft, '--accent-soft').not.toBeNull()
  }
  expect(tags.map(t => t.name).sort()).toEqual(['tag', 'tag-accent', 'tag-del', 'tag-ok', 'tag-warn'])
})

for (const [name, theme, layer] of [
  ['light', light, layers(block(':root'))],
  ['dark', dark, layers(block('.dark'))],
] as const) {
  test(`every text colour reads on every ground in the ${name} theme`, () => {
    for (const fg of texts)
      for (const bg of flats) expect(ratio(theme[fg], theme[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    expect(ratio(theme['--accent-fg'], theme['--accent-fill']), '--accent-fg on --accent-fill').toBeGreaterThanOrEqual(4.5)
  })

  test(`a role's tool groups read on every ground, and the ground on them, in the ${name} theme`, () => {
    // The group's heading is in its colour; its mark and a tile's check are the ground on it.
    for (const group of ['files', 'commands', 'web', 'browser', 'team', 'to-do', 'memory'])
      for (const bg of flats) expect(ratio(theme[`--tool-${group}`], theme[bg]), `--tool-${group} on ${bg}`).toBeGreaterThanOrEqual(4.5)
  })

  test(`every text reads on a hovered or chosen row, and in its tags, in the ${name} theme`, () => {
    for (const bg of flats) {
      const hovered = over(layer.hover!.rgb, layer.hover!.alpha, theme[bg])
      const chosen = over(layer.soft!.rgb, layer.soft!.alpha, theme[bg])
      for (const fg of texts)
        expect(ratio(theme[fg], hovered), `${fg} on a hovered row on ${bg}`).toBeGreaterThanOrEqual(4.5)
      for (const fg of texts)
        expect(ratio(theme[fg], chosen), `${fg} on a chosen row on ${bg}`).toBeGreaterThanOrEqual(4.5)
      // An answer's inline path and command, on inline code's own ground (--hover).
      for (const fg of ['--code-title', '--code-keyword'])
        expect(ratio(theme[fg], hovered), `${fg} in inline code on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
    for (const tag of tags) {
      const ground = over(rgb(theme[tag.tint]), tag.pct, theme[tag.ground])
      expect(ratio(theme[tag.fg], ground), `.${tag.name} (${tag.fg}), on any row`).toBeGreaterThanOrEqual(4.5)
    }
  })
}

// CIE 1976 distance in L*a*b* (D65): about 2 is the least an eye tells apart; 25 is clearly another colour.
const lab = (hex: string) => {
  const [r, g, b] = rgb(hex).map(c => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4))
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  const [x, y, z] = [
    (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047,
    0.2126 * r + 0.7152 * g + 0.0722 * b,
    (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883,
  ].map(f)
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)]
}
const distance = (a: string, b: string) => Math.hypot(...lab(a).map((v, i) => v - lab(b)[i]))

test('muted text is a visible step from faint text in the dark theme (K-38f1)', () => {
  // (The light theme's two are as close; only the dark one was asked for.)
  expect(distance(dark['--muted'], dark['--faint']), '--muted from --faint').toBeGreaterThanOrEqual(5)
})

for (const [name, theme] of [
  ['light', light],
  ['dark', dark],
] as const) {
  test(`a warning is not read as the accent or as a failure, in the ${name} theme`, () => {
    // Honey says "at work, the main action, chosen"; a warning is another colour, and so is a failure.
    expect(distance(theme['--warn'], theme['--accent']), '--warn from --accent').toBeGreaterThanOrEqual(25)
    expect(distance(theme['--warn'], theme['--del']), '--warn from --del').toBeGreaterThanOrEqual(25)
  })

  test(`the strong border is seen against the grounds, in the ${name} theme`, () => {
    for (const bg of ['--bg', '--surface'])
      expect(ratio(theme['--border-strong'], theme[bg]), `--border-strong on ${bg}`).toBeGreaterThanOrEqual(3)
  })
}

// Coloured code (slice 42a): each colour of it reads on a plain line, an added one and a removed one,
// with the line numbers and the signs beside it - the tints changes.css lays over the window's ground.
const changes = readFileSync(new URL('./changes.css', import.meta.url), 'utf8')
const tint = (kind: string) => {
  const found = changes.match(new RegExp(`\\.diff-${kind} \\{\\s*background: color-mix\\(in srgb, var\\((--[\\w-]+)\\) (\\d+)%, transparent\\);`))
  return found && { token: found[1], alpha: Number(found[2]) / 100 }
}
for (const [name, theme, own] of [
  ['light', light, light],
  ['dark', dark, darkOwn],
] as const) {
  test(`coloured code reads on plain, added and removed lines in the ${name} theme`, () => {
    const code = Object.keys(own).filter(token => token.startsWith('--code-'))
    expect(code.length, 'the code colours, each set in this theme').toBeGreaterThanOrEqual(5)
    const [added, removed] = [tint('add'), tint('del')]
    expect(added && removed, '.diff-add and .diff-del grounds').toBeTruthy()
    const grounds = {
      plain: theme['--surface'],
      added: over(rgb(theme[added!.token]), added!.alpha, theme['--surface']),
      removed: over(rgb(theme[removed!.token]), removed!.alpha, theme['--surface']),
    }
    for (const fg of [...code, '--text', '--faint', '--ok', '--del'])
      for (const [ground, bg] of Object.entries(grounds)) expect(ratio(theme[fg], bg), `${fg} on a ${ground} line`).toBeGreaterThanOrEqual(4.5)
  })
}

test('an answer colours its paths, commands and bold words with the tokens checked above (K-sohbet-renk)', () => {
  const rule = (selector: string) => base.match(new RegExp(`${selector.replace(/\./g, '\\.')} \\{\\s*color: var\\((--[\\w-]+)\\);`))?.[1]
  expect(rule('.markdown .md-path')).toBe('--code-title')
  expect(rule('.markdown .md-command')).toBe('--code-keyword')
  expect(rule('.markdown strong')).toBe('--accent')
})
