import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'
const BASE = 'http://localhost:5174'
const API = 'http://127.0.0.1:5055/api'
const login = await (await fetch(API + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'supervisor@fieldtrack.com', password: 'Super123!' }) })).json()
const browser = await chromium.launch()
const groups = new Map()
for (const dark of [false, true]) {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, colorScheme: dark ? 'dark' : 'light' })
  await ctx.addInitScript((t) => localStorage.setItem('fieldtrack_token', t), login.token)
  const page = await ctx.newPage()
  for (const p of ['/login', '/', '/jobs', '/time-entries', '/reports', '/crew', '/sites']) {
    if (p === '/login') { await ctx.clearCookies(); }
    await page.goto(BASE + p)
    await page.waitForTimeout(1200)
    const axe = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze()
    for (const v of axe.violations) for (const n of v.nodes) {
      const d = n.any[0]?.data || {}
      const cls = (n.target.join(' ').match(/[.#][\w-]+/g) || []).slice(-1)[0] || n.target.join(' ').slice(0, 40)
      const key = `${dark ? 'dark ' : 'light'} fg=${d.fgColor} bg=${d.bgColor} ratio=${d.contrastRatio} need=${d.expectedContrastRatio}`
      const g = groups.get(key) || { n: 0, where: new Set(), size: d.fontSize }
      g.n++; g.where.add(cls); groups.set(key, g)
    }
  }
  await ctx.close()
}
await browser.close()
for (const [k, g] of [...groups.entries()].sort((a, b) => b[1].n - a[1].n)) console.log(`${String(g.n).padStart(4)}  ${k}  size=${g.size}  e.g. ${[...g.where].slice(0, 5).join(', ')}`)
