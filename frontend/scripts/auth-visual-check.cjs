const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

async function run() {
  const output = path.resolve(__dirname, '..', '.screenshots', 'auth')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 })
  const errors = []
  const overflow = {}
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', error => errors.push(error.message))

  await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /账户密码登录注册/ }).waitFor()
  await page.getByRole('button', { name: /手机号登录注册/ }).waitFor()
  overflow.choiceDesktop = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'choice-desktop.png'), fullPage: true })

  await page.getByRole('button', { name: /账户密码登录注册/ }).click()
  await page.waitForURL('**/login/account')
  await page.getByRole('tab', { name: '账号注册' }).click()
  await page.getByPlaceholder('输入您的昵称').waitFor()
  overflow.accountDesktop = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'account-register-desktop.png'), fullPage: true })

  await page.getByRole('tab', { name: '账号登录' }).click()
  await page.getByPlaceholder('name@example.com').fill('demo@zhiyan.ai')
  await page.getByPlaceholder('输入密码').fill('demo123456')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard')
  await page.locator('.stats-grid').waitFor()
  await page.evaluate(() => localStorage.removeItem('zhiyan_token'))

  await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /手机号登录注册/ }).click()
  await page.waitForURL('**/login/phone')
  await page.getByPlaceholder('输入 11 位手机号').waitFor()
  overflow.phoneDesktop = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  await page.screenshot({ path: path.join(output, 'phone-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  for (const [name, route] of [['choiceMobile', 'login'], ['accountMobile', 'login/account'], ['phoneMobile', 'login/phone']]) {
    await page.goto(`http://127.0.0.1:5173/${route}`, { waitUntil: 'networkidle' })
    overflow[name] = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
  }

  await browser.close()
  console.log(JSON.stringify({ errors, overflow }, null, 2))
  if (errors.length || Object.values(overflow).some(value => value > 1)) process.exitCode = 1
}

run().catch(error => { console.error(error); process.exit(1) })
