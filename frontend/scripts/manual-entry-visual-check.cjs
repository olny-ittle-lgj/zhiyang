const { chromium } = require('playwright')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || path.join(__dirname, '..', '.screenshots')
const title = '向量检索实践笔记'
const category = '知识工程'
const content = '# 向量检索实践\n\n向量检索用于寻找语义相近的知识片段。\n\n- 统一嵌入模型\n- 校验召回质量\n- 记录索引版本'

async function openAuthenticatedPage(browser, viewport) {
  const page = await browser.newPage({ viewport })
  const login = await page.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: 'demo@zhiyan.ai', password: 'demo123456' },
  })
  if (!login.ok()) throw new Error(`Login failed: ${login.status()}`)
  const { access_token: token } = await login.json()
  await page.goto(baseUrl)
  await page.evaluate((value) => localStorage.setItem('zhiyan_token', value), token)
  await page.goto(`${baseUrl}/materials`, { waitUntil: 'networkidle' })
  return page
}

async function checkViewport(browser, viewport, label) {
  const page = await openAuthenticatedPage(browser, viewport)
  let saveRoute
  await page.route('**/api/materials/text', async (route) => { saveRoute = route })

  await page.getByRole('button', { name: '手动输入' }).click()
  await page.getByLabel('素材名称').fill(title)
  await page.getByLabel('分类', { exact: true }).fill(category)
  await page.getByLabel('知识内容').fill(content)
  await page.screenshot({ path: path.join(screenshots, `manual-entry-form-${label}.png`) })

  await page.getByRole('button', { name: '保存并入库' }).click()
  await page.locator('.url-fetch-state').waitFor()
  await page.screenshot({ path: path.join(screenshots, `manual-entry-saving-${label}.png`) })
  if (!saveRoute) throw new Error('Manual material request was not intercepted')

  await saveRoute.fulfill({
    status: 201,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 98765,
      name: title,
      source: 'manual',
      kind: '文本',
      size: Buffer.byteLength(content),
      status: 'ready',
      category,
      content,
      file_path: null,
      origin_url: null,
      created_at: '2026-07-29T09:00:00+00:00',
    }),
  })

  await page.locator('.material-detail-preview').waitFor()
  await page.screenshot({ path: path.join(screenshots, `manual-entry-saved-${label}.png`) })
  const result = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      detailTitle: document.querySelector('.modal header h2')?.textContent.trim(),
      headings: document.querySelectorAll('.material-detail-preview h1, .material-detail-preview h2').length,
      listItems: document.querySelectorAll('.material-detail-preview li').length,
    }
  })
  await page.close()

  if (result.documentWidth > result.viewportWidth || result.modalLeft < 0 || result.modalRight > result.viewportWidth) {
    throw new Error(`${label} layout overflows: ${JSON.stringify(result)}`)
  }
  if (result.detailTitle !== title || result.headings !== 1 || result.listItems !== 3) {
    throw new Error(`${label} saved preview is incomplete: ${JSON.stringify(result)}`)
  }
  return result
}

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  try {
    const desktop = await checkViewport(browser, { width: 1440, height: 900 }, 'desktop')
    const mobile = await checkViewport(browser, { width: 390, height: 844 }, 'mobile')
    console.log(JSON.stringify({ desktop, mobile }))
  } finally {
    await browser.close()
  }
}

run().catch((error) => { console.error(error); process.exit(1) })
