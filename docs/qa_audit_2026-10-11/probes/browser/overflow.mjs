import { chromium } from 'playwright'
const BASE = 'http://localhost:5174'
const API = 'http://127.0.0.1:5055/api'
const login = await (await fetch(API + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'supervisor@fieldtrack.com', password: 'Super123!' }) })).json()
const browser = await chromium.launch()
const cases = [['mobile', 390, 844, ['/', '/live-map', '/crew', '/time-entries', '/reports']], ['tablet', 820, 1180, ['/live-map']]]
for (const [name, width, height, pages] of cases) {
  const ctx = await browser.newContext({ viewport: { width, height } })
  await ctx.addInitScript((t) => localStorage.setItem('fieldtrack_token', t), login.token)
  const page = await ctx.newPage()
  for (const p of pages) {
    await page.goto(BASE + p)
    await page.waitForTimeout(2500)
    const offenders = await page.evaluate(() => {
      const vw = window.innerWidth
      const clipped = (el) => { for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) { const o = getComputedStyle(e).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true } return false }
      return [...document.querySelectorAll('body *')]
        .map((el) => ({ el, r: el.getBoundingClientRect() }))
        .filter(({ el, r }) => r.width > 0 && r.right > vw + 1 && !clipped(el) && getComputedStyle(el).position !== 'fixed')
        .slice(0, 6)
        .map(({ el, r }) => `${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ').slice(0, 2).join('.')} right=${Math.round(r.right)} width=${Math.round(r.width)}`)
    })
    console.log(`${name} ${p}:`, offenders.length ? offenders : 'none')
  }
  await ctx.close()
}
await browser.close()
