const { chromium } = require('playwright')

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const page = await browser.newPage()
  await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' })
  const html = await page.evaluate(async () => {
    const { renderMarkdown } = await import('/src/markdown.js')
    const fence = String.fromCharCode(96).repeat(3)
    return renderMarkdown(`# 标题\n\n## 备份命令\n\n${fence}bash\ngit add -A\n${fence}\n\n- 一项`)
  })
  await browser.close()
  console.log(html)
  if (!html.includes('<h1>') || !html.includes('<h2>') || !html.includes('<pre><code class="language-bash">') || !html.includes('<ul>')) process.exit(1)
}

run().catch(error => { console.error(error); process.exit(1) })
