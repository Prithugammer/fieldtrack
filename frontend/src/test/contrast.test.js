import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Reads the real design tokens and checks WCAG 2.1 contrast, so a colour change that breaks AA fails here.
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
const [light, dark] = (() => {
  const i = css.indexOf(":root[data-theme='dark']")
  return [css.slice(0, i === -1 ? undefined : i), i === -1 ? '' : css.slice(i)]
})()

const token = (block, name) => {
  const m = block.match(new RegExp(String.raw`--${name}:\s*(#[0-9a-fA-F]{6})`))
  if (!m) throw new Error(`token --${name} not found`)
  return m[1]
}
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const t = (name) => token(light, name)

describe('WCAG 2.1 AA contrast of the design tokens (4.5:1 for normal text)', () => {
  it('primary button label on the brand orange, in every state', () => {
    const fg = t('color-on-orange')
    expect(ratio(fg, t('color-orange'))).toBeGreaterThanOrEqual(4.5) // rest: 6.11
    expect(ratio(fg, t('color-orange-600'))).toBeGreaterThanOrEqual(4.5) // hover: 4.96
  })
  it('white on the old orange really was too low (documents why the label is dark)', () => {
    expect(ratio('#ffffff', t('color-orange'))).toBeLessThan(3)
  })
  it('keeps the same label colour in the dark theme (the orange does not change)', () => {
    expect(() => token(dark, 'color-orange')).toThrow() // not redefined, so the light values apply
    expect(ratio(t('color-on-orange'), t('color-orange'))).toBeGreaterThanOrEqual(4.5)
  })
  it('success button (white on green), muted text on page and card', () => {
    expect(ratio('#ffffff', t('color-green-600'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(t('color-muted'), t('color-bg'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(t('color-muted'), '#ffffff')).toBeGreaterThanOrEqual(4.5)
  })
  it('muted text in the dark theme', () => {
    expect(ratio(token(dark, 'color-muted'), token(dark, 'color-bg'))).toBeGreaterThanOrEqual(4.5)
  })
})
