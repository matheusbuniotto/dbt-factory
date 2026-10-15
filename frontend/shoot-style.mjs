import puppeteer from 'puppeteer-core'
const tid = process.env.TID,
  out = '../screenshots'
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage()
await p.setViewport({ width: 1440, height: 1300 })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
await p.goto(`http://localhost:5173/?task=${tid}&tab=review`, { waitUntil: 'domcontentloaded' })
await p.waitForFunction(() => document.body.innerText.includes('Review this change') && document.body.innerText.includes('jaffle_shop'), {
  timeout: 180000,
})
await sleep(800)
await p.screenshot({ path: `${out}/style-review-inline.png` })
await p.setViewport({ width: 1440, height: 900 })
await p.goto(`http://localhost:5173/?task=${tid}&tab=gates`, { waitUntil: 'domcontentloaded' })
await p.waitForFunction(() => document.body.innerText.includes('Team SQL style'))
await sleep(500)
await p.screenshot({ path: `${out}/style-gate.png` })
await p.evaluate(() => [...document.querySelectorAll('button')].find((x) => /skills? ·/.test(x.innerText))?.click())
await sleep(600)
await p.screenshot({ path: `${out}/style-capabilities.png` })
await p.goto(`http://localhost:5173/?task=${tid}&settings=1`, { waitUntil: 'domcontentloaded' })
await p.waitForFunction(
  () =>
    document.body.innerText.includes('Settings · SQL style') &&
    document.body.innerText.includes('Active:') &&
    document.body.innerText.includes('gh connected') &&
    !document.body.innerText.includes('Active: …'),
)
await sleep(800)
await p.screenshot({ path: `${out}/style-settings.png` })
await b.close()
console.log('ok')
