const { chromium } = require('playwright')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = path.join(__dirname, '..', '.screenshots')
const sampleImage = path.join(screenshots, 'url-preview-desktop.png')

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
  await page.route('**/api/materials/image/preview', async (route) => { previewRoute = route })

  await page.getByRole('button', { name: '图片识别' }).click()
  await page.locator('input[type="file"][accept*="image/png"]').setInputFiles(sampleImage)
  await page.locator('.url-fetch-state').waitFor()
  await page.screenshot({ path: path.join(screenshots, `image-ocr-loading-${label}.png`) })

  if (!previewRoute) throw new Error('OCR preview request was not intercepted')
  await previewRoute.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      filename: 'knowledge-workflow.png',
      width: 1440,
      height: 900,
      format: 'PNG',
      size: 98642,
      content: '知识工程中的可验证采集流程\n网页采集需要将来源校验、正文提取、内容预览和确认入库连成完整流程。\n核心步骤\n校验公开网页地址\n提取并清洗正文\n在入库前完成人工确认',
      lines: 6,
      confidence: 0.9632,
      characters: 92,
      recognized_at: '2026-07-29T08:00:00+00:00',
    }),
  })

  await page.locator('.image-preview').waitFor()
  await page.screenshot({ path: path.join(screenshots, `image-ocr-preview-${label}.png`) })
  const result = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const image = document.querySelector('.image-ocr-layout img')
    const textarea = document.querySelector('.image-ocr-layout textarea')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      imageWidth: image.getBoundingClientRect().width,
      textareaHeight: textarea.getBoundingClientRect().height,
      buttons: [...document.querySelectorAll('.image-preview .url-actions button')].map((item) => item.textContent.trim()),
    }
  })
  await page.close()

  if (result.documentWidth > result.viewportWidth || result.modalLeft < 0 || result.modalRight > result.viewportWidth) {
    throw new Error(`${label} layout overflows: ${JSON.stringify(result)}`)
  }
  if (result.imageWidth < 100 || result.textareaHeight < 180 || result.buttons.length !== 3) {
    throw new Error(`${label} OCR preview is incomplete: ${JSON.stringify(result)}`)
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
