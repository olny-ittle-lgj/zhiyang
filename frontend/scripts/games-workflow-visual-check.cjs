const { chromium } = require('playwright')
const path = require('node:path')

const baseUrl = process.env.APP_BASE_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || path.join(__dirname, '..', '.screenshots')

const material = {
  id: 501, name: '向量检索学习笔记.md', kind: 'Markdown', category: '人工智能', size: 2048,
  content: '向量检索用于寻找语义相似内容。嵌入模型将文本转换为向量。混合检索结合关键词与语义匹配。',
}

const overview = {
  level: 3, xp: 1180, next_level_xp: 1500, coins: 4280, props: 7, rank: 1, total_players: 1,
  settings: { gamified_review: true, flashcard_difficulty: 'easy', monopoly_difficulty: 'easy', matching_difficulty: 'hard' },
  best: [], leaderboard: [{ nickname: 'Alex Chen', score: 4280 }], recent_packs: [], materials: [material],
  games: [
    { id: 'flashcard', title: '知识点卡片对对碰', description: '由 Agent 提取所选文件的知识点，通过翻牌完成记忆配对。', difficulty: 'easy' },
    { id: 'monopoly', title: '知识大富翁', description: '2-4 名玩家轮流掷骰、问答、购买地产并争夺最终胜利。' },
    { id: 'matching', title: '概念配对 V2.0', description: '匹配概念与定义之间的语义关系。' },
  ],
}

const points = [
  { term: '向量检索', definition: '向量检索用于寻找语义相似内容。', fact: '向量检索关注语义相似性。' },
  { term: '嵌入模型', definition: '嵌入模型将文本转换为向量。', fact: '嵌入模型负责生成向量表示。' },
  { term: '混合检索', definition: '混合检索结合关键词与语义匹配。', fact: '混合检索融合两种匹配方式。' },
]
const memoryPoints = Array.from({ length: 18 }, (_, index) => ({
  term: index < points.length ? points[index].term : `检索知识点 ${index + 1}`,
  definition: index < points.length ? points[index].definition : `这是从素材提取的第 ${index + 1} 个检索知识定义。`,
  fact: index < points.length ? points[index].fact : `素材支持第 ${index + 1} 个知识点。`,
  source_material_id: material.id,
  source_name: material.name,
}))

let questionId = 900
function makePack(game) {
  const packPoints = game === 'flashcard' ? memoryPoints : points
  const questions = packPoints.map((point, index) => {
    const answer = game === 'matching' ? point.term : point.definition
    const wrong = game === 'matching'
      ? points.filter((item) => item.term !== point.term).map((item) => item.term)
      : points.filter((item) => item.definition !== point.definition).map((item) => item.definition)
    return {
      id: ++questionId, game, difficulty: 'easy',
      prompt: game === 'matching' ? point.definition : `关于“${point.term}”，以下哪项最符合素材中的知识？`,
      options: [answer, ...wrong, '素材未说明该关系。'], topic: game === 'matching' ? '概念配对' : point.term,
      question_type: game === 'matching' ? 'concept-definition' : 'multiple-choice', sequence: index + 1,
      _answer: answer, _explanation: point.fact,
    }
  })
  return {
    id: 700 + questionId, game, difficulty: 'easy', title: `${overview.games.find((item) => item.id === game).title} · ${material.name}`,
    material_ids: [material.id], knowledge_points: packPoints, source_mode: 'local-agent',
    agent_note: '本地 Agent 已从所选素材提取并校验核心知识点。',
    questions: questions.map(({ _answer, _explanation, ...question }) => question),
    terms: game === 'matching' ? ['混合检索', '向量检索', '嵌入模型'] : undefined,
    _answers: Object.fromEntries(questions.map((question) => [question.id, { answer: question._answer, explanation: question._explanation }])),
  }
}

async function runViewport(browser, viewport, label) {
  const page = await browser.newPage({ viewport })
  const login = await page.request.post(`${baseUrl}/api/auth/login`, { data: { username: 'demo@zhiyan.ai', password: 'demo123456' } })
  if (!login.ok()) throw new Error(`Login failed: ${login.status()}`)
  const { access_token: token } = await login.json()
  await page.goto(baseUrl)
  await page.evaluate((value) => localStorage.setItem('zhiyan_token', value), token)

  const packs = {}
  await page.route('**/api/games', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) }))
  await page.route('**/api/games/generate', async (route) => {
    const body = route.request().postDataJSON()
    const pack = makePack(body.game)
    packs[body.game] = pack
    const { _answers, ...publicPack } = pack
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(publicPack) })
  })
  await page.route('**/api/games/matching/round', async (route) => {
    const pack = packs.matching
    const pair = [pack.knowledge_points[0], pack.knowledge_points[1]].map((point) => ({
      ...point,
      expanded_text: `${point.term}：${point.definition} 关联要点：${point.fact}`,
    }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pair,
        dimension: { field: 'vector_similarity', label: '向量语义相似度', rule: 'vector', threshold: .72 },
        similarity: .84,
        threshold: .72,
        correct_answer: 'similar',
        vector_engine: 'milvus-cosine',
      }),
    })
  })
  await page.route('**/api/games/flashcard/complete', async (route) => {
    const body = route.request().postDataJSON()
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...body, score: body.difficulty === 'hard' ? 19600 : 7800, xp: body.difficulty === 'hard' ? 360 : 180 }),
    })
  })
  await page.route('**/api/games/*/submit', async (route) => {
    const body = route.request().postDataJSON()
    const game = route.request().url().split('/').at(-2)
    const expected = packs[game]._answers[body.question_id]
    const correct = body.answer === expected.answer
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ correct, answer: expected.answer, explanation: expected.explanation, score: correct ? 950 : 0, xp: correct ? 100 : 10 }),
    })
  })

  await page.goto(`${baseUrl}/games`, { waitUntil: 'networkidle' })
  await page.screenshot({ path: path.join(screenshots, `games-center-${label}.png`), fullPage: true })

  async function generate(actionName, game) {
    await page.getByRole('button', { name: new RegExp(actionName) }).click()
    await page.locator('.game-material-list label').filter({ hasText: material.name }).click()
    await page.getByRole('button', { name: '提取知识并开始游戏' }).click()
    if (game === 'monopoly') {
      await page.locator('.monopoly-frame').waitFor()
      return
    }
    await page.locator('.game-session-header h1').waitFor()
    await page.waitForFunction(() => window.scrollY === 0)
  }

  await generate('选择知识并开始', 'flashcard')
  await page.locator('.memory-board.easy').waitFor()
  await page.getByRole('button', { name: /切换难度/ }).click()
  await page.locator('.memory-board.hard').waitFor()
  if (await page.locator('.memory-card').count() !== 36) throw new Error(`${label}: hard memory board must contain 36 cards`)
  await page.getByRole('button', { name: /切换难度/ }).click()
  await page.locator('.memory-board.easy').waitFor()
  const cards = page.locator('.memory-card')
  if (await cards.count() !== 16) throw new Error(`${label}: easy memory board must contain 16 cards`)
  await cards.nth(0).click()
  await cards.nth(0).click()
  if ((await page.locator('.memory-status span').first().textContent()).trim() !== '0 步') {
    throw new Error(`${label}: clicking the same card twice changed the move count`)
  }

  const pairKeys = await cards.evaluateAll((elements) => elements.map((element) => element.dataset.pairKey))
  const cardLabels = await cards.evaluateAll((elements) => elements.map((element) => element.querySelector('.memory-card-front').textContent.trim()))
  if (!cardLabels.some((labelText) => labelText.includes('向量检索'))) throw new Error(`${label}: Agent knowledge points were not rendered on cards`)
  const differentIndex = pairKeys.findIndex((pairKey) => pairKey !== pairKeys[0])
  const thirdIndex = pairKeys.findIndex((pairKey, index) => index !== 0 && index !== differentIndex && pairKey !== pairKeys[0])
  await cards.nth(differentIndex).click()
  if (!await cards.nth(thirdIndex).isDisabled()) throw new Error(`${label}: comparison did not lock the remaining cards`)
  await page.waitForTimeout(850)

  const groups = new Map()
  pairKeys.forEach((pairKey, index) => groups.set(pairKey, [...(groups.get(pairKey) || []), index]))
  let matchedCards = 0
  for (const pair of groups.values()) {
    await cards.nth(pair[0]).click()
    await cards.nth(pair[1]).click()
    matchedCards += 2
    await page.waitForFunction((count) => document.querySelectorAll('.memory-card.matched').length === count, matchedCards)
  }
  await page.getByText('恭喜完成全部知识点配对！', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(screenshots, `games-memory-victory-${label}.png`), fullPage: true })
  const memoryResult = await page.evaluate(() => ({
    cards: document.querySelectorAll('.memory-card').length,
    matched: document.querySelectorAll('.memory-card.matched').length,
    overflow: document.documentElement.scrollWidth > innerWidth,
    moves: document.querySelector('.memory-victory-stats strong')?.textContent.trim(),
    duration: document.querySelectorAll('.memory-victory-stats strong')[1]?.textContent.trim(),
  }))
  if (memoryResult.cards !== 16 || memoryResult.matched !== 16 || memoryResult.overflow || !memoryResult.duration?.endsWith('s')) {
    throw new Error(`${label} memory workflow failed: ${JSON.stringify(memoryResult)}`)
  }
  await page.getByRole('button', { name: '再玩一次' }).click()
  await page.locator('.memory-board.easy').waitFor()
  if ((await page.locator('.memory-status span').first().textContent()).trim() !== '0 步') throw new Error(`${label}: replay did not reset the game`)
  await page.getByTitle('返回游戏中心').click()

  await generate('生成棋盘', 'monopoly')
  const monopoly = page.frameLocator('.monopoly-frame')
  await monopoly.locator('.setup-form select').selectOption('4')
  if (await monopoly.locator('[data-player-name]').count() !== 4) throw new Error(`${label}: monopoly must support four local players`)
  await monopoly.locator('.setup-form select').selectOption('1')
  if (await monopoly.locator('[data-player-name]').count() !== 1) throw new Error(`${label}: monopoly must support solo play`)
  await monopoly.getByRole('button', { name: '开始知识大富翁' }).click()
  if (await monopoly.locator('.player-roll-button').count() !== 1 || !await monopoly.getByRole('button', { name: '玩家 1 掷骰' }).isEnabled()) {
    throw new Error(`${label}: solo player dice button is unavailable`)
  }
  await monopoly.locator('body').evaluate(() => { Math.random = () => 0 })
  await monopoly.getByRole('button', { name: '玩家 1 掷骰' }).click()
  await monopoly.locator('.modal-options button').first().click()
  await monopoly.getByRole('button', { name: '继续' }).click()
  await monopoly.getByRole('button', { name: '暂不购买' }).click()
  await monopoly.getByText('第 2 回合 · 当前玩家', { exact: true }).waitFor()
  if (!await monopoly.getByRole('button', { name: '玩家 1 掷骰' }).isEnabled()) throw new Error(`${label}: solo turn did not return to the player`)
  await monopoly.locator('.controls > .button').click()
  await monopoly.locator('.modal-actions').getByRole('button', { name: '重新开始' }).click()
  await monopoly.locator('.setup-form select').waitFor()
  await monopoly.locator('.setup-form select').selectOption('2')
  await monopoly.getByRole('button', { name: '开始知识大富翁' }).click()
  if (await monopoly.locator('.space').count() !== 22) throw new Error(`${label}: monopoly board must contain 22 spaces`)
  if (await monopoly.locator('.space-property').count() !== 12) throw new Error(`${label}: monopoly board must contain 12 properties`)
  if (await monopoly.locator('.player-roll-button').count() !== 2) throw new Error(`${label}: every player needs a dice button`)
  await monopoly.locator('body').evaluate(() => { Math.random = () => 0 })
  await monopoly.getByRole('button', { name: '玩家 1 掷骰' }).click()
  await monopoly.locator('.modal-options button').first().click()
  await monopoly.getByRole('button', { name: '继续' }).click()
  await monopoly.getByRole('button', { name: /支付 100 元/ }).click()
  await monopoly.getByText('第 2 回合 · 当前玩家', { exact: true }).waitFor()
  const monopolyResult = await monopoly.locator('body').evaluate(() => ({
    spaces: document.querySelectorAll('.space').length,
    properties: document.querySelectorAll('.space-property').length,
    players: document.querySelectorAll('.player-card').length,
    tokens: [...document.querySelectorAll('.token')].map((element) => element.textContent.trim()),
    playerAnimals: document.querySelectorAll('.player-animal').length,
    diceButtons: document.querySelectorAll('.player-roll-button').length,
    enabledDice: document.querySelectorAll('.player-roll-button:not(:disabled)').length,
    owner: document.querySelector('[data-index="2"] .space-owner')?.textContent.trim(),
    overflow: document.documentElement.scrollWidth > innerWidth,
  }))
  if (monopolyResult.spaces !== 22 || monopolyResult.properties !== 12 || monopolyResult.players !== 2 || !monopolyResult.tokens.includes('🦊') || !monopolyResult.tokens.includes('🐼') || monopolyResult.playerAnimals !== 2 || monopolyResult.diceButtons !== 2 || monopolyResult.enabledDice !== 1 || monopolyResult.owner !== '玩家 1' || monopolyResult.overflow) {
    throw new Error(`${label} monopoly workflow failed: ${JSON.stringify(monopolyResult)}`)
  }
  await page.screenshot({ path: path.join(screenshots, `games-monopoly-${label}.png`), fullPage: true })
  await page.locator('.game-session-header').getByTitle('返回游戏中心').click()

  await generate('生成配对', 'matching')
  await page.screenshot({ path: path.join(screenshots, `games-matching-${label}.png`) })
  await page.locator('.matching-arcade').waitFor()
  if (await page.locator('.matching-knowledge-card').count() !== 2 || await page.locator('.matching-command-dock button').count() !== 2 || await page.locator('.matching-status-panel').count() !== 1) {
    throw new Error(`${label}: matching game did not render the automated comparison terminal`)
  }
  const dimensions = await page.locator('.matching-card-dimension span').allTextContents()
  if (dimensions.length !== 2 || !dimensions.some((value) => value.trim().length > 0)) throw new Error(`${label}: automatic comparison dimension was not rendered`)
  for (let round = 0; round < 8; round += 1) {
    if (await page.locator('.matching-level-summary').count()) break
    const answer = page.locator('.matching-command-dock button').first()
    await answer.waitFor({ state: 'visible' })
    await answer.click()
    if (round < 7) {
      try {
        await page.waitForFunction(() => [...document.querySelectorAll('.matching-command-dock button')].some((button) => !button.disabled), null, { timeout: 10000 })
      } catch (error) {
        console.log(`${label}: matching round ${round + 1} did not unlock`, await page.locator('.matching-arcade').innerText())
        throw error
      }
    }
  }
  await page.getByText('关卡结算', { exact: true }).waitFor()
  const matchingResult = await page.locator('body').evaluate(() => ({
    round: document.querySelector('.matching-status-panel strong')?.textContent.trim(),
    accuracy: document.querySelector('.matching-summary-stats strong')?.textContent.trim(),
    vectorPair: [...document.querySelectorAll('.matching-card-dimension strong')].map((element) => element.textContent.trim()),
    vectorEngine: document.querySelector('.matching-round-feedback')?.textContent.includes('Milvus Cosine'),
    overflow: document.documentElement.scrollWidth > innerWidth,
  }))
  if (!matchingResult.accuracy?.endsWith('%') || matchingResult.vectorPair.some((value) => !value.includes('余弦相似度')) || !matchingResult.vectorEngine || matchingResult.overflow) throw new Error(`${label} matching workflow failed: ${JSON.stringify(matchingResult)}`)
  await page.screenshot({ path: path.join(screenshots, `games-matching-level-${label}.png`), fullPage: true })
  await page.getByRole('button', { name: '继续挑战' }).click()
  await page.locator('.matching-arcade').waitFor()
  await page.locator('.game-session-header').getByTitle('返回游戏中心').click()
  await page.locator('.games-page').waitFor()
  await page.screenshot({ path: path.join(screenshots, `games-finish-${label}.png`), fullPage: true })

  const layout = await page.evaluate(() => ({
    viewportWidth: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    finishVisible: Boolean(document.querySelector('.games-page')),
    score: document.querySelector('.game-card h2')?.textContent.trim(),
  }))
  await page.close()
  if (layout.documentWidth > layout.viewportWidth || !layout.finishVisible || layout.score !== '知识点卡片对对碰') {
    throw new Error(`${label} game workflow failed: ${JSON.stringify(layout)}`)
  }
  return { ...layout, memoryResult, monopolyResult, matchingResult }
}

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  try {
    const desktop = await runViewport(browser, { width: 1440, height: 900 }, 'desktop')
    const mobile = await runViewport(browser, { width: 390, height: 844 }, 'mobile')
    console.log(JSON.stringify({ desktop, mobile }))
  } finally {
    await browser.close()
  }
}

run().catch((error) => { console.error(error); process.exit(1) })
