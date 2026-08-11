const { chromium } = require('playwright')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = path.join(__dirname, '..', '.screenshots')

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
  let previewRoute
  await page.route('**/api/materials/url/preview', async (route) => { previewRoute = route })

  await page.getByRole('button', { name: '链接抓取' }).click()
  await page.locator('input[type="url"]').fill('https://example.com/research/article')
  await page.getByRole('button', { name: '抓取并预览' }).click()
  await page.locator('.url-fetch-state').waitFor()
  await page.screenshot({ path: path.join(screenshots, `url-loading-${label}.png`) })

  if (!previewRoute) throw new Error('Preview request was not intercepted')
  await previewRoute.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      url: 'https://example.com/research/article',
      host: 'example.com',
      title: '知识工程中的可验证采集流程',
      content: '# 知识工程中的可验证采集流程\n\n网页采集需要将来源校验、正文提取、内容预览和确认入库连成完整流程。\n\n## 核心步骤\n\n- 校验公开网页地址\n- 提取并清洗正文\n- 在入库前完成人工确认\n\n预览内容应当保留标题、段落与来源信息。',
      size: 4380,
      characters: 1268,
      fetched_at: '2026-07-29T08:00:00+00:00',
    }),
  })

  await page.locator('.url-preview').waitFor()
  await page.screenshot({ path: path.join(screenshots, `url-preview-${label}.png`) })

  const result = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const preview = document.querySelector('.url-preview-body')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      previewHeight: preview.getBoundingClientRect().height,
      buttons: [...document.querySelectorAll('.url-actions button')].map((item) => item.textContent.trim()),
    }
  })
  await page.close()

  if (result.documentWidth > result.viewportWidth || result.modalLeft < 0 || result.modalRight > result.viewportWidth) {
    throw new Error(`${label} layout overflows: ${JSON.stringify(result)}`)
  }
  if (result.previewHeight < 200 || result.buttons.length !== 3) {
    throw new Error(`${label} preview is incomplete: ${JSON.stringify(result)}`)
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
