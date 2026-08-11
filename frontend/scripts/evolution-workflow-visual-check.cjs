const { chromium } = require('playwright')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || path.join(__dirname, '..', '.screenshots')

const materials = [
  { id: 301, name: 'RAGFlow 多路召回笔记.md', kind: 'Markdown', size: 18420, status: 'ready', category: 'RAG', content: 'RAGFlow 通过向量、全文与图谱三路召回融合提升知识检索覆盖率。', created_at: '2026-07-29T08:00:00+00:00' },
  { id: 302, name: '神经网络优化指南.pdf', kind: 'PDF', size: 4404019, status: 'ready', category: '人工智能', content: '反向传播通过梯度下降优化神经网络参数。学习率与正则化决定模型的泛化能力。', created_at: '2026-07-29T08:00:00+00:00' },
  { id: 303, name: '量子力学入门', kind: '网页', size: 8640, status: 'ready', category: '物理', content: '量子纠缠描述多个粒子之间无法由经典局域变量解释的关联。', created_at: '2026-07-29T08:00:00+00:00' },
]

const reviews = [
  {
    id: 701, task_id: 91, material_id: 301, material_name: materials[0].name, material_kind: materials[0].kind,
    material_category: materials[0].category, title: `进化：${materials[0].name}`,
    original_text: materials[0].content,
    proposed_text: '# RAGFlow 多路召回\n\nRAGFlow 将向量检索、全文检索与知识图谱检索进行融合排序，以提升知识检索的覆盖率与相关性。\n\n## 核心要点\n\n- 多路召回覆盖不同匹配方式\n- 融合排序统一评估候选结果',
    reason: 'AI 编辑代理完成了事实约束下的纠错、结构优化和上下文补充。', decision: 'pending',
  },
  {
    id: 702, task_id: 91, material_id: 302, material_name: materials[1].name, material_kind: materials[1].kind,
    material_category: materials[1].category, title: `进化：${materials[1].name}`,
    original_text: materials[1].content,
    proposed_text: '# 神经网络优化指南\n\n反向传播计算损失函数相对于模型参数的梯度，优化器据此更新参数。\n\n## 核心要点\n\n- 学习率影响收敛速度\n- 正则化改善泛化能力',
    reason: '已统一概念表达，并将关键结论整理为结构化知识。', decision: 'pending',
  },
]

function baseOverview() {
  return {
    latest: { id: 90, mode: 'auto', status: 'completed', progress: 100, review_count: 1, accepted_count: 1, rejected_count: 0, summary: '最近任务已完成。', created_at: '2026-07-29T07:00:00+00:00' },
    pending: [], materials, latest_reviews: [],
    timeline: [
      { agent: '审计代理', time: '09:10:08', text: '已读取并校验指定素材的知识内容。', tone: 'blue' },
      { agent: '编辑代理', time: '09:10:16', text: '已生成结构化进化建议。', tone: 'mint' },
      { agent: '拓展代理', time: '09:10:24', text: '已完成语义一致性检查和上下文整理。', tone: 'cyan' },
      { agent: '系统核心', time: '09:10:32', text: '进化结果已写回素材并保留版本记录。', tone: 'cyan' },
    ],
  }
}

async function checkViewport(browser, viewport, label) {
  const page = await browser.newPage({ viewport })
  const login = await page.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: 'demo@zhiyan.ai', password: 'demo123456' },
  })
  if (!login.ok()) throw new Error(`Login failed: ${login.status()}`)
  const { access_token: token } = await login.json()
  await page.goto(baseUrl)
  await page.evaluate((value) => localStorage.setItem('zhiyan_token', value), token)

  let overview = baseOverview()
  let startRoute
  await page.route('**/api/evolution', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) })
  })
  await page.route('**/api/evolution/start', async (route) => { startRoute = route })
  await page.route('**/api/evolution/reviews/**', async (route) => {
    const parts = route.request().url().split('/')
    const isRollback = parts.at(-1) === 'rollback'
    const reviewId = Number(parts.at(isRollback ? -2 : -1))
    if (isRollback) {
      const current = overview.latest_reviews.find((item) => item.id === reviewId)
      current.decision = 'rolled_back'
      current.version += 1
      overview.latest = { ...overview.latest, accepted_count: 0, rolled_back_count: 1 }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
      return
    }
    const body = route.request().postDataJSON()
    const current = reviews.find((item) => item.id === reviewId)
    current.decision = body.decision
    overview.pending = overview.pending.filter((item) => item.id !== reviewId)
    if (!overview.pending.length) {
      overview.latest = { ...overview.latest, status: 'completed', progress: 100, accepted_count: 1, rejected_count: 1, summary: '已对 2 个指定素材完成审计并生成进化建议。' }
      overview.latest_reviews = reviews.map((item) => ({ id: item.id, material_id: item.material_id, material_name: item.material_name, decision: item.decision }))
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
  })

  await page.goto(`${baseUrl}/evolution`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '选择文件并进化' }).click()
  await page.locator('.evolution-material-list input').nth(0).check()
  await page.locator('.evolution-material-list input').nth(1).check()
  await page.screenshot({ path: path.join(screenshots, `evolution-select-${label}.png`) })

  await page.getByRole('button', { name: '生成进化建议' }).click()
  await page.locator('.url-fetch-state').waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-running-${label}.png`) })
  if (!startRoute) throw new Error('Evolution start request was not intercepted')
  overview = {
    ...overview,
    latest: { id: 91, mode: 'manual', status: 'review', progress: 70, review_count: 2, accepted_count: 0, rejected_count: 0, summary: '已对 2 个指定素材完成审计并生成进化建议。', created_at: '2026-07-29T09:10:00+00:00' },
    pending: reviews.map((item) => ({ ...item })),
    latest_reviews: reviews.map((item) => ({ id: item.id, material_id: item.material_id, material_name: item.material_name, decision: 'pending' })),
  }
  await startRoute.fulfill({
    status: 201, contentType: 'application/json',
    body: JSON.stringify({ task_id: 91, status: 'review', reviews }),
  })

  await page.locator('.evolution-diff-grid').waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-review-${label}.png`) })
  await page.getByRole('button', { name: '确认应用' }).click()
  await page.getByRole('heading', { name: materials[1].name }).waitFor()
  await page.getByRole('button', { name: '拒绝并保留原文' }).click()
  await page.getByRole('heading', { name: '知识进化已完成' }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-result-${label}.png`) })

  const result = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      resultRows: document.querySelectorAll('.evolution-result li').length,
      resultTitle: document.querySelector('.modal header h2')?.textContent.trim(),
    }
  })
  if (result.documentWidth > result.viewportWidth || result.modalLeft < 0 || result.modalRight > result.viewportWidth) {
    throw new Error(`${label} layout overflows: ${JSON.stringify(result)}`)
  }
  if (result.resultTitle !== '知识进化已完成' || result.resultRows !== 2) {
    throw new Error(`${label} workflow is incomplete: ${JSON.stringify(result)}`)
  }

  await page.locator('.evolution-result .url-actions .button.ghost').click()
  await page.getByRole('button', { name: '自动模式' }).click()
  await page.getByRole('heading', { name: '启用自动模式' }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-auto-confirm-${label}.png`) })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  if (!await page.getByRole('button', { name: '手动模式' }).evaluate((button) => button.classList.contains('active'))) {
    throw new Error(`${label} cancelling auto mode changed the selected mode`)
  }
  await page.getByRole('button', { name: '自动模式' }).click()
  await page.getByRole('button', { name: '确认启用自动模式' }).click()
  await page.getByRole('button', { name: '选择文件并进化' }).click()
  await page.locator('.evolution-material-list input').first().check()
  await page.screenshot({ path: path.join(screenshots, `evolution-auto-select-${label}.png`) })

  startRoute = null
  await page.getByRole('button', { name: '确认并自动应用' }).click()
  await page.locator('.url-fetch-state').waitFor()
  if (!startRoute) throw new Error('Auto evolution start request was not intercepted')
  const autoReview = {
    ...reviews[0], id: 801, task_id: 92, decision: 'accepted', version: 2,
    original_chars: reviews[0].original_text.length, proposed_chars: reviews[0].proposed_text.length,
  }
  const autoTask = {
    id: 92, mode: 'auto', status: 'completed', progress: 100, review_count: 1,
    accepted_count: 1, rejected_count: 0, rolled_back_count: 0,
    summary: '自动进化已完成：1 个素材已写回知识库并保存版本。', created_at: '2026-07-29T10:00:00+00:00',
  }
  overview = { ...overview, latest: autoTask, pending: [], latest_reviews: [autoReview] }
  await startRoute.fulfill({
    status: 201, contentType: 'application/json',
    body: JSON.stringify({ task_id: 92, status: 'completed', task: autoTask, reviews: [autoReview] }),
  })
  await page.getByRole('heading', { name: '自动进化已完成' }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-auto-result-${label}.png`) })
  await page.getByRole('button', { name: '撤销' }).click()
  await page.getByRole('button', { name: '确认撤销' }).click()
  await page.getByText('已撤销', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-auto-rollback-${label}.png`) })

  const autoResult = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    const rect = modal.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      modalLeft: rect.left,
      modalRight: rect.right,
      resultRows: document.querySelectorAll('.evolution-result li').length,
      rolledBack: document.querySelector('.evolution-result li b')?.textContent.trim(),
    }
  })
  await page.locator('.evolution-result .url-actions .button.ghost').click()
  await page.getByRole('button', { name: '手动模式' }).click()
  await page.getByRole('heading', { name: '切换至手动模式' }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `evolution-manual-confirm-${label}.png`) })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  if (!await page.getByRole('button', { name: '自动模式' }).evaluate((button) => button.classList.contains('active'))) {
    throw new Error(`${label} cancelling manual mode changed the selected mode`)
  }
  await page.getByRole('button', { name: '手动模式' }).click()
  await page.getByRole('button', { name: '确认切换至手动模式' }).click()
  if (!await page.getByRole('button', { name: '手动模式' }).evaluate((button) => button.classList.contains('active'))) {
    throw new Error(`${label} manual mode confirmation did not change the selected mode`)
  }
  autoResult.manualModeConfirmed = true
  await page.close()
  if (autoResult.documentWidth > autoResult.viewportWidth || autoResult.modalLeft < 0 || autoResult.modalRight > autoResult.viewportWidth) {
    throw new Error(`${label} auto layout overflows: ${JSON.stringify(autoResult)}`)
  }
  if (autoResult.resultRows !== 1 || autoResult.rolledBack !== '已撤销') {
    throw new Error(`${label} auto workflow is incomplete: ${JSON.stringify(autoResult)}`)
  }
  return { manual: result, auto: autoResult }
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
