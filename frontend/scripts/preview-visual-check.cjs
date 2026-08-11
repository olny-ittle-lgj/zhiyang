const { chromium } = require('playwright')
const path = require('node:path')

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /账户密码登录注册/ }).click()
  await page.getByPlaceholder('name@example.com').fill('demo@zhiyan.ai')
  await page.getByPlaceholder('输入密码').fill('demo123456')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard')
  await page.goto('http://127.0.0.1:5173/materials', { waitUntil: 'networkidle' })
  await page.getByTitle('预览').first().click()
  await page.locator('.preview-content p').waitFor()
  const color = await page.locator('.preview-content p').evaluate(element => getComputedStyle(element).color)
  await page.screenshot({ path: path.join(__dirname, '..', '.screenshots', 'material-preview.png'), fullPage: true })
  await browser.close()
  console.log(JSON.stringify({ color }))
  if (color !== 'rgb(24, 48, 66)') process.exitCode = 1
}

run().catch(error => { console.error(error); process.exit(1) })
