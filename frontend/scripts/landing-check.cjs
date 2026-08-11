const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

const baseUrl = process.env.BASE_URL || 'http://127.0.0.1:5173'

async function run() {
  const output = process.env.SCREENSHOT_DIR || path.resolve(__dirname, '..', '.landing-checkshots')
  fs.mkdirSync(output, { recursive: true })

  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', error => errors.push(error.message))

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.locator('h1').waitFor()
  await page.waitForFunction(() => {
    const frame = document.querySelector('.hero-frame')
    return frame && frame.complete && frame.naturalWidth > 0
  }, null, { timeout: 30000 })
  await page.waitForTimeout(300)

  const desktopBefore = await page.locator('.hero-frame').evaluate(frame => ({
    frame: frame.currentSrc,
    width: frame.naturalWidth,
    height: frame.naturalHeight,
  }))
  await page.mouse.move(120, 300)
  await page.waitForTimeout(50)
  const frameSwitchPromise = page.evaluate(before => new Promise(resolve => {
    const frame = document.querySelector('.hero-frame')
    const startedAt = performance.now()
    const timeout = setTimeout(() => resolve(null), 1000)
    const check = () => {
      if (frame.currentSrc !== before) {
        clearTimeout(timeout)
        resolve(Number((performance.now() - startedAt).toFixed(1)))
        return
      }
      requestAnimationFrame(check)
    }
    check()
  }), desktopBefore.frame)
  await page.mouse.move(1120, 300)
  const frameSwitchLatencyMs = await frameSwitchPromise
  await page.waitForTimeout(100)
  const desktopAfter = await page.locator('.hero-frame').evaluate(frame => frame.currentSrc)

  await page.waitForTimeout(350)
  const desktop = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - innerWidth,
    headline: document.querySelector('h1')?.textContent,
    headlineSize: getComputedStyle(document.querySelector('h1')).fontSize,
    navRemoved: !document.querySelector('.desktop-nav, .menu-button, .mobile-nav-overlay'),
    startButton: document.querySelector('.start-button')?.textContent.trim(),
    servicePills: document.querySelectorAll('.service-pill').length,
    glowRemoved: !document.querySelector('.gaze-response, .gaze-field'),
  }))
  await page.screenshot({ path: path.join(output, 'landing-mainframe-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.locator('h1').waitFor()
  await page.waitForFunction(() => {
    const frame = document.querySelector('.hero-frame')
    return frame && frame.complete && frame.naturalWidth > 0
  }, null, { timeout: 30000 })
  const mobileFrameBefore = await page.locator('.hero-frame').evaluate(frame => frame.currentSrc)
  await page.waitForTimeout(250)
  const mobileFrameAfter = await page.locator('.hero-frame').evaluate(frame => frame.currentSrc)
  const mobile = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - innerWidth,
    navRemoved: !document.querySelector('.desktop-nav, .menu-button, .mobile-nav-overlay'),
  }))
  await page.screenshot({ path: path.join(output, 'landing-mainframe-mobile.png'), fullPage: true })

  await browser.close()

  const report = { errors, desktop, desktopBefore, desktopAfter, frameSwitchLatencyMs, mobile, mobileFrameBefore, mobileFrameAfter }
  console.log(JSON.stringify(report, null, 2))
  const runtimeErrors = errors.filter(error => !error.includes('ERR_NETWORK_ACCESS_DENIED'))
  if (
    runtimeErrors.length ||
    desktop.overflow > 1 ||
    mobile.overflow > 1 ||
    desktopAfter === desktopBefore.frame ||
    frameSwitchLatencyMs === null ||
    !desktop.glowRemoved ||
    !desktop.navRemoved ||
    desktop.startButton !== '开始使用' ||
    desktop.servicePills !== 0 ||
    !mobile.navRemoved ||
    mobileFrameBefore === mobileFrameAfter
  ) process.exitCode = 1
}

run().catch(error => {
  console.error(error)
  process.exit(1)
})
