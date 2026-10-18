// Browser audit of FieldTrack against a DISPOSABLE stack (backend :5055 with a scratch SQLite DB, frontend :5174).
// Run with:  node audit_browser.mjs <outDir>
import { chromium, firefox, webkit } from 'playwright'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'
import path from 'node:path'

const OUT = process.argv[2] || './out'
const SHOTS = path.join(OUT, 'screens')
fs.mkdirSync(SHOTS, { recursive: true })
const BASE = 'http://localhost:5174'
const API = 'http://127.0.0.1:5055/api'
const ACCOUNTS = {
  admin: ['admin@fieldtrack.com', 'Admin123!'],
  dispatcher: ['dispatch@fieldtrack.com', 'Dispatch123!'],
  supervisor: ['supervisor@fieldtrack.com', 'Super123!'],
}
const VIEWPORTS = { desktop: { width: 1366, height: 768 }, tablet: { width: 820, height: 1180 }, mobile: { width: 390, height: 844 } }
const PAGES = [
  ['dashboard', '/'], ['jobs', '/jobs'], ['live-map', '/live-map'], ['sites', '/sites'], ['crew', '/crew'], ['time-entries', '/time-entries'], ['reports', '/reports'],
]
const results = { startedAt: new Date().toISOString(), checks: [], axe: {}, layout: {}, notes: [] }
const check = (id, ok, detail = '') => {
  results.checks.push({ id, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${detail}`)
}

async function api(method, p, token, body) {
  const r = await fetch(API + p, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined })
  return { status: r.status, body: await r.json().catch(() => null) }
}
async function tokenFor(role) {
  const [email, password] = ACCOUNTS[role]
  return (await api('POST', '/auth/login', null, { email, password })).body.token
}
const tokens = {}
for (const r of Object.keys(ACCOUNTS)) tokens[r] = await tokenFor(r)

const ENGINE = process.env.BROWSER || 'chromium'
const browser = await { chromium, firefox, webkit }[ENGINE].launch({ headless: true })
console.log('browser engine:', ENGINE, browser.version())
results.engine = ENGINE
results.engineVersion = browser.version()
async function open(role, vp = 'desktop', opts = {}) {
  const ctx = await browser.newContext({ viewport: VIEWPORTS[vp], colorScheme: opts.dark ? 'dark' : 'light', locale: 'en-GB' })
  if (role) await ctx.addInitScript(([k, v]) => localStorage.setItem(k, v), ['fieldtrack_token', tokens[role]])
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 160)))
  page.on('console', (m) => m.type() === 'error' && !/tiles|stadiamaps|ERR_|net::|Failed to load resource/i.test(m.text()) && errors.push(m.text().slice(0, 160)))
  page.__errors = errors
  return { ctx, page }
}
async function settle(page, ms = 1500) {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(ms)
}

// ---------------------------------------------------------------- 1. layout + axe on every page, 3 viewports
for (const role of ['supervisor']) {
  for (const [vpName] of Object.entries(VIEWPORTS)) {
    const { ctx, page } = await open(role, vpName)
    for (const [name, url] of PAGES) {
      await page.goto(BASE + url)
      await settle(page, name === 'live-map' ? 3500 : 1200)
      const m = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth,
        small: [...document.querySelectorAll('button,a[href],input,select,textarea,[role=button]')].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24) && getComputedStyle(e).visibility !== 'hidden' }).length,
        title: document.title,
      }))
      results.layout[`${vpName}/${name}`] = m
      check(`layout ${vpName} ${name}: no horizontal page scroll`, m.scrollW <= m.innerW + 1, `scrollWidth ${m.scrollW} vs viewport ${m.innerW}`)
      check(`console ${vpName} ${name}: no page errors`, page.__errors.length === 0, page.__errors.slice(0, 2).join(' | '))
      if (vpName !== 'tablet') await page.screenshot({ path: path.join(SHOTS, `${role}_${vpName}_${name}.png`), fullPage: false })
      if (vpName !== 'tablet') {
        const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
        results.axe[`${vpName}/${name}/light`] = axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, sample: v.nodes[0]?.target?.join(' ') }))
      }
    }
    await ctx.close()
  }
}
// login page + dark mode
for (const dark of [false, true]) {
  for (const vpName of ['desktop', 'mobile']) {
    const { ctx, page } = await open(null, vpName, { dark })
    await page.goto(BASE + '/login'); await settle(page, 800)
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    results.axe[`${vpName}/login/${dark ? 'dark' : 'light'}`] = axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, sample: v.nodes[0]?.target?.join(' ') }))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)
    check(`layout ${vpName} login ${dark ? 'dark' : 'light'}: no horizontal scroll`, overflow)
    await page.screenshot({ path: path.join(SHOTS, `login_${vpName}_${dark ? 'dark' : 'light'}.png`) })
    await ctx.close()
  }
}
for (const [name, url] of [['dashboard', '/'], ['time-entries', '/time-entries'], ['jobs', '/jobs']]) {
  const { ctx, page } = await open('supervisor', 'desktop', { dark: true })
  await page.goto(BASE + url); await settle(page, 1200)
  const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  results.axe[`desktop/${name}/dark`] = axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, sample: v.nodes[0]?.target?.join(' ') }))
  await page.screenshot({ path: path.join(SHOTS, `supervisor_desktop_${name}_dark.png`) })
  await ctx.close()
}

// ---------------------------------------------------------------- 2. keyboard: sign-in form
{
  const { ctx, page } = await open(null)
  await page.goto(BASE + '/login'); await settle(page, 600)
  const order = []
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press('Tab')
    order.push(await page.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); return { tag: e.tagName, id: e.id, text: (e.textContent || '').trim().slice(0, 20), outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0, shadow: cs.boxShadow !== 'none' } }))
  }
  results.notes.push({ keyboardOrderLogin: order })
  check('keyboard login: first Tab stops reach the email then the password field', order.some((o) => o.id === 'email') && order.some((o) => o.id === 'password'), JSON.stringify(order.map((o) => o.id || o.tag)))
  check('keyboard login: every focused control shows a visible focus indicator', order.every((o) => o.outline || o.shadow), JSON.stringify(order.map((o) => (o.outline || o.shadow))))
  await page.fill('#email', 'supervisor@fieldtrack.com'); await page.fill('#password', 'Super123!')
  await page.keyboard.press('Enter')
  await page.waitForURL(BASE + '/', { timeout: 8000 }).catch(() => {})
  check('keyboard login: Enter submits the form and reaches the dashboard', page.url() === BASE + '/', page.url())
  await ctx.close()
}

// ---------------------------------------------------------------- 3. modal focus handling
{
  const { ctx, page } = await open('dispatcher')
  await page.goto(BASE + '/jobs'); await settle(page, 1200)
  const opener = page.getByRole('button', { name: /New job/ })
  await opener.focus(); await opener.press('Enter')
  await page.waitForSelector('[role=dialog]')
  const inside0 = await page.evaluate(() => document.querySelector('[role=dialog]').contains(document.activeElement))
  check('modal: opening it moves focus inside the dialog', inside0)
  let leaked = false
  for (let i = 0; i < 25; i++) { await page.keyboard.press('Tab'); if (!(await page.evaluate(() => document.querySelector('[role=dialog]')?.contains(document.activeElement)))) { leaked = true; break } }
  check('modal: Tab never moves focus out of the dialog (focus trap)', !leaked, leaked ? 'focus escaped to the page behind the dialog' : '')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
  check('modal: Escape closes it', (await page.locator('[role=dialog]').count()) === 0)
  const back = await page.evaluate(() => (document.activeElement?.textContent || '').trim().slice(0, 30) + '|' + document.activeElement?.tagName)
  check('modal: focus returns to the button that opened it', /New job/.test(back), `focus is on: ${back}`)
  await ctx.close()
}

// ---------------------------------------------------------------- 4. Live Map: network behaviour and lazy chunk
{
  const { ctx, page } = await open('supervisor')
  const reqs = []
  page.on('request', (r) => { if (r.url().startsWith(API) || /LiveMap/.test(r.url())) reqs.push(`${r.method()} ${r.url().replace(API, '/api').replace(BASE, '')}`.slice(0, 90)) })
  await page.goto(BASE + '/'); await settle(page, 1500)
  const before = reqs.filter((r) => /LiveMap/.test(r)).length
  reqs.length = 0
  await page.getByRole('link', { name: /Live Map/ }).click()
  await page.waitForTimeout(6000)
  const live = reqs.filter((r) => r === 'GET /api/map/live' || r.startsWith('GET /api/map/live?')).length
  const tick = reqs.filter((r) => r.includes('/safety/tick')).length
  check('live map: the LiveMap chunk is fetched only when the page is opened', before === 0 && reqs.some((r) => /LiveMap/.test(r)), `chunk requested before: ${before}`)
  check('live map: polls GET /api/map/live about once a second (6 s window)', live >= 4 && live <= 9, `GET /map/live x${live}`)
  check('live map: does not call POST /api/safety/tick any more', tick === 0, `POST /safety/tick x${tick}`)
  check('live map: the Safety panel is shown', await page.getByRole('region', { name: 'Safety and emergency' }).isVisible())
  await page.screenshot({ path: path.join(SHOTS, 'supervisor_desktop_live-map_loaded.png') })
  await ctx.close()
}

// ---------------------------------------------------------------- 5. safety controls by role (real popups)
async function popupButtons(page) {
  const names = []
  const markers = page.locator('.leaflet-marker-icon:has(.ft-worker)')
  const n = await markers.count()
  for (let i = 0; i < n && i < 14; i++) {
    await markers.nth(i).click({ force: true }).catch(() => {})
    await page.waitForTimeout(250)
    const btns = await page.locator('.leaflet-popup-content button').allInnerTexts()
    if (btns.length) { names.push(...btns); return { names: [...new Set(names)], workerIndex: i } }
  }
  return { names: [...new Set(names)], workerIndex: -1 }
}
for (const role of ['supervisor', 'dispatcher']) {
  const { ctx, page } = await open(role)
  await page.goto(BASE + '/live-map'); await settle(page, 4500)
  const { names } = await popupButtons(page)
  const hasControls = names.some((t) => /Trigger accident|SOS|break/i.test(t))
  if (role === 'supervisor') check('safety UI: Supervisor sees Trigger accident / SOS / break in a worker popup', hasControls, names.join(', '))
  else check('safety UI: Dispatcher sees NO accident/SOS/break buttons in worker popups', !hasControls, `buttons seen: [${names.join(', ')}]`)
  await page.screenshot({ path: path.join(SHOTS, `${role}_desktop_live-map_popup.png`) })
  await ctx.close()
}
{ // end to end in the UI: SOS -> EMERGENCY alert -> resolve
  const { ctx, page } = await open('supervisor')
  await page.goto(BASE + '/live-map'); await settle(page, 4500)
  const panel = page.getByRole('region', { name: 'Safety and emergency' })
  const resolveBtns = () => panel.getByRole('button', { name: /Resolved – false alarm/ }).count()
  const before = await resolveBtns() // emergencies that already exist (idle workers escalate on their own)
  const markers = page.locator('.leaflet-marker-icon:has(.ft-worker)')
  let pressed = false
  for (let i = 0; i < Math.min(await markers.count(), 14) && !pressed; i++) {
    await markers.nth(i).click({ force: true }).catch(() => {})
    await page.waitForTimeout(250)
    const sos = page.locator('.leaflet-popup-content button', { hasText: /^SOS$/ })
    if (await sos.count()) { await sos.first().click(); pressed = true }
  }
  check('safety UI: Supervisor can press SOS on an on-shift worker', pressed)
  if (pressed) {
    await page.waitForTimeout(2500)
    const during = await resolveBtns()
    check('safety UI: the SOS adds an EMERGENCY alert with a resolve control to the Safety panel', during === before + 1, `resolve buttons before ${before}, after SOS ${during}`)
    await page.screenshot({ path: path.join(SHOTS, 'supervisor_desktop_live-map_emergency.png') })
    await panel.getByRole('button', { name: /Resolved – false alarm/ }).last().click()
    await page.waitForTimeout(2500)
    const after = await resolveBtns()
    check('safety UI: resolving it as a false alarm removes that alert', after === before, `resolve buttons after resolving ${after}`)
  }
  await ctx.close()
}

// ---------------------------------------------------------------- 6. unsupported (far-away) site in the real browser
{
  const todayJobs = (await api('GET', `/jobs?date=${new Date().toISOString().slice(0, 10)}`, tokens.dispatcher)).body.jobs
  const j = todayJobs[0]
  const sites = (await api('GET', '/sites', tokens.dispatcher)).body.sites
  const orig = sites.find((s) => s.site_id === j.site_id)
  await api('PATCH', `/sites/${j.site_id}`, tokens.dispatcher, { latitude: 28.2096, longitude: 83.9856 }) // Pokhara
  const { ctx, page } = await open('supervisor')
  const timings = []
  page.on('response', async (r) => { if (r.url().includes('/api/map/live')) timings.push(r.request().timing().responseEnd) })
  const t0 = Date.now()
  await page.goto(BASE + '/live-map')
  const warn = page.getByText(/outside the supported road network/)
  await warn.waitFor({ timeout: 12000 }).catch(() => {})
  const dt = Date.now() - t0
  check('far-away site: the Live Map shows its warning within 5 s (was 13.5 s+ before the fix)', (await warn.count()) > 0 && dt < 5000, `${dt} ms`)
  check('far-away site: the rest of the map still renders (Safety panel visible)', await page.getByRole('region', { name: 'Safety and emergency' }).isVisible())
  await page.screenshot({ path: path.join(SHOTS, 'supervisor_desktop_live-map_unsupported-site.png') })
  const t1 = Date.now()
  const r = await api('GET', '/safety/config', tokens.supervisor)
  check('far-away site: other API calls stay fast (safety config)', r.status === 200 && Date.now() - t1 < 1000, `${Date.now() - t1} ms`)
  await ctx.close()
  await api('PATCH', `/sites/${j.site_id}`, tokens.dispatcher, { latitude: orig.latitude, longitude: orig.longitude }) // restore
}

// ---------------------------------------------------------------- 7. error + recovery states in the browser
{
  const { ctx, page } = await open('supervisor')
  await page.route('**/api/dashboard', (route) => route.abort())
  await page.goto(BASE + '/'); await settle(page, 1200)
  check('error state: dashboard shows a readable message when the server is unreachable', (await page.getByText(/Cannot reach the FieldTrack server/).count()) > 0)
  await page.unroute('**/api/dashboard')
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.waitForTimeout(1200)
  check('error state: "Try again" recovers once the server is back', (await page.getByText('Active jobs').count()) > 0)
  await page.route('**/api/jobs**', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Something went wrong on the server.', field: null }) }))
  await page.goto(BASE + '/jobs'); await settle(page, 1200)
  check('error state: a server 500 is shown with its message (no blank page)', (await page.getByText('Something went wrong on the server.').count()) > 0)
  await ctx.close()
}
{ // an invalid stored token sends the user to the sign-in page
  const { ctx, page } = await open(null)
  await page.goto(BASE + '/login'); await settle(page, 600)
  await page.evaluate(() => localStorage.setItem('fieldtrack_token', 'abc'))
  await page.goto(BASE + '/'); await settle(page, 1800)
  check('session: an invalid stored token sends the user to the sign-in page', page.url().endsWith('/login'), page.url())
  check('session: and the bad token is removed from storage', (await page.evaluate(() => localStorage.getItem('fieldtrack_token'))) === null)
  await ctx.close()
}

// ---------------------------------------------------------------- 7b. measured contrast of the primary button (rest / hover / focus)
{
  const { ctx, page } = await open('dispatcher')
  await page.goto(BASE + '/jobs'); await settle(page, 1200)
  const btn = page.getByRole('button', { name: /New job/ })
  const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
  const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05) }
  const rgb = (c) => c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number)
  const read = async () => btn.evaluate((e) => { const c = getComputedStyle(e); return { fg: c.color, bg: c.backgroundColor } })
  const rest = await read()
  await btn.hover(); await page.waitForTimeout(250)
  const hover = await read()
  await page.mouse.move(5, 5)
  await btn.focus(); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab'); await page.waitForTimeout(150)
  const focus = await read()
  const r1 = ratio(rgb(rest.fg), rgb(rest.bg)), r2 = ratio(rgb(hover.fg), rgb(hover.bg)), r3 = ratio(rgb(focus.fg), rgb(focus.bg))
  results.notes.push({ primaryButtonContrast: { rest: +r1.toFixed(2), hover: +r2.toFixed(2), focus: +r3.toFixed(2), restColors: rest, hoverColors: hover } })
  check('contrast: primary button label vs background, rest >= 4.5:1', r1 >= 4.5, `${r1.toFixed(2)}:1 (${rest.fg} on ${rest.bg})`)
  check('contrast: primary button, hover >= 4.5:1', r2 >= 4.5, `${r2.toFixed(2)}:1 (${hover.fg} on ${hover.bg})`)
  check('contrast: primary button, keyboard focus >= 4.5:1', r3 >= 4.5, `${r3.toFixed(2)}:1`)
  await ctx.close()
}
{ // wide tables are keyboard-reachable on a phone
  const { ctx, page } = await open('supervisor', 'mobile')
  await page.goto(BASE + '/time-entries'); await settle(page, 1500)
  const region = page.getByRole('region', { name: 'Data table' }).first()
  await region.focus()
  check('keyboard: a table region on a phone is focusable and named', await region.evaluate((e) => document.activeElement === e && e.scrollWidth >= e.clientWidth))
  await ctx.close()
}

// ---------------------------------------------------------------- 8. role buttons on pages (real DOM)
for (const [role, expectBtn] of [['dispatcher', { 'New job': true, 'Record time entry': false }], ['supervisor', { 'New job': false, 'Record time entry': true }]]) {
  const { ctx, page } = await open(role)
  await page.goto(BASE + '/jobs'); await settle(page, 1000)
  const hasNewJob = (await page.getByRole('button', { name: /New job/ }).count()) > 0
  await page.goto(BASE + '/time-entries'); await settle(page, 1000)
  const hasRecord = (await page.getByRole('button', { name: /Record time entry/ }).count()) > 0
  check(`role UI: ${role} sees New job=${expectBtn['New job']}, Record time entry=${expectBtn['Record time entry']}`, hasNewJob === expectBtn['New job'] && hasRecord === expectBtn['Record time entry'], `seen: ${hasNewJob}/${hasRecord}`)
  await ctx.close()
}

await browser.close()
results.finishedAt = new Date().toISOString()
results.summary = { passed: results.checks.filter((c) => c.ok).length, failed: results.checks.filter((c) => !c.ok).length }
fs.writeFileSync(path.join(OUT, 'browser_results.json'), JSON.stringify(results, null, 2))
console.log('\nSUMMARY', JSON.stringify(results.summary))
