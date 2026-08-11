<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  AlertTriangle,
  ArrowLeft,
  BadgeCheck,
  Bot,
  BrainCircuit,
  Check,
  CheckCircle2,
  Clock3,
  Coins,
  Dices,
  FileText,
  Flag,
  Gamepad2,
  Gauge,
  LoaderCircle,
  LockKeyhole,
  Play,
  Puzzle,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Target,
  Trophy,
  XCircle,
  Zap,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ElectricBorder from '../components/ElectricBorder.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { api, formatBytes } from '../api'

const data = ref(null)
const loadError = ref('')
const setupGame = ref(null)
const selectedMaterialIds = ref([])
const generating = ref(false)
const generateError = ref('')
const session = ref(null)
const activeSidebarModule = ref('leaderboard')
const now = ref(Date.now())
let clock = null
let memoryEpoch = 0
let matchingEpoch = 0
let audioContext = null

const difficulty = ref({ flashcard: 'easy', monopoly: 'easy', matching: 'hard' })
const difficultyOptions = [
  { key: 'easy', label: '简单' },
  { key: 'medium', label: '中等' },
  { key: 'hard', label: '困难' },
]
const memoryDifficultyOptions = [
  { key: 'easy', label: '简单', detail: '4×4 · 8 对' },
  { key: 'hard', label: '困难', detail: '6×6 · 18 对' },
]
const visuals = {
  flashcard: { icon: BrainCircuit, class: 'flash', label: '知识记忆挑战', action: '选择知识并开始' },
  monopoly: { icon: Gamepad2, class: 'mono', label: '多人知识地产战', action: '生成棋盘' },
  matching: { icon: Puzzle, class: 'match', label: '智识对弈 · 全自动版', action: '生成配对' },
}
const sidebarModules = [
  { id: 'leaderboard', label: '排行榜', icon: Trophy },
  { id: 'best', label: '个人最佳', icon: Target },
  { id: 'packs', label: '最近生成', icon: Bot },
  { id: 'milestones', label: '里程碑', icon: Flag },
  { id: 'summary', label: '总览', icon: Gauge },
]
const activeSidebarDefinition = computed(() => sidebarModules.find((item) => item.id === activeSidebarModule.value) || sidebarModules[0])

const materials = computed(() => data.value?.materials || [])
const progress = computed(() => {
  if (!data.value) return 0
  const levelStart = Math.max(0, (data.value.level - 1) * 500)
  return Math.min(100, Math.round((data.value.xp - levelStart) / 500 * 100))
})
const currentQuestion = computed(() => session.value?.pack?.questions?.[session.value.index] || null)
const elapsed = computed(() => session.value ? Math.floor((now.value - session.value.startedAt) / 1000) : 0)
const sessionProgress = computed(() => {
  if (!session.value) return 0
  if (session.value.game.id === 'flashcard') {
    return Math.round(session.value.matchedPairs / session.value.pairCount * 100)
  }
  if (session.value.game.id === 'matching') {
    return Math.round((session.value.matching?.roundsInLevel || 0) / 8 * 100)
  }
  return Math.round((session.value.index + (session.value.feedback ? 1 : 0)) / session.value.pack.questions.length * 100)
})
const matchingQuestion = computed(() => {
  if (!session.value?.activeMatchId) return null
  return session.value.pack.questions.find((item) => item.id === session.value.activeMatchId)
})

function resetPageScroll() {
  nextTick(() => window.requestAnimationFrame(() => {
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }))
}

async function load() {
  loadError.value = ''
  try {
    data.value = await api('/games')
    if (data.value?.settings) {
      difficulty.value = {
        flashcard: data.value.settings.flashcard_difficulty || difficulty.value.flashcard,
        monopoly: data.value.settings.monopoly_difficulty || difficulty.value.monopoly,
        matching: data.value.settings.matching_difficulty || difficulty.value.matching,
      }
    }
  } catch (error) {
    loadError.value = error.message
  }
}

onMounted(() => {
  load()
  clock = window.setInterval(() => {
    now.value = Date.now()
    tickMatchingGame()
  }, 1000)
})
onUnmounted(() => {
  window.clearInterval(clock)
  memoryEpoch += 1
  matchingEpoch += 1
  audioContext?.close().catch(() => {})
})

function openSetup(game) {
  setupGame.value = game
  selectedMaterialIds.value = []
  generateError.value = data.value?.settings?.gamified_review === false
    ? '游戏化复习已关闭，请先在系统设置中启用。'
    : ''
}

function closeSetup() {
  if (generating.value) return
  setupGame.value = null
  generateError.value = ''
}

function toggleMaterial(materialId) {
  if (selectedMaterialIds.value.includes(materialId)) {
    selectedMaterialIds.value = selectedMaterialIds.value.filter((id) => id !== materialId)
  } else if (selectedMaterialIds.value.length < 10) {
    selectedMaterialIds.value = [...selectedMaterialIds.value, materialId]
  } else {
    generateError.value = '单次最多选择 10 个知识库文件'
  }
}

async function generateGame() {
  if (data.value?.settings?.gamified_review === false) {
    generateError.value = '游戏化复习已关闭，请先在系统设置中启用。'
    return
  }
  if (!setupGame.value || !selectedMaterialIds.value.length) {
    generateError.value = '请至少选择一个知识库文件'
    return
  }
  generating.value = true
  generateError.value = ''
  try {
    const pack = await api('/games/generate', {
      method: 'POST',
      body: {
        game: setupGame.value.id,
        difficulty: difficulty.value[setupGame.value.id],
        material_ids: selectedMaterialIds.value,
      },
    })
    if (setupGame.value.id === 'monopoly') {
      sessionStorage.setItem('zhiyan_monopoly_pack', JSON.stringify(pack))
      startSession(setupGame.value, pack)
      session.value.embeddedMonopoly = true
    } else if (setupGame.value.id === 'flashcard') {
      startMemoryGame(setupGame.value, pack, difficulty.value.flashcard)
    } else {
      startSession(setupGame.value, pack)
    }
    setupGame.value = null
  } catch (error) {
    generateError.value = error.message
  } finally {
    generating.value = false
  }
}

const MATCH_TITLE_HINTS = ['名称', '名字', '姓名', '标题', 'name', 'title', 'entity']
const MATCH_DESC_HINTS = ['描述', '简介', '说明', '内容', 'desc', 'description', 'detail', '概述']

function matchingKeys(records) {
  return [...new Set(records.flatMap((item) => Object.keys(item || {})))]
}

function matchingValues(records, field) {
  return records.map((item) => item?.[field]).filter((value) => value !== undefined && value !== null && value !== '')
}

function isMatchingEnum(values) {
  const strings = values.filter((value) => typeof value === 'string')
  return strings.length === values.length && new Set(strings).size >= 2 && new Set(strings).size <= 20
}

function matchingText(value) {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(' ')
  if (value === null || value === undefined) return ''
  return String(value)
}

function matchingNgrams(value) {
  const text = matchingText(value).toLowerCase().replace(/\s+/g, '')
  if (text.length < 2) return new Set(text ? [text] : [])
  return new Set(Array.from({ length: text.length - 1 }, (_, index) => text.slice(index, index + 2)))
}

function matchingJaccard(left, right) {
  const a = matchingNgrams(left)
  const b = matchingNgrams(right)
  if (!a.size && !b.size) return 1
  if (!a.size || !b.size) return 0
  const intersection = [...a].filter((item) => b.has(item)).length
  return intersection / new Set([...a, ...b]).size
}

function buildMatchingMapping(records) {
  const keys = matchingKeys(records)
  const stringKeys = keys.filter((field) => matchingValues(records, field).some((value) => typeof value === 'string'))
  const byHint = (hints) => keys.find((field) => hints.some((hint) => field.toLowerCase().includes(hint.toLowerCase())))
  const titleField = byHint(MATCH_TITLE_HINTS) || stringKeys.sort((a, b) => {
    const average = (field) => matchingValues(records, field).reduce((sum, value) => sum + String(value).length, 0) / Math.max(1, matchingValues(records, field).length)
    return average(a) - average(b)
  })[0] || keys[0]
  const descField = byHint(MATCH_DESC_HINTS) || stringKeys.filter((field) => field !== titleField).sort((a, b) => {
    const average = (field) => matchingValues(records, field).reduce((sum, value) => sum + String(value).length, 0) / Math.max(1, matchingValues(records, field).length)
    return average(b) - average(a)
  })[0] || ''
  const tagField = keys.find((field) => field !== titleField && field !== descField && isMatchingEnum(matchingValues(records, field))) || ''
  const dimensions = keys.filter((field) => ![titleField, descField, tagField].includes(field)).map((field) => {
    const values = matchingValues(records, field)
    const types = values.map((value) => Array.isArray(value) ? 'array' : typeof value)
    let rule = 'text'
    let score = 4
    if (isMatchingEnum(values)) { rule = 'enum'; score = 10 } else if (types.every((type) => type === 'number')) { rule = 'numeric'; score = 8 } else if (types.every((type) => type === 'array')) { rule = 'array'; score = 7 } else if (types.every((type) => type === 'boolean')) { rule = 'boolean'; score = 6 }
    const numbers = values.filter((value) => typeof value === 'number')
    const average = numbers.reduce((sum, value) => sum + value, 0) / Math.max(1, numbers.length)
    const deviation = Math.sqrt(numbers.reduce((sum, value) => sum + ((value - average) ** 2), 0) / Math.max(1, numbers.length))
    return { field, rule, score, threshold: rule === 'numeric' ? Math.max(1, deviation * .4) : .3 }
  }).sort((a, b) => b.score - a.score).slice(0, 5)

  const fallbackFields = [tagField, titleField, descField].filter(Boolean)
  for (const field of fallbackFields) {
    if (dimensions.length >= 3) break
    if (!dimensions.some((item) => item.field === field)) dimensions.push({ field, rule: 'text', score: 4, threshold: .3 })
  }
  return { titleField, descField, tagField, dimensions: dimensions.slice(0, 5) }
}

function matchingDifficultyForRound(round) {
  return Math.min(4, Math.floor((round - 1) / 5) + 1)
}

function matchingDimensionLabel(dimension) {
  return dimension?.field || '知识关系'
}

function matchingDimensionIcon(rule) {
  return { numeric: '📊', array: '🔗', enum: '🏷️', boolean: '◈', text: '✎', vector: '🧬' }[rule] || '✦'
}

function matchingVectorEngineLabel(engine) {
  return engine === 'milvus-cosine' ? 'Milvus Cosine' : engine === 'local-vector-fallback' ? '本地向量降级' : '向量引擎连接中'
}

function gameTitle(gameId) {
  return data.value?.games?.find((game) => game.id === gameId)?.title || gameId
}

function sourceModeLabel(mode) {
  return mode === 'deepseek-agent' ? 'AI Agent' : mode === 'local-extractor' || mode === 'local-agent' ? '本地 Agent' : mode || '未知来源'
}

function formatGameTime(value) {
  if (!value) return '暂无记录'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16)
  return parsed.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function percentValue(value, total) {
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) / Number(total) * 100)))
}

function milestoneIcon(id) {
  return {
    first_pack: Bot,
    ai_builder: Sparkles,
    first_correct: CheckCircle2,
    accuracy_drill: Target,
    game_explorer: Gamepad2,
    score_hunter: Trophy,
    knowledge_foundry: BrainCircuit,
    ranked_player: Flag,
  }[id] || LockKeyhole
}

function matchingSimilarityPercent(current) {
  const value = Number(current?.vectorSimilarity)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function matchingThresholdPercent(current) {
  const value = Number(current?.vectorThreshold)
  if (!Number.isFinite(value)) return 72
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function matchingRuleText(rule) {
  return {
    numeric: '数值距离进入阈值区间时判定相似',
    array: '存在共同标签、能力或关联知识时判定相似',
    enum: '分类、来源或主题标签一致时判定相似',
    boolean: '条件状态一致时判定相似',
    vector: 'BGE-M3 向量相似度达到阈值时判定相似',
    text: '关键语义片段重合度达到要求时判定相似',
  }[rule] || '依据当前知识字段的语义接近程度判定'
}

function matchingReviewTitle(current) {
  if (!current?.lastResult) return `推荐结论：锁定「${matchingDimensionLabel(current?.currentDimension)}」线索`
  return current.lastResult.answer === 'similar'
    ? '复盘结论：两项知识存在高关联'
    : '复盘结论：两项知识应保持区分'
}

function matchingKnowledgeExcerpt(item, field) {
  return item?.expanded_text || matchingDimensionValue(item, field)
}

function compareMatchingValues(left, right, dimension, difficultyLevel = 1) {
  const a = left?.[dimension.field]
  const b = right?.[dimension.field]
  const strictness = [1, 1, .8, .65, .5][difficultyLevel] || .5
  if (dimension.rule === 'numeric') return Math.abs(Number(a) - Number(b)) <= dimension.threshold * strictness
  if (dimension.rule === 'array') {
    const leftSet = new Set((Array.isArray(a) ? a : []).map((item) => String(item)))
    return (Array.isArray(b) ? b : []).some((item) => leftSet.has(String(item)))
  }
  if (dimension.rule === 'boolean' || dimension.rule === 'enum') return String(a) === String(b)
  return matchingJaccard(a, b) >= (.3 + Math.max(0, difficultyLevel - 1) * .07)
}

function createMatchingState(pack) {
  const knowledgeBase = (pack.knowledge_points || []).filter((item) => item && typeof item === 'object')
  if (knowledgeBase.length < 2) throw new Error('知识点数量不足，至少需要 2 个可比较条目')
  const mappings = buildMatchingMapping(knowledgeBase)
  if (mappings.dimensions.length < 3) throw new Error('无法识别有效比对维度，请检查知识库内容')
  return {
    knowledgeBase,
    mappings,
    round: 1,
    score: 0,
    combo: 0,
    maxCombo: 0,
    energy: 0,
    level: 1,
    difficulty: 1,
    roundsInLevel: 0,
    totalCorrect: 0,
    totalAnswered: 0,
    levelCorrect: 0,
    levelAnswered: 0,
    levelMaxCombo: 0,
    boostRemaining: 0,
    currentPair: [],
    currentDimension: null,
    vectorSimilarity: 0,
    vectorThreshold: .72,
    vectorEngine: 'pending',
    correctAnswer: 'similar',
    isWaiting: false,
    timeLeft: 12,
    timeLimit: 12,
    questionStartedAt: Date.now(),
    pausedUntil: 0,
    swapped: false,
    autoPending: false,
    lastResult: null,
    activeEvent: null,
    expertHint: '',
    difficultyNotice: '',
    summary: null,
  }
}

function startSession(game, pack) {
  if (game.id === 'matching') matchingEpoch += 1
  session.value = {
    game,
    pack,
    status: 'playing',
    index: 0,
    score: 0,
    xp: 0,
    correct: 0,
    selected: '',
    feedback: null,
    submitting: false,
    startedAt: Date.now(),
    questionStartedAt: Date.now(),
    position: 0,
    dice: null,
    matched: [],
    matchedTerms: [],
    activeMatchId: null,
    wrongMatchId: null,
    attempts: 0,
    matching: game.id === 'matching' ? createMatchingState(pack) : null,
  }
  if (game.id === 'matching') beginMatchingRound()
  now.value = Date.now()
  resetPageScroll()
}

function shuffle(items) {
  const result = [...items]
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(Math.random() * (index + 1))
    ;[result[index], result[target]] = [result[target], result[index]]
  }
  return result
}

function startMemoryGame(game, pack, level = difficulty.value.flashcard) {
  const selectedDifficulty = level === 'hard' ? 'hard' : 'easy'
  const pairCount = selectedDifficulty === 'hard' ? 18 : 8
  const epoch = ++memoryEpoch
  difficulty.value.flashcard = selectedDifficulty
  const knowledgePoints = pack.knowledge_points.slice(0, pairCount)
  if (knowledgePoints.length < pairCount) {
    throw new Error(`Agent 仅提取到 ${knowledgePoints.length} 个知识点，无法创建 ${pairCount} 对卡片`)
  }
  const cards = shuffle(knowledgePoints.flatMap((point, pairIndex) => [
    { id: `${epoch}-${pairIndex}-a`, pairKey: `${epoch}-${pairIndex}`, text: point.term || `知识点 ${pairIndex + 1}`, point, matched: false },
    { id: `${epoch}-${pairIndex}-b`, pairKey: `${epoch}-${pairIndex}`, text: point.term || `知识点 ${pairIndex + 1}`, point, matched: false },
  ]))
  session.value = {
    game,
    pack,
    status: 'playing',
    startedAt: Date.now(),
    memoryEpoch: epoch,
    memoryDifficulty: selectedDifficulty,
    pairCount,
    cards,
    flippedIds: [],
    matchedPairs: 0,
    locked: false,
    moves: 0,
    memoryWon: false,
    memoryResult: null,
  }
  now.value = Date.now()
  resetPageScroll()
}

function restartMemoryGame() {
  if (!session.value || session.value.game.id !== 'flashcard') return
  startMemoryGame(session.value.game, session.value.pack, session.value.memoryDifficulty)
}

function switchMemoryDifficulty() {
  if (!session.value || session.value.game.id !== 'flashcard') return
  const nextDifficulty = session.value.memoryDifficulty === 'easy' ? 'hard' : 'easy'
  startMemoryGame(session.value.game, session.value.pack, nextDifficulty)
}

function playMemorySound(success) {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (!AudioContextClass) return
    audioContext ||= new AudioContextClass()
    if (audioContext.state === 'suspended') audioContext.resume()
    const start = audioContext.currentTime
    const frequencies = success ? [660, 880] : [220, 160]
    frequencies.forEach((frequency, index) => {
      const oscillator = audioContext.createOscillator()
      const gain = audioContext.createGain()
      const toneStart = start + index * 0.09
      oscillator.type = success ? 'sine' : 'triangle'
      oscillator.frequency.setValueAtTime(frequency, toneStart)
      gain.gain.setValueAtTime(0.0001, toneStart)
      gain.gain.exponentialRampToValueAtTime(0.13, toneStart + 0.012)
      gain.gain.exponentialRampToValueAtTime(0.0001, toneStart + 0.12)
      oscillator.connect(gain)
      gain.connect(audioContext.destination)
      oscillator.start(toneStart)
      oscillator.stop(toneStart + 0.13)
    })
  } catch {
    // Audio feedback is optional when the browser blocks Web Audio.
  }
}

async function completeMemoryGame(epoch, moves, duration) {
  if (!session.value || session.value.memoryEpoch !== epoch) return
  session.value.memoryResult = { moves, duration, score: null, xp: null, error: '' }
  session.value.memoryWon = true
  try {
    const result = await api('/games/flashcard/complete', {
      method: 'POST',
      body: { difficulty: session.value.memoryDifficulty, moves, duration, pack_id: session.value.pack.id },
    })
    if (!session.value || session.value.memoryEpoch !== epoch) return
    session.value.memoryResult = { ...result, error: '' }
    await load()
  } catch (error) {
    if (!session.value || session.value.memoryEpoch !== epoch) return
    session.value.memoryResult.error = error.message
  }
}

function playMatchingSound(kind = 'correct') {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (!AudioContextClass) return
    audioContext ||= new AudioContextClass()
    if (audioContext.state === 'suspended') audioContext.resume()
    const start = audioContext.currentTime
    const tones = kind === 'correct' ? [520, 740, 980] : kind === 'event' ? [330, 520, 780] : [180, 130]
    tones.forEach((frequency, index) => {
      const oscillator = audioContext.createOscillator()
      const gain = audioContext.createGain()
      const toneStart = start + index * .07
      oscillator.type = kind === 'wrong' ? 'square' : 'triangle'
      oscillator.frequency.setValueAtTime(frequency, toneStart)
      gain.gain.setValueAtTime(.0001, toneStart)
      gain.gain.exponentialRampToValueAtTime(.08, toneStart + .01)
      gain.gain.exponentialRampToValueAtTime(.0001, toneStart + .12)
      oscillator.connect(gain)
      gain.connect(audioContext.destination)
      oscillator.start(toneStart)
      oscillator.stop(toneStart + .13)
    })
  } catch {
    // 浏览器可能在首次用户操作前阻止音频。
  }
}

function matchingPair() {
  const points = session.value.matching.knowledgeBase
  const firstIndex = Math.floor(Math.random() * points.length)
  let secondIndex = Math.floor(Math.random() * points.length)
  while (secondIndex === firstIndex && points.length > 1) secondIndex = Math.floor(Math.random() * points.length)
  return [points[firstIndex], points[secondIndex]]
}

function matchingEventForRound(round) {
  if (round < 3 || Math.random() > .25) return null
  const events = ['flash', 'pause', 'expert', 'mix']
  return events[Math.floor(Math.random() * events.length)]
}

async function beginMatchingRound() {
  const current = session.value?.matching
  if (!current || session.value.game.id !== 'matching') return
  const epoch = matchingEpoch
  current.difficulty = matchingDifficultyForRound(current.round)
  current.level = Math.floor((current.round - 1) / 8) + 1
  current.timeLimit = current.difficulty >= 4 ? 10 : 12
  current.timeLeft = current.timeLimit
  current.isWaiting = true
  current.currentPair = matchingPair()
  current.currentDimension = current.mappings.dimensions[Math.floor(Math.random() * current.mappings.dimensions.length)]
  current.correctAnswer = compareMatchingValues(current.currentPair[0], current.currentPair[1], current.currentDimension, current.difficulty) ? 'similar' : 'different'
  current.vectorEngine = 'pending'
  try {
    const result = await api('/games/matching/round', {
      method: 'POST',
      body: { pack_id: session.value.pack.id, round: current.round },
    })
    if (!session.value?.matching) return
    current.currentPair = result.pair
    current.currentDimension = result.dimension
    current.vectorSimilarity = result.similarity
    current.vectorThreshold = result.threshold
    current.correctAnswer = result.correct_answer
    current.vectorEngine = result.vector_engine || 'milvus-cosine'
  } catch {
    current.vectorEngine = 'local-vector-fallback'
  }
  if (!session.value?.matching) return
  current.isWaiting = false
  current.lastResult = null
  current.expertHint = ''
  current.swapped = false
  current.autoPending = false
  current.pausedUntil = 0
  current.questionStartedAt = Date.now()
  current.activeEvent = matchingEventForRound(current.round)
  if (current.activeEvent === 'pause') current.pausedUntil = Date.now() + 3000
  if (current.activeEvent === 'expert') {
    current.expertHint = current.correctAnswer === 'similar'
      ? '专家提示：这两个条目在当前维度上表现出明显共性。'
      : '专家提示：这两个条目在当前维度上的差异较大。'
  }
  if (current.activeEvent === 'mix') current.swapped = true
  if (current.activeEvent) playMatchingSound('event')
  if (current.boostRemaining > 0) {
    current.autoPending = true
    current.isWaiting = true
    window.setTimeout(() => {
      if (!session.value?.matching) return
      current.autoPending = false
      answerMatching('auto')
    }, 650)
  }
}

function matchingTimeLeft() {
  const current = session.value?.matching
  if (!current) return 0
  const paused = current.pausedUntil > current.questionStartedAt ? Math.min(Date.now(), current.pausedUntil) - current.questionStartedAt : 0
  const elapsedSeconds = Math.floor(Math.max(0, Date.now() - current.questionStartedAt - paused) / 1000)
  return Math.max(0, current.timeLimit - elapsedSeconds)
}

function tickMatchingGame() {
  const current = session.value?.matching
  if (!current || session.value.status !== 'playing' || current.isWaiting || current.summary) return
  current.timeLeft = matchingTimeLeft()
  if (current.timeLeft <= 0) answerMatching('timeout')
}

function comboMultiplier(combo) {
  if (combo >= 10) return 3
  if (combo >= 8) return 2.5
  if (combo >= 6) return 2
  if (combo >= 4) return 1.5
  if (combo >= 2) return 1.2
  return 1
}

function matchingAnswerText(answer) {
  const text = answer === 'similar' ? '相似' : '不同'
  return session.value?.matching?.swapped ? (text === '相似' ? '不同' : '相似') : text
}

function matchingDimensionValue(item, field) {
  const value = item?.[field]
  if (Array.isArray(value)) return value.join(' · ')
  if (typeof value === 'boolean') return value ? '是' : '否'
  return value === undefined || value === null || value === '' ? '未记录' : String(value)
}

function answerMatching(choice) {
  const current = session.value?.matching
  if (!current || (current.isWaiting && choice !== 'auto') || (current.autoPending && choice !== 'auto') || current.summary) return
  current.isWaiting = true
  current.timeLeft = matchingTimeLeft()
  const autoCorrect = choice === 'auto'
  const answer = autoCorrect ? current.correctAnswer : choice
  const correct = autoCorrect || answer === current.correctAnswer
  const comboBefore = current.combo
  const multiplier = comboMultiplier(current.combo + (correct ? 1 : 0))
  const timeBonus = current.timeLeft >= 8 ? 3 : current.timeLeft >= 5 ? 2 : current.timeLeft >= 3 ? 1 : 0
  let points = 0
  let penalty = 0
  if (correct) {
    current.combo += 1
    current.maxCombo = Math.max(current.maxCombo, current.combo)
    current.levelMaxCombo = Math.max(current.levelMaxCombo, current.combo)
    points = Math.round((10 * multiplier + timeBonus) * (current.activeEvent === 'flash' ? 2 : 1))
    current.score += points
    current.energy = Math.min(100, current.energy + 10 + current.combo * 2)
    current.totalCorrect += 1
    current.levelCorrect += 1
    if (current.energy >= 100) {
      current.energy = 0
      current.boostRemaining = 3
      current.activeEvent = 'burst'
      playMatchingSound('event')
    }
    playMatchingSound('correct')
  } else {
    penalty = choice === 'timeout' ? 3 : Math.floor(5 + comboBefore * .5)
    current.score = Math.max(0, current.score - penalty)
    current.combo = 0
    playMatchingSound('wrong')
  }
  if (current.boostRemaining > 0 && autoCorrect) current.boostRemaining -= 1
  current.totalAnswered += 1
  current.levelAnswered += 1
  current.roundsInLevel += 1
  current.lastResult = { correct, answer: current.correctAnswer, points, penalty, timeout: choice === 'timeout' }
  if (current.roundsInLevel >= 8) {
    window.setTimeout(() => finishMatchingLevel(), 850)
    return
  }
  const nextRound = current.round + 1
  const oldDifficulty = current.difficulty
  window.setTimeout(() => {
    if (!session.value?.matching || current !== session.value.matching) return
    current.round = nextRound
    beginMatchingRound()
    if (current.difficulty > oldDifficulty) {
      current.difficultyNotice = '难度提升！标准更严格，继续保持专注。'
      window.setTimeout(() => { if (session.value?.matching === current) current.difficultyNotice = '' }, 1800)
    }
  }, 1000)
}

function finishMatchingLevel() {
  const current = session.value?.matching
  if (!current) return
  const accuracy = current.levelAnswered ? current.levelCorrect / current.levelAnswered : 0
  const passed = accuracy >= .6
  const reward = passed ? 20 : 0
  if (passed) current.score += reward
  current.energy = Math.min(100, current.energy + (passed ? 20 : 0))
  current.summary = {
    accuracy: Math.round(accuracy * 100),
    maxCombo: current.levelMaxCombo,
    reward,
    energy: passed ? 20 : 0,
    passed,
    level: current.level,
  }
  current.isWaiting = false
  playMatchingSound('event')
}

function continueMatchingLevel() {
  const current = session.value?.matching
  if (!current?.summary) return
  current.summary = null
  current.levelCorrect = 0
  current.levelAnswered = 0
  current.levelMaxCombo = 0
  current.round += 1
  current.roundsInLevel = 0
  beginMatchingRound()
}

function flipMemoryCard(card) {
  const current = session.value
  if (!current || current.game.id !== 'flashcard' || current.locked || current.memoryWon) return
  if (card.matched || current.flippedIds.includes(card.id)) return

  if (!current.flippedIds.length) {
    current.flippedIds = [card.id]
    return
  }

  const firstCard = current.cards.find((item) => item.id === current.flippedIds[0])
  const epoch = current.memoryEpoch
  const isMatch = firstCard?.pairKey === card.pairKey
  current.flippedIds = [firstCard.id, card.id]
  current.moves += 1
  current.locked = true
  playMemorySound(isMatch)

  window.setTimeout(() => {
    const active = session.value
    if (!active || active.memoryEpoch !== epoch) return
    if (isMatch) {
      active.cards = active.cards.map((item) => (
        active.flippedIds.includes(item.id) ? { ...item, matched: true } : item
      ))
      active.matchedPairs += 1
    }
    active.flippedIds = []
    active.locked = false
    if (isMatch && active.matchedPairs === active.pairCount) {
      const duration = Math.max(1, Math.floor((Date.now() - active.startedAt) / 1000))
      completeMemoryGame(epoch, active.moves, duration)
    }
  }, isMatch ? 420 : 780)
}

function questionDuration() {
  return Math.max(1, Math.floor((Date.now() - session.value.questionStartedAt) / 1000))
}

async function submitAnswer(question, answer) {
  if (!session.value || session.value.submitting) return null
  session.value.submitting = true
  try {
    const result = await api(`/games/${session.value.game.id}/submit`, {
      method: 'POST',
      body: {
        question_id: question.id,
        pack_id: session.value.pack.id,
        answer,
        duration: questionDuration(),
      },
    })
    session.value.attempts += 1
    session.value.score += result.score
    session.value.xp += result.xp
    if (result.correct) session.value.correct += 1
    return result
  } finally {
    session.value.submitting = false
  }
}

async function answerCurrent(option) {
  if (!currentQuestion.value || session.value.feedback) return
  session.value.selected = option
  const result = await submitAnswer(currentQuestion.value, option)
  session.value.feedback = result
  if (session.value.game.id === 'monopoly') {
    const steps = result.correct ? session.value.dice : 1
    session.value.position = (session.value.position + steps) % 12
  }
}

function nextQuestion() {
  if (session.value.index >= session.value.pack.questions.length - 1) {
    finishSession()
    return
  }
  session.value.index += 1
  session.value.selected = ''
  session.value.feedback = null
  session.value.questionStartedAt = Date.now()
  if (session.value.game.id === 'monopoly') session.value.dice = null
}

function rollDice() {
  if (session.value.dice || session.value.feedback) return
  session.value.dice = Math.floor(Math.random() * 6) + 1
  session.value.questionStartedAt = Date.now()
}

function selectDefinition(questionId) {
  if (session.value.matched.includes(questionId)) return
  session.value.activeMatchId = questionId
  session.value.wrongMatchId = null
}

async function selectTerm(term) {
  const question = matchingQuestion.value
  if (!question || session.value.submitting) return
  const result = await submitAnswer(question, term)
  if (result.correct) {
    session.value.matched = [...session.value.matched, question.id]
    session.value.matchedTerms = [...session.value.matchedTerms, term]
    session.value.activeMatchId = null
    session.value.wrongMatchId = null
    if (session.value.matched.length === session.value.pack.questions.length) finishSession()
  } else {
    session.value.wrongMatchId = question.id
  }
}

async function finishSession() {
  session.value.status = 'result'
  await load()
  resetPageScroll()
}

function leaveGame() {
  memoryEpoch += 1
  matchingEpoch += 1
  session.value = null
  resetPageScroll()
}

function replay() {
  const game = session.value.game
  if (game.id === 'flashcard') {
    restartMemoryGame()
    return
  }
  session.value = null
  openSetup(game)
}

function boardLabel(index) {
  const points = session.value.pack.knowledge_points
  return points[index % points.length]?.term || `知识格 ${index + 1}`
}
</script>

<template>
  <AppShell search-placeholder="搜索游戏或知识文件..." :immersive="!!session">
    <div v-if="!data && !loadError" class="page-loader">正在载入游戏中心...</div>
    <div v-else-if="loadError" class="page-loader game-load-error">
      <AlertTriangle /><span>{{ loadError }}</span><button class="button primary" @click="load">重新加载</button>
    </div>

    <div v-else-if="session" class="game-modal-backdrop" role="dialog" aria-modal="true" :aria-label="session.game.title">
      <section class="game-modal-surface" :class="{ 'monopoly-modal': session.game.id === 'monopoly', 'matching-modal': session.game.id === 'matching' }">
      <header class="game-session-header">
        <button class="icon-button" title="返回游戏中心" @click="leaveGame"><ArrowLeft /></button>
        <div>
          <span>{{ session.pack.title }}</span>
          <h1>{{ session.game.title }}</h1>
        </div>
        <div class="game-live-stats">
          <span><Clock3 /> {{ elapsed }}s</span>
          <template v-if="session.game.id === 'flashcard'">
            <span><Target /> {{ session.moves }} 步</span>
            <strong>{{ session.matchedPairs }} / {{ session.pairCount }} 对</strong>
          </template>
          <template v-else-if="session.game.id === 'matching'">
            <span><Target /> 第 {{ session.matching.round }} 轮</span>
            <span><Zap /> {{ session.matching.energy }}%</span>
            <strong>{{ session.matching.score.toLocaleString() }} 分</strong>
          </template>
          <template v-else>
            <span><Target /> {{ session.correct }}</span>
            <strong>{{ session.score.toLocaleString() }} 分</strong>
          </template>
        </div>
      </header>
      <div class="game-session-progress"><i :style="{ width: `${sessionProgress}%` }"></i></div>

      <section v-if="session.status === 'result'" class="game-finish">
        <Trophy />
        <span>本局完成</span>
        <h2>{{ session.game.title }}</h2>
        <p>已完成 {{ session.pack.questions.length }} 个来自所选知识文件的学习挑战。</p>
        <div class="game-finish-stats">
          <span><strong>{{ session.score.toLocaleString() }}</strong><small>本局得分</small></span>
          <span><strong>{{ session.correct }}/{{ session.pack.questions.length }}</strong><small>正确进度</small></span>
          <span><strong>+{{ session.xp }}</strong><small>知识经验</small></span>
          <span><strong>{{ elapsed }}s</strong><small>完成用时</small></span>
        </div>
        <p class="game-agent-source"><Bot /> {{ session.pack.agent_note }}</p>
        <div class="game-finish-actions">
          <button class="button ghost" @click="leaveGame">返回游戏中心</button>
          <button class="button primary" @click="replay"><RotateCcw /> 换一组知识再玩</button>
        </div>
      </section>

      <template v-else-if="session.game.id === 'flashcard'">
        <main class="memory-game-shell">
          <header class="memory-toolbar">
            <div>
              <span>RETRO MEMORY CLUB</span>
              <h2>知识点卡片对对碰</h2>
              <p>{{ session.memoryDifficulty === 'easy' ? '简单 · 4×4 · 8 对' : '困难 · 6×6 · 18 对' }}</p>
            </div>
            <div class="memory-actions">
              <button class="button ghost" @click="restartMemoryGame"><RotateCcw /> 重新开始</button>
              <button class="button primary" @click="switchMemoryDifficulty"><Gauge /> 切换难度</button>
            </div>
          </header>
          <section
            class="memory-board"
            :class="session.memoryDifficulty"
            :aria-label="`${session.memoryDifficulty === 'easy' ? '简单' : '困难'}知识点卡片对对碰棋盘`"
          >
            <button
              v-for="card in session.cards"
              :key="card.id"
              class="memory-card"
              :class="{
                flipped: card.matched || session.flippedIds.includes(card.id),
                matched: card.matched,
              }"
              :disabled="card.matched || session.locked || session.memoryWon"
              :aria-label="card.matched ? `已配对 ${card.text}` : '翻开知识点卡片'"
              :data-pair-key="card.pairKey"
              @click="flipMemoryCard(card)"
            >
              <span class="memory-card-inner">
                <span class="memory-card-face memory-card-back"><b>✦</b><small>ZH YAN</small></span>
                <span class="memory-card-face memory-card-front" :title="`${card.text}：${card.point.definition}`"><span>{{ card.text }}</span></span>
              </span>
            </button>
          </section>
          <footer class="memory-status" aria-live="polite">
            <span><Target /> {{ session.moves }} 步</span>
            <span><Clock3 /> {{ elapsed }} 秒</span>
            <span><CheckCircle2 /> {{ session.matchedPairs }} / {{ session.pairCount }} 对</span>
          </footer>
        </main>
      </template>

      <template v-else-if="session.game.id === 'monopoly'">
        <iframe class="monopoly-frame" src="/knowledge-monopoly.html?embedded=1" title="知识大富翁游戏"></iframe>
      </template>

      <template v-else>
        <main class="matching-arcade" :class="{ 'matching-error-state': session.matching.lastResult && !session.matching.lastResult.correct }">
          <div class="matching-scanlines" aria-hidden="true"></div>
          <header class="matching-arcade-header">
            <div>
              <span class="matching-kicker">GAME MATCH ANALYSIS</span>
              <h2>对局复盘终端</h2>
              <p>智能对战分析系统正在读取所选素材的知识点、语义向量与来源证据。</p>
            </div>
            <button class="matching-reset" title="重新选择知识素材" @click="leaveGame"><RotateCcw /> 重选知识</button>
          </header>

          <section class="matching-status-panel" aria-label="游戏状态">
            <div><small>回合</small><strong>{{ session.matching.round }}</strong></div>
            <div><small>匹配度</small><strong>{{ matchingSimilarityPercent(session.matching) }}%</strong></div>
            <div><small>阈值</small><strong>{{ matchingThresholdPercent(session.matching) }}%</strong></div>
            <div class="matching-energy"><small>知识能量 <b>{{ session.matching.energy }}%</b></small><i><b :style="{ width: `${session.matching.energy}%` }"></b></i></div>
            <div><small>倒计时</small><strong>{{ session.matching.timeLeft }}s</strong></div>
          </section>

          <div v-if="session.matching.difficultyNotice" class="matching-event-banner difficulty">{{ session.matching.difficultyNotice }}</div>
          <div v-if="session.matching.activeEvent" class="matching-event-banner">
            <Sparkles />
            <span v-if="session.matching.activeEvent === 'flash'">知识闪光：本轮得分 ×2</span>
            <span v-else-if="session.matching.activeEvent === 'pause'">时间暂停：倒计时冻结 3 秒</span>
            <span v-else-if="session.matching.activeEvent === 'expert'">{{ session.matching.expertHint }}</span>
            <span v-else-if="session.matching.activeEvent === 'mix'">思维混乱：按钮文字已交换</span>
            <span v-else>知识爆发：连续 3 轮自动判定正确</span>
          </div>

          <div class="matching-match-meter" aria-label="语义匹配度">
            <i :style="{ width: `${matchingSimilarityPercent(session.matching)}%` }"></i>
            <b :style="{ left: `${matchingThresholdPercent(session.matching)}%` }"></b>
            <span>匹配度 {{ matchingSimilarityPercent(session.matching) }}%</span>
          </div>

          <div class="matching-timer" aria-label="本轮倒计时">
            <i :style="{ width: `${session.matching.timeLeft / session.matching.timeLimit * 100}%` }"></i>
            <span>{{ session.matching.timeLeft }}s</span>
          </div>

          <section class="matching-round-prompt">
            <span>{{ matchingDimensionIcon(session.matching.currentDimension.rule) }} 比较两个知识点的【{{ matchingDimensionLabel(session.matching.currentDimension) }}】</span>
            <strong>{{ matchingReviewTitle(session.matching) }}</strong>
            <small>{{ matchingRuleText(session.matching.currentDimension.rule) }}</small>
          </section>

          <section class="matching-pair-layout">
            <article class="matching-knowledge-card">
              <span class="matching-card-index">知识点 A</span>
              <span v-if="session.matching.mappings.tagField" class="matching-card-tag">{{ matchingDimensionValue(session.matching.currentPair[0], session.matching.mappings.tagField) }}</span>
              <h3>{{ matchingDimensionValue(session.matching.currentPair[0], session.matching.mappings.titleField) }}</h3>
              <p>{{ matchingKnowledgeExcerpt(session.matching.currentPair[0], session.matching.mappings.descField) }}</p>
              <div class="matching-card-dimension">
                <span>{{ matchingDimensionIcon(session.matching.currentDimension.rule) }} {{ matchingDimensionLabel(session.matching.currentDimension) }}</span>
                <strong v-if="session.matching.currentDimension.rule === 'vector'">余弦相似度 {{ session.matching.vectorSimilarity.toFixed(3) }} / 阈值 {{ session.matching.vectorThreshold.toFixed(2) }}</strong>
                <strong v-else>{{ matchingDimensionValue(session.matching.currentPair[0], session.matching.currentDimension.field) }}</strong>
              </div>
            </article>

            <div class="matching-decision-panel">
              <span>语义雷达</span>
              <div class="matching-radar-core">
                <strong>{{ matchingSimilarityPercent(session.matching) }}%</strong>
                <small>余弦匹配</small>
              </div>
              <p>{{ matchingVectorEngineLabel(session.matching.vectorEngine) }} · 阈值 {{ session.matching.vectorThreshold.toFixed(2) }}</p>
              <p v-if="session.matching.boostRemaining" class="matching-auto-note"><Zap /> 自动判定剩余 {{ session.matching.boostRemaining }} 轮</p>
            </div>

            <article class="matching-knowledge-card">
              <span class="matching-card-index">知识点 B</span>
              <span v-if="session.matching.mappings.tagField" class="matching-card-tag">{{ matchingDimensionValue(session.matching.currentPair[1], session.matching.mappings.tagField) }}</span>
              <h3>{{ matchingDimensionValue(session.matching.currentPair[1], session.matching.mappings.titleField) }}</h3>
              <p>{{ matchingKnowledgeExcerpt(session.matching.currentPair[1], session.matching.mappings.descField) }}</p>
              <div class="matching-card-dimension">
                <span>{{ matchingDimensionIcon(session.matching.currentDimension.rule) }} {{ matchingDimensionLabel(session.matching.currentDimension) }}</span>
                <strong v-if="session.matching.currentDimension.rule === 'vector'">余弦相似度 {{ session.matching.vectorSimilarity.toFixed(3) }} / 阈值 {{ session.matching.vectorThreshold.toFixed(2) }}</strong>
                <strong v-else>{{ matchingDimensionValue(session.matching.currentPair[1], session.matching.currentDimension.field) }}</strong>
              </div>
            </article>
          </section>

          <section class="matching-command-dock" aria-label="对弈操作">
            <button :disabled="session.matching.isWaiting" :class="{ primary: !session.matching.swapped }" @click="answerMatching(session.matching.swapped ? 'different' : 'similar')"><CheckCircle2 /> {{ matchingAnswerText('similar') }}</button>
            <button :disabled="session.matching.isWaiting" :class="{ primary: session.matching.swapped }" @click="answerMatching(session.matching.swapped ? 'similar' : 'different')"><XCircle /> {{ matchingAnswerText('different') }}</button>
            <span><Gauge /> 第 {{ session.matching.level }} 关 · {{ session.matching.roundsInLevel }}/8</span>
            <span><Zap /> 连击 {{ session.matching.combo }} × {{ comboMultiplier(session.matching.combo).toFixed(1) }}</span>
          </section>

          <footer class="matching-round-feedback" aria-live="polite">
            <span v-if="!session.matching.lastResult"><Target /> 本轮等待你的判断</span>
            <span v-else-if="session.matching.lastResult.correct" class="correct"><CheckCircle2 /> 判断正确！ +{{ session.matching.lastResult.points }} 分 · 连击 {{ session.matching.combo }}</span>
            <span v-else class="wrong"><XCircle /> {{ session.matching.lastResult.timeout ? '时间到，' : '' }}判断错误 · 连击归零 · -{{ session.matching.lastResult.penalty }} 分</span>
            <span>难度 {{ session.matching.difficulty }} · {{ matchingVectorEngineLabel(session.matching.vectorEngine) }} · {{ session.matching.activeEvent ? '特殊事件生效中' : '标准模式' }}</span>
          </footer>
        </main>
      </template>
      </section>
    </div>

    <div v-else class="page-wrap games-page">
      <section class="level-panel panel">
        <div><span>当前等级</span><strong>{{ data.level }} <small v-if="data.xp > 0">持续学习</small></strong></div>
        <div class="xp-block"><span>知识经验值</span><i><b :style="{ width: `${progress}%` }"></b></i><small>{{ data.xp.toLocaleString() }} XP <em>等级 {{ data.level + 1 }} 目标 {{ data.next_level_xp.toLocaleString() }} XP</em></small></div>
        <div class="economy"><span><Coins /><strong>{{ data.coins.toLocaleString() }}</strong><small>智衍币</small></span><span><Puzzle /><strong>{{ data.props }}</strong><small>强化道具</small></span></div>
      </section>

      <div class="games-layout">
        <main>
          <div class="games-title"><div><h1>知识游戏</h1><p>从自己的知识库生成专属挑战</p></div><span><BadgeCheck /> 题目均绑定来源素材</span></div>
          <section class="game-list">
            <ElectricBorder v-for="game in data.games" :key="game.id" class="game-card-border" color="#7df9ff" :speed="1" :chaos="0.12" :thickness="2" :border-radius="16">
              <article class="game-card">
                <div class="game-art" :class="visuals[game.id].class"><component :is="visuals[game.id].icon" /><span>{{ visuals[game.id].label }}</span></div>
                <div class="game-info">
                  <span class="game-tag">{{ game.id === 'flashcard' ? '记忆' : game.id === 'monopoly' ? '策略' : '关联' }}</span>
                  <h2>{{ game.title }}</h2><p>{{ game.description }}</p>
                  <div class="game-framework">
                    <span v-if="game.id === 'flashcard'"><Gauge /> Agent 提取 · 知识点配对</span>
                    <span v-else-if="game.id === 'monopoly'"><Dices /> 掷骰移动 · 知识事件</span>
                    <span v-else><Puzzle /> 自动映射 · 相似/不同判断</span>
                  </div>
                  <div v-if="game.id !== 'matching'" class="difficulty">
                    <button
                      v-for="item in game.id === 'flashcard' ? memoryDifficultyOptions : difficultyOptions"
                      :key="item.key"
                      :class="{ active: difficulty[game.id] === item.key }"
                      :title="item.detail || item.label"
                      @click="difficulty[game.id] = item.key"
                    >{{ item.label }}</button>
                  </div>
                  <div v-else class="game-auto-badge"><Bot /> 全自动映射 · 难度随轮次提升</div>
                  <button class="button outline" @click="openSetup(game)">{{ visuals[game.id].action }} <Zap /></button>
                </div>
              </article>
            </ElectricBorder>
          </section>
        </main>

        <section class="game-sidebar">
          <nav class="game-module-tabs" aria-label="游戏数据模块">
            <button
              v-for="module in sidebarModules"
              :key="module.id"
              :class="{ active: activeSidebarModule === module.id }"
              :title="module.label"
              :aria-label="module.label"
              @click="activeSidebarModule = module.id"
            >
              <component :is="module.icon" />
              <span>{{ module.label }}</span>
            </button>
          </nav>

          <article class="panel game-module-panel">
            <header class="game-module-header">
              <div><span>GAME DATA MODULE</span><h2>{{ activeSidebarDefinition.label }}</h2></div>
              <component :is="activeSidebarDefinition.icon" />
            </header>

            <section v-if="activeSidebarModule === 'leaderboard'" class="module-content leaderboard">
              <div v-if="data.leaderboard?.length" v-for="(player, index) in data.leaderboard" :key="`${player.nickname}-${index}`" class="leaderboard-row">
                <b>{{ index + 1 }}</b>
                <span class="avatar"><Sparkles /></span>
                <p><strong>{{ player.nickname }}</strong><small>{{ player.score.toLocaleString() }} 分 · 答对 {{ player.correct || 0 }} 次</small></p>
                <Trophy />
              </div>
              <p v-else class="game-empty">完成一局游戏后进入排行榜</p>
              <footer v-if="data.rank" class="leaderboard-rank"><b>{{ data.rank }}</b><span>您的排名<small>{{ data.total_players ? `共 ${data.total_players} 位玩家` : '暂无其他玩家' }}</small></span></footer>
            </section>

            <section v-else-if="activeSidebarModule === 'best'" class="module-content best-module">
              <div v-for="best in (data.game_stats || data.best || [])" :key="best.game" class="best-row">
                <span class="best-game-dot" :class="`best-${best.game}`"></span>
                <div><strong>{{ gameTitle(best.game) }}</strong><small>{{ best.attempts || 0 }} 次挑战 · 答对 {{ best.correct || 0 }} 次 · 平均 {{ best.avg_duration || 0 }}s</small></div>
                <b>{{ Number(best.best_score || best.score || 0).toLocaleString() }}<small>最高分</small></b>
              </div>
              <p v-if="!(data.game_stats || data.best || []).length" class="game-empty">完成首局后显示真实最佳记录</p>
            </section>

            <section v-else-if="activeSidebarModule === 'packs'" class="module-content packs-module">
              <div v-for="pack in data.recent_packs" :key="pack.id" class="pack-row">
                <Bot />
                <div><strong>{{ pack.title }}</strong><small>{{ gameTitle(pack.game) }} · {{ pack.question_count }} 题 · {{ sourceModeLabel(pack.source_mode) }}</small></div>
                <time>{{ formatGameTime(pack.created_at) }}</time>
              </div>
              <p v-if="!data.recent_packs?.length" class="game-empty">尚未生成专属题包</p>
            </section>

            <section v-else-if="activeSidebarModule === 'milestones'" class="module-content milestones-module">
              <div v-for="milestone in (data.milestones || [])" :key="milestone.id" class="milestone-row" :class="{ unlocked: milestone.unlocked }">
                <span class="milestone-icon"><component :is="milestoneIcon(milestone.id)" /></span>
                <div><strong>{{ milestone.title }}</strong><small>{{ milestone.description }}</small><i><b :style="{ width: `${percentValue(milestone.progress, milestone.target)}%` }"></b></i><em>{{ milestone.progress }}/{{ milestone.target }}</em></div>
                <component :is="milestone.unlocked ? CheckCircle2 : LockKeyhole" />
              </div>
              <p v-if="!data.milestones?.length" class="game-empty">暂无可统计的里程碑</p>
            </section>

            <section v-else class="module-content summary-module">
              <div class="summary-feature"><strong>{{ data.summary?.total_score?.toLocaleString?.() || 0 }}</strong><span>累计得分</span></div>
              <div class="summary-grid">
                <span><b>{{ data.summary?.attempts || 0 }}</b><small>挑战次数</small></span>
                <span><b>{{ data.summary?.correct || 0 }}</b><small>正确次数</small></span>
                <span><b>{{ data.summary?.pack_count || 0 }}</b><small>生成题包</small></span>
                <span><b>{{ data.summary?.generated_question_count || 0 }}</b><small>累计题目</small></span>
              </div>
              <p class="summary-note">覆盖 {{ data.summary?.game_count || 0 }} 种游戏模式 · 平均用时 {{ data.summary?.avg_duration || 0 }}s</p>
            </section>
          </article>
        </section>
      </div>
    </div>

    <ModalDialog v-if="setupGame" :title="`生成${setupGame.title}`" wide :close-disabled="generating" @close="closeSetup">
      <section v-if="generating" class="game-agent-loading" aria-live="polite">
        <LoaderCircle />
        <h3>Agent 正在构建游戏题包</h3>
        <p>扫描所选文件，提取核心概念并生成 {{ setupGame.title }} 的交互内容。</p>
        <div><span class="done"><Check /> 读取知识库正文</span><span><Bot /> 提取重要知识点</span><span><ShieldCheck /> 生成并校验游戏题目</span></div>
      </section>
      <section v-else class="game-generator">
        <div class="game-generator-summary"><component :is="visuals[setupGame.id].icon" /><div><h3>{{ visuals[setupGame.id].label }}</h3><p>{{ setupGame.description }}</p></div><b>{{ setupGame.id === 'matching' ? '自动模式' : difficultyOptions.find((item) => item.key === difficulty[setupGame.id])?.label }}</b></div>
        <div class="game-material-toolbar"><span>选择知识文件 <strong>{{ selectedMaterialIds.length }} / 10</strong></span><small>{{ data.settings.gamified_review === false ? '游戏化复习已关闭，无法生成新题包' : 'Agent 只使用所选文件生成本局内容' }}</small></div>
        <div class="game-material-list">
          <label v-for="material in materials" :key="material.id" :class="{ selected: selectedMaterialIds.includes(material.id) }">
            <input type="checkbox" :checked="selectedMaterialIds.includes(material.id)" @change="toggleMaterial(material.id)" />
            <FileText />
            <span><strong>{{ material.name }}</strong><small>{{ material.kind }} · {{ material.category }} · {{ formatBytes(material.size) }}</small><em>{{ material.content }}</em></span>
          </label>
          <div v-if="!materials.length" class="game-empty">知识库中暂无可用文件，请先导入知识。</div>
        </div>
        <p class="game-agent-rule"><Bot /> 优先使用 AI Agent 提取知识点；服务不可用时自动启用本地文本 Agent，游戏仍可正常进行。</p>
        <p v-if="generateError" class="game-generate-error"><AlertTriangle /> {{ generateError }}</p>
        <div class="url-actions"><button class="button ghost" @click="closeSetup">取消</button><button class="button primary" :disabled="!selectedMaterialIds.length || data.settings.gamified_review === false" @click="generateGame"><Play /> 提取知识并开始游戏</button></div>
      </section>
    </ModalDialog>

    <ModalDialog
      v-if="session?.game.id === 'flashcard' && session.memoryWon"
      title="配对挑战完成"
      @close="session.memoryWon = false"
    >
      <section class="memory-victory">
        <div class="memory-victory-medal"><Trophy /></div>
        <span>CONGRATULATIONS</span>
        <h3>恭喜完成全部知识点配对！</h3>
        <p>{{ session.memoryDifficulty === 'easy' ? '简单模式 · 4×4' : '困难模式 · 6×6' }}</p>
        <div class="memory-victory-stats">
          <span><strong>{{ session.memoryResult.moves }}</strong><small>完成步数</small></span>
          <span><strong>{{ session.memoryResult.duration }}s</strong><small>完成用时</small></span>
          <span v-if="session.memoryResult.score !== null"><strong>{{ session.memoryResult.score.toLocaleString() }}</strong><small>本局得分</small></span>
        </div>
        <p v-if="session.memoryResult.error" class="game-generate-error"><AlertTriangle /> {{ session.memoryResult.error }}</p>
        <div class="memory-victory-actions">
          <button class="button ghost" @click="leaveGame">返回游戏中心</button>
          <button class="button primary" @click="restartMemoryGame"><RotateCcw /> 再玩一次</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog
      v-if="session?.game.id === 'matching' && session.matching.summary"
      title="关卡结算"
      :close-disabled="false"
      @close="continueMatchingLevel"
    >
      <section class="matching-level-summary">
        <div class="matching-summary-icon"><Trophy /></div>
        <span>LEVEL {{ session.matching.summary.level }} COMPLETE</span>
        <h3>{{ session.matching.summary.passed ? '关卡通过！' : '继续练习，下一关重新开始' }}</h3>
        <p>本关完成 8 轮判断，Agent 记录了你的知识比对表现。</p>
        <div class="matching-summary-stats">
          <span><strong>{{ session.matching.summary.accuracy }}%</strong><small>正确率</small></span>
          <span><strong>{{ session.matching.summary.maxCombo }}</strong><small>最高连击</small></span>
          <span><strong>+{{ session.matching.summary.reward }}</strong><small>奖励分数</small></span>
          <span><strong>+{{ session.matching.summary.energy }}</strong><small>能量恢复</small></span>
        </div>
        <p class="matching-summary-note"><CheckCircle2 /> {{ session.matching.summary.passed ? '已达到 60% 通关标准，准备进入下一关。' : '本关不扣分，下一关将重新统计正确率。' }}</p>
        <button class="button primary" @click="continueMatchingLevel">继续挑战 <ArrowLeft class="rotate-icon" /></button>
      </section>
    </ModalDialog>
  </AppShell>
</template>
