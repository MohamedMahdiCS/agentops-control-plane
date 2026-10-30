// Capture the README screenshots from the running console.
//
// Prerequisites: API on :8000 backed by the seeded agentops_demo database
// (scripts/demo/seed_demo.py), the console on :5173, Google Chrome installed.
//
//   npm install --no-save puppeteer-core
//   AGENTOPS_OPERATOR_TOKEN=<token> node scripts/demo/capture_screenshots.mjs docs/assets/screenshots
//
// Afterwards build the GIF from <out>/frames with ffmpeg (see docs/assets/README.md).
import fs from 'node:fs'
import puppeteer from 'puppeteer-core'

const [outDir] = process.argv.slice(2)
const TOKEN = process.env.AGENTOPS_OPERATOR_TOKEN ?? ''
if (!outDir || !TOKEN) {
  console.error('Usage: AGENTOPS_OPERATOR_TOKEN=<token> node capture_screenshots.mjs <output-dir>')
  process.exit(2)
}
const runs = await fetch('http://localhost:8000/api/v1/evaluations?scenario_key=B01&verdict=passed&limit=100', {
  headers: { Authorization: `Bearer ${TOKEN}` },
}).then((r) => r.json())
const RUN_ID = runs.evaluations.at(-1).run_id
const BASE = 'http://localhost:5173/'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
  args: ['--use-angle=metal', '--enable-gpu', '--hide-scrollbars'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 })

async function view(name) {
  await page.evaluate((label) => {
    ;[...document.querySelectorAll('.nav-item')].find((b) => b.textContent.includes(label))?.click()
  }, name)
  await sleep(1800)
}

async function shot(file, clip) {
  await page.screenshot({ path: `${outDir}/${file}`, type: 'webp', quality: 90, ...(clip ? { clip } : {}) })
  console.log('captured', file)
}

await page.evaluateOnNewDocument(() => sessionStorage.setItem('agentops:active-view', 'overview'))
await page.goto(BASE, { waitUntil: 'networkidle0' })
await page.type('#overview-operator-token', TOKEN)
await page.keyboard.press('Enter')
await sleep(4000)
await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0) })
await sleep(800)
await shot('overview.webp')

// Animated constellation: frames of the 3D panel for a short GIF.
const panel = await page.$('.topology-panel')
const box = await panel.boundingBox()
fs.mkdirSync(`${outDir}/frames`, { recursive: true })
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 })
await sleep(800)
const panel1 = await (await page.$('.topology-panel')).boundingBox()
for (let i = 0; i < 48; i += 1) {
  await page.screenshot({ path: `${outDir}/frames/f${String(i).padStart(3, '0')}.png`, clip: panel1 })
  await sleep(70)
}
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 })
console.log('frames done', Math.round(box.width), Math.round(box.height))

// Evaluations: open the regression (failed B01) and compare with a passing B01.
await view('Evaluations')
await sleep(1500)
await page.evaluate(() => {
  const rows = [...document.querySelectorAll('.ev-table tbody tr')]
  const failed = rows.find((r) => r.textContent.includes('Failed') && r.textContent.includes('B01'))
  failed?.querySelector('.ev-row-button')?.click()
})
await sleep(1500)
await page.evaluate(() => {
  const select = document.getElementById('evaluation-compare')
  if (select && select.options.length > 1) {
    // The oldest passing evaluation is the baseline, so the failure reads as a regression.
    select.value = select.options[select.options.length - 1].value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  }
})
await sleep(1800)
await page.evaluate(() => { document.querySelector('.ev-detail')?.scrollIntoView({ block: 'start' }); window.scrollBy(0, -96) })
await sleep(600)
await shot('evaluation-regression.webp')
await page.evaluate(() => window.scrollTo(0, 0))
await sleep(400)
await shot('evaluations.webp')

// Benchmarks: the replay compared against its source benchmark.
await view('Benchmarks')
await sleep(1500)
await page.evaluate(() => {
  const select = document.getElementById('benchmark-baseline')
  if (select && select.options.length > 1) {
    select.value = select.options[1].value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  }
})
await sleep(1500)
await page.evaluate(() => { document.querySelector('.bm-detail')?.scrollIntoView({ block: 'start' }); window.scrollBy(0, -96) })
await sleep(600)
await shot('benchmarks.webp')

// Runs and traces: load a real run and open its trace timeline.
await view('Runs')
await page.type('input[placeholder="Enter an existing run UUID"]', RUN_ID)
await page.keyboard.press('Enter')
await sleep(2500)
await page.evaluate(() => { document.querySelector('.trace-explorer')?.scrollIntoView({ block: 'start' }); window.scrollBy(0, -96) })
await sleep(800)
await shot('traces.webp')

// Command palette over the overview.
await view('Overview')
await sleep(1500)
await page.keyboard.down('Meta')
await page.keyboard.press('KeyK')
await page.keyboard.up('Meta')
await page.keyboard.type('go to')
await sleep(700)
await shot('command-palette.webp')
await page.keyboard.press('Escape')

// Mobile overview.
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 3, isMobile: true, hasTouch: true })
await page.reload({ waitUntil: 'networkidle0' })
await sleep(1500)
const unlockInput = await page.$('#overview-operator-token')
if (unlockInput) {
  await unlockInput.type(TOKEN)
  await page.keyboard.press('Enter')
}
await sleep(3500)
await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0) })
await sleep(600)
await shot('mobile.webp')

await browser.close()
