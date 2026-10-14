import puppeteer from 'puppeteer-core'
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'], defaultViewport: { width: 1600, height: 1000 } })
const p = await b.newPage()
await p.goto('http://localhost:5173/?task=f2b490df', { waitUntil: 'networkidle2' }).catch(() => {})
await p.waitForFunction(() => document.body.innerText.includes('Engine error'), { timeout: 15000 }); await new Promise(r => setTimeout(r, 800))
await p.screenshot({ path: '/workspace/dbt-factory/screenshots/sdk-no-credentials.png' })
await p.goto('http://localhost:5173/', { waitUntil: 'networkidle2' }); await new Promise(r => setTimeout(r, 800))
await p.select('select', 'sdk'); await new Promise(r => setTimeout(r, 300))
await p.screenshot({ path: '/workspace/dbt-factory/screenshots/empty-engine-selector.png' }); await b.close(); console.log('ok')
