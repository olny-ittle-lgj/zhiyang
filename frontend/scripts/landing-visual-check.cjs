const { chromium } = require('playwright')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

async function run() {
  const output = path.join(os.tmpdir(), 'zhiyan-landing-visual-check')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().includes('ERR_NETWORK_ACCESS_DENIED')) errors.push(message.text())
  })
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1600)
  if (!await page.locator('.landing-hero h1').count()) {
    console.log(JSON.stringify({ url: page.url(), title: await page.title(), body: (await page.locator('body').innerText()).slice(0, 800), errors }, null, 2))
    throw new Error('Landing hero did not render')
  }
  await page.waitForTimeout(2200)
  await page.evaluate(() => {
    const video = document.querySelector('.landing-video')
    window.__landingSeekMetrics = []
    window.__landingLongTasks = []
    let seekStartedAt = 0
    video.addEventListener('seeking', () => { seekStartedAt = performance.now() })
    video.addEventListener('seeked', () => {
      if (seekStartedAt) window.__landingSeekMetrics.push(performance.now() - seekStartedAt)
    })
    if ('PerformanceObserver' in window) {
      const observer = new PerformanceObserver(list => {
        for (const entry of list.getEntries()) window.__landingLongTasks.push(entry.duration)
      })
      observer.observe({ type: 'longtask', buffered: true })
    }
  })
  const before = await page.locator('.landing-video').evaluate(element => ({
    readyState: element.readyState,
    currentTime: element.currentTime,
    duration: element.duration,
    videoWidth: element.videoWidth,
    videoHeight: element.videoHeight,
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
  }))
  for (let index = 0; index < 80; index += 1) {
    const progress = index % 40 / 39
    const x = index < 40 ? 100 + progress * 1240 : 1340 - progress * 1240
    await page.mouse.move(x, 420)
    await page.waitForTimeout(16)
  }
  await page.waitForTimeout(900)
  const interaction = await page.evaluate(() => ({
    afterTime: document.querySelector('.landing-video').currentTime,
    seekMetrics: window.__landingSeekMetrics,
    longTasks: window.__landingLongTasks,
  }))
  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'landing-mainframe-desktop.png') })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.locator('.landing-hero h1').waitFor()
  await page.waitForTimeout(1200)
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'landing-mainframe-mobile.png') })
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.locator('.landing-mobile-menu.open').waitFor()
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(output, 'landing-mainframe-mobile-menu.png') })

  await browser.close()
  const sortedSeekMetrics = [...interaction.seekMetrics].sort((a, b) => a - b)
  const seekSummary = {
    samples: sortedSeekMetrics.length,
    average: sortedSeekMetrics.length ? sortedSeekMetrics.reduce((sum, value) => sum + value, 0) / sortedSeekMetrics.length : 0,
    p95: sortedSeekMetrics[Math.max(0, Math.ceil(sortedSeekMetrics.length * .95) - 1)] || 0,
    max: sortedSeekMetrics.at(-1) || 0,
  }
  const result = { errors, before, afterTime: interaction.afterTime, seekSummary, longTasks: interaction.longTasks, desktopOverflow, mobileOverflow }
  console.log(JSON.stringify(result, null, 2))
  if (errors.length || desktopOverflow > 1 || mobileOverflow > 1 || before.readyState < 1 || interaction.afterTime === before.currentTime || before.width < 300 || before.height < 500 || seekSummary.p95 > 30) process.exitCode = 1
}

run().catch(error => { console.error(error); process.exit(1) })
