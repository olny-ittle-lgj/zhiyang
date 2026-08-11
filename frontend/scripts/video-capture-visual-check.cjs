const { chromium } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || path.join(__dirname, '..', '.screenshots')
const sampleVideo = path.join(__dirname, '..', '..', 'backend', 'data', 'uploads', '1e552b7e35f8421ea0815c7a792796f5.mp4')

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
  await page.route('**/api/materials/video/preview', async (route) => { previewRoute = route })

  await page.getByRole('button', { name: '视频导入' }).click()
  await page.locator('input[type="file"][accept*="video/mp4"]').setInputFiles({
    name: 'typescript-overview.mp4',
    mimeType: 'video/mp4',
    buffer: fs.readFileSync(sampleVideo),
  })
  await page.locator('.url-fetch-state').waitFor()
  await page.screenshot({ path: path.join(screenshots, `video-import-loading-${label}.png`) })

  if (!previewRoute) throw new Error('Video preview request was not intercepted')
  const content = 'TypeScript 是 JavaScript 的超集。\n静态类型检查可以提前发现错误。\n类型推断与接口约束有助于大型项目协作。'
  await previewRoute.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      filename: 'typescript-overview.mp4',
      width: 1240,
      height: 852,
      duration: 7.29,
      size: 2224806,
      content,
      characters: content.length,
      subtitle_lines: 0,
      keyframes: 3,
      confidence: 0.987,
      analyzed_at: '2026-07-29T08:00:00+00:00',
    }),
  })

  await page.locator('.video-preview').waitFor()
  await page.screenshot({ path: path.join(screenshots, `video-import-preview-${label}.png`) })
  const result = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const video = document.querySelector('.video-text-layout video')
    const textarea = document.querySelector('.video-text-layout textarea')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      videoWidth: video.getBoundingClientRect().width,
      textareaHeight: textarea.getBoundingClientRect().height,
      buttons: [...document.querySelectorAll('.video-preview .url-actions button')].map((item) => item.textContent.trim()),
    }
  })
  await page.close()

  if (result.documentWidth > result.viewportWidth || result.modalLeft < 0 || result.modalRight > result.viewportWidth) {
    throw new Error(`${label} layout overflows: ${JSON.stringify(result)}`)
  }
  if (result.videoWidth < 100 || result.textareaHeight < 180 || result.buttons.length !== 3) {
    throw new Error(`${label} video preview is incomplete: ${JSON.stringify(result)}`)
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
