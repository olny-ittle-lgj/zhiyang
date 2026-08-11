const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

const baseUrl = process.env.BASE_URL || 'http://127.0.0.1:5173'

async function run() {
  const output = process.env.SCREENSHOT_DIR || path.resolve(__dirname, '..', '.auth-checkshots')
  fs.mkdirSync(output, { recursive: true })

  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', error => errors.push(error.message))

  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('.login-card').waitFor()
  await page.waitForFunction(() => {
    const logo = document.querySelector('.login-mark img')
    return logo && logo.complete && logo.naturalWidth > 0
  })
  await page.waitForTimeout(250)

  const desktop = await page.evaluate(() => {
    const shell = document.querySelector('.login-shell')
    const card = document.querySelector('.login-card')
    const terminal = document.querySelector('.login-terminal')
    const rect = card?.getBoundingClientRect()
    return {
      overflow: document.documentElement.scrollWidth - innerWidth,
      footerPresent: Boolean(document.querySelector('.public-footer')),
      scenePresent: Boolean(document.querySelector('.login-scene')),
      terminalVisible: terminal && getComputedStyle(terminal).display !== 'none',
      cardWidth: Math.round(rect?.width || 0),
      background: getComputedStyle(shell).backgroundImage,
      choices: document.querySelectorAll('.login-choice-button').length,
    }
  })
  await page.screenshot({ path: path.join(output, 'login-desktop.png'), fullPage: true })

  await page.locator('.login-choice-button').first().click()
  await page.waitForURL(url => url.pathname === '/login/account')
  const account = await page.evaluate(() => ({
    footerPresent: Boolean(document.querySelector('.public-footer')),
    authForm: Boolean(document.querySelector('form.auth-card')),
    inputWrapBackground: getComputedStyle(document.querySelector('.input-wrap')).backgroundImage,
    inputBackground: getComputedStyle(document.querySelector('.input-wrap input')).backgroundColor,
    inputBorder: getComputedStyle(document.querySelector('.input-wrap')).borderColor,
  }))
  await page.screenshot({ path: path.join(output, 'account-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('.login-card').waitFor()
  await page.waitForTimeout(200)
  const mobile = await page.evaluate(() => {
    const card = document.querySelector('.login-card')
    const rect = card?.getBoundingClientRect()
    return {
      overflow: document.documentElement.scrollWidth - innerWidth,
      footerPresent: Boolean(document.querySelector('.public-footer')),
      cardWidth: Math.round(rect?.width || 0),
      viewportWidth: innerWidth,
      terminalHidden: getComputedStyle(document.querySelector('.login-terminal')).display === 'none',
    }
  })
  await page.screenshot({ path: path.join(output, 'login-mobile.png'), fullPage: true })

  await browser.close()

  const report = { errors, desktop, account, mobile }
  console.log(JSON.stringify(report, null, 2))
  const runtimeErrors = errors.filter(error => !error.includes('ERR_NETWORK_ACCESS_DENIED'))
  if (
    runtimeErrors.length ||
    desktop.overflow > 1 ||
    desktop.footerPresent ||
    !desktop.scenePresent ||
    !desktop.terminalVisible ||
    desktop.choices !== 2 ||
    !account.authForm ||
    account.footerPresent ||
    account.inputBackground !== 'rgba(0, 0, 0, 0)' ||
    account.inputWrapBackground === 'none' ||
    account.inputBorder === 'rgb(255, 255, 255)' ||
    mobile.overflow > 1 ||
    mobile.footerPresent ||
    mobile.cardWidth > mobile.viewportWidth ||
    !mobile.terminalHidden
  ) process.exitCode = 1
}

run().catch(error => {
  console.error(error)
  process.exit(1)
})
