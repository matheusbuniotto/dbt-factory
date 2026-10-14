import puppeteer from 'puppeteer-core'
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'], defaultViewport: { width: 1600, height: 1000, deviceScaleFactor: 1 } })
const p = await b.newPage(); const base = 'http://localhost:5173/'
const shot = async (url, file, wait) => { await p.goto(base + url, { waitUntil: 'networkidle2' }).catch(() => {}); if (wait) await p.waitForFunction(wait, { timeout: 15000 }); await new Promise(r => setTimeout(r, 900)); await p.screenshot({ path: `/workspace/dbt-factory/screenshots/${file}` }); console.log('ok', file) }
await shot('', 'empty.png', () => document.body.innerText.includes('Build a monthly revenue mart'))
await shot('?task=cb44f7fa', 'task-cb44f7fa.png', () => document.body.innerText.includes('revenue_per_customer') && document.body.innerText.includes('Added revenue_per_customer'))
await shot('?task=cb44f7fa&tab=changes', 'task-cb44f7fa-changes.png', () => document.body.innerText.includes('models/monthly_revenue.yml'))
await shot('?task=cb44f7fa&tab=sql', 'task-cb44f7fa-sql.png', () => document.body.innerText.includes('date_trunc'))
await b.close()
