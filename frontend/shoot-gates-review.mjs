import puppeteer from 'puppeteer-core'
import fs from 'fs'
const out = process.argv[2] || '../screenshots'
fs.mkdirSync(out, { recursive: true })
const browser = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1440,900'] })
const page = await browser.newPage(); await page.setViewport({ width: 1440, height: 900 })
const wait = async (fn, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return; await new Promise(r => setTimeout(r, 400)) }; throw new Error('timeout') }

// Prefer a succeeded task with a gate
const tasks = await (await fetch('http://localhost:8787/api/tasks')).json()
let tid = process.env.TID || tasks.find(t => t.gate?.checks)?.id || tasks.find(t => t.status === 'succeeded')?.id
if (!tid) {
  const r = await (await fetch('http://localhost:8787/api/tasks', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ prompt: 'Build a monthly revenue mart with AOV', engine: 'mock' }) })).json()
  tid = r.id
  await wait(async () => { const t = await (await fetch(`http://localhost:8787/api/tasks/${tid}`)).json(); return t.status === 'succeeded' && t.gate }, 180000)
}
console.log('task', tid)
await page.goto(`http://localhost:5173/?task=${tid}&tab=gates`, { waitUntil: 'networkidle0' })
await wait(async () => page.evaluate(() => !!document.body.innerText.match(/Definition of Done|Not done yet/)))
await page.screenshot({ path: `${out}/gate-scorecard.png`, fullPage: false })
console.log('gate-scorecard')

await page.setViewport({ width: 1440, height: 1500 })
await page.goto(`http://localhost:5173/?task=${tid}&tab=review`, { waitUntil: 'networkidle0' })
await wait(async () => page.evaluate(() => !!document.body.innerText.match(/Review this change|High risk|Medium risk|Low risk|Preparing review/)))
await wait(async () => page.evaluate(() => !document.body.innerText.includes('Preparing review')), 120000).catch(() => {})
await page.screenshot({ path: `${out}/review-analyst.png`, fullPage: false })
console.log('review')
// scroll to verdict
await page.evaluate(() => { document.querySelectorAll('.overflow-auto').forEach(e => e.scrollTop = e.scrollHeight) })
await new Promise(r => setTimeout(r, 500))
await page.screenshot({ path: `${out}/review-verdict.png`, fullPage: false })

await page.setViewport({ width: 1440, height: 900 })
await page.goto('http://localhost:5173/?page=evals', { waitUntil: 'networkidle0' })
await wait(async () => page.evaluate(() => !!document.body.innerText.match(/Eval run|Runs|No runs yet|Pass rate/)))
await page.screenshot({ path: `${out}/evals-page.png`, fullPage: false })
console.log('evals')
// open first case
await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find(x => /PASS|FAIL/.test(x.innerText)); b?.click() })
await new Promise(r => setTimeout(r, 600))
await page.screenshot({ path: `${out}/evals-case.png`, fullPage: false })
await browser.close(); console.log('done')
