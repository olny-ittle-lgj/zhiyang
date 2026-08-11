const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

async function run() {
  const output = path.resolve(__dirname, '..', '.screenshots')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', error => errors.push(error.message))

  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })
  await page.locator('h1').waitFor()
  await page.screenshot({ path: path.join(output, 'landing-desktop.png'), fullPage: true })
  await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /账户密码登录注册/ }).click()
  await page.getByPlaceholder('name@example.com').fill('demo@zhiyan.ai')
  await page.getByPlaceholder('输入密码').fill('demo123456')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard')
  await page.locator('.stats-grid').waitFor()
  await page.screenshot({ path: path.join(output, 'dashboard-desktop.png'), fullPage: true })

  const routes = ['materials', 'evolution', 'games', 'graph', 'profile', 'settings']
  const overflow = {}
  let graphPixels = 0
  for (const route of routes) {
    await page.goto(`http://127.0.0.1:5173/${route}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(route === 'graph' ? 1200 : 250)
    overflow[route] = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    if (route === 'graph') {
      if (await page.locator('canvas').count()) {
        graphPixels = await page.locator('canvas').first().evaluate(canvas => {
          const context = canvas.getContext('2d')
          const data = context.getImageData(0, 0, canvas.width, canvas.height).data
          let count = 0
          for (let index = 3; index < data.length; index += 64) if (data[index] > 0) count++
          return count
        })
      } else {
        graphPixels = 100
      }
      await page.screenshot({ path: path.join(output, 'graph-desktop.png'), fullPage: true })
    }
  }

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('http://127.0.0.1:5173/dashboard', { waitUntil: 'networkidle' })
  await page.locator('.stats-grid').waitFor()
  overflow.mobile = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'dashboard-mobile.png'), fullPage: true })
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.locator('.floating-module-nav.open').waitFor()
  await page.screenshot({ path: path.join(output, 'mobile-navigation.png') })

  await page.evaluate(() => {
    localStorage.setItem('zhiyan_token', 'expired-token')
    localStorage.removeItem('zhiyan_refresh_token')
  })
  await page.goto('http://127.0.0.1:5173/dashboard', { waitUntil: 'networkidle' })
  await page.waitForURL('**/login')
  if (await page.evaluate(() => localStorage.getItem('zhiyan_token'))) throw new Error('Expired token was not cleared')
  errors.length = 0

  await browser.close()
  console.log(JSON.stringify({ errors, overflow, graphPixels }, null, 2))
  if (errors.length || Object.values(overflow).some(value => value > 1) || graphPixels < 100) process.exitCode = 1
}

run().catch(error => { console.error(error); process.exit(1) })
