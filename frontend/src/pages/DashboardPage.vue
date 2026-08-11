<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  ArrowUpRight,
  Bot,
  BrainCircuit,
  Building2,
  CheckCircle2,
  Database,
  FileText,
  FolderKanban,
  KeyRound,
  Network,
  Sparkles,
  Target,
  Upload,
  UserPlus,
  Zap,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { api } from '../api'

const data = ref(null)
const teams = ref([])
const question = ref('')
const answer = ref('')
const asking = ref(false)
const showAsk = ref(false)
const trendChart = ref(null)
const joinTeamOpen = ref(false)
const joinTeamCode = ref('')
const joiningTeam = ref(false)
const joinTeamError = ref('')
const joinTeamNotice = ref('')

let chartInstance = null

function getWeekDateLabels() {
  const today = new Date()
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today)
    d.setDate(d.getDate() - (6 - i))
    return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
  })
}
const weekLabels = getWeekDateLabels()

function formatNumber(value) {
  return Number(value || 0).toLocaleString()
}

function normalizeSeven(values, fallback = 0) {
  const source = Array.isArray(values) ? values : []
  return weekLabels.map((_, index) => Number(source[index] ?? fallback))
}

const trendValues = computed(() => normalizeSeven(data.value?.trend, 0))
const accuracyValues = computed(() => normalizeSeven(data.value?.accuracy, 0))

const maxTrend = computed(() => Math.max(...trendValues.value, 1))

const topCategories = computed(() => (data.value?.category_distribution || []).slice(0, 3))
const latestMaterials = computed(() => data.value?.recent || [])
const teamRoleLabels = {
  owner: '负责人',
  admin: '管理员',
  editor: '编辑成员',
  viewer: '只读成员',
}

const stats = computed(() => {
  if (!data.value) return []
  const mastery = Number(data.value.mastery || 0)
  return [
    {
      id: 'knowledge',
      icon: Database,
      tone: 'cyan',
      label: '知识总量',
      value: formatNumber(data.value.knowledge_total),
      unit: '素材',
      meta: data.value.today_added > 0 ? `今日新增 ${data.value.today_added} 条` : '知识库稳定运行',
      progress: Math.min(Number(data.value.knowledge_total || 0), 100),
    },
    {
      id: 'today',
      icon: Sparkles,
      tone: 'mint',
      label: '今日新增',
      value: formatNumber(data.value.today_added),
      unit: '实体',
      meta: data.value.today_added > 0 ? '已同步进入知识流' : '等待新的知识输入',
      progress: Math.min(Number(data.value.today_added || 0) * 20, 100),
    },
    {
      id: 'category',
      icon: FolderKanban,
      tone: 'blue',
      label: '分类结构',
      value: formatNumber(topCategories.value.length),
      unit: '类目',
      meta: topCategories.value.length ? topCategories.value.map((item) => item.name).join(' / ') : '暂无分类数据',
      progress: Math.min(topCategories.value.reduce((sum, item) => sum + Number(item.value || 0), 0), 100),
    },
    {
      id: 'mastery',
      icon: Target,
      tone: 'amber',
      label: '平均掌握度',
      value: `${mastery}%`,
      unit: '掌握',
      meta: mastery >= 80 ? '掌握优秀，继续保持' : mastery >= 50 ? '稳步提升中' : '建议进入复习训练',
      progress: mastery,
    },
  ]
})

const trendSummary = computed(() => {
  const total = trendValues.value.reduce((sum, value) => sum + value, 0)
  const avgAccuracy = Math.round(
    accuracyValues.value.reduce((sum, value) => sum + value, 0) / Math.max(accuracyValues.value.length, 1),
  )
  return {
    total,
    avgAccuracy,
    peak: Math.max(...trendValues.value, 0),
  }
})

function chartOption() {
  return {
    backgroundColor: 'transparent',
    animationDuration: 1200,
    animationEasing: 'cubicOut',
    color: ['#7df9ff', '#a2ffd6'],
    grid: { left: 42, right: 38, top: 42, bottom: 38, containLabel: true },
    tooltip: {
      trigger: 'axis',
      appendToBody: true,
      backgroundColor: 'rgba(5, 19, 34, .94)',
      borderColor: 'rgba(125, 249, 255, .34)',
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: '#dffbff', fontSize: 12 },
      axisPointer: {
        type: 'line',
        lineStyle: { color: 'rgba(125, 249, 255, .45)', width: 1, type: 'dashed' },
      },
      formatter(params) {
        const rows = params.map((item) => {
          const suffix = item.seriesName === '准确率' ? '%' : ' 次'
          return `${item.marker}${item.seriesName}: <b>${item.value}${suffix}</b>`
        })
        return `<div class="dashboard-chart-tip"><strong>${params[0]?.axisValue || ''}</strong><br/>${rows.join('<br/>')}</div>`
      },
    },
    legend: {
      top: 0,
      right: 0,
      icon: 'roundRect',
      itemWidth: 18,
      itemHeight: 4,
      textStyle: { color: '#a7c7d8', fontSize: 12 },
      data: ['答题量', '准确率'],
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: weekLabels,
      axisLine: { lineStyle: { color: 'rgba(125, 249, 255, .2)' } },
      axisTick: { show: false },
      axisLabel: { color: '#8fb4c9', margin: 16 },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: Math.max(maxTrend.value, 5),
        splitNumber: 4,
        axisLabel: { color: '#6f9bb0' },
        splitLine: { lineStyle: { color: 'rgba(125, 249, 255, .08)' } },
      },
      {
        type: 'value',
        min: 0,
        max: 100,
        splitNumber: 4,
        axisLabel: { color: '#6f9bb0', formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '答题量',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false,
        data: trendValues.value,
        lineStyle: {
          width: 4,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#22e6ff' },
            { offset: 0.45, color: '#7df9ff' },
            { offset: 1, color: '#8b7cff' },
          ]),
          shadowBlur: 18,
          shadowColor: 'rgba(34, 230, 255, .34)',
        },
        itemStyle: { color: '#7df9ff', borderColor: '#061627', borderWidth: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(34, 230, 255, .24)' },
            { offset: 1, color: 'rgba(34, 230, 255, 0)' },
          ]),
        },
      },
      {
        name: '准确率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false,
        data: accuracyValues.value,
        lineStyle: {
          width: 3,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#a2ffd6' },
            { offset: 0.55, color: '#57ffa8' },
            { offset: 1, color: '#ffd166' },
          ]),
          shadowBlur: 16,
          shadowColor: 'rgba(162, 255, 214, .24)',
        },
        itemStyle: { color: '#a2ffd6', borderColor: '#061627', borderWidth: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(162, 255, 214, .18)' },
            { offset: 1, color: 'rgba(162, 255, 214, 0)' },
          ]),
        },
      },
    ],
  }
}

function renderChart() {
  if (!trendChart.value || !data.value) return
  if (!chartInstance) chartInstance = echarts.init(trendChart.value)
  chartInstance.setOption(chartOption(), true)
}

function resizeChart() {
  chartInstance?.resize()
}

async function load() {
  data.value = await api('/dashboard')
  await loadTeams()
  await nextTick()
  renderChart()
}

async function loadTeams() {
  try {
    const teamPayload = await api('/teams')
    teams.value = teamPayload.teams || []
  } catch {
    teams.value = []
  }
}

function openJoinTeam() {
  joinTeamOpen.value = true
  joinTeamCode.value = ''
  joinTeamError.value = ''
  joinTeamNotice.value = ''
}

function closeJoinTeam() {
  if (joiningTeam.value) return
  joinTeamOpen.value = false
}

function normalizeJoinTeamCode() {
  joinTeamCode.value = joinTeamCode.value.replace(/\s+/g, '').toUpperCase()
}

async function submitJoinTeam() {
  normalizeJoinTeamCode()
  if (!joinTeamCode.value) {
    joinTeamError.value = '请输入团队邀请码'
    joinTeamNotice.value = ''
    return
  }

  joiningTeam.value = true
  joinTeamError.value = ''
  joinTeamNotice.value = ''
  try {
    const result = await api('/teams/join', {
      method: 'POST',
      body: { code: joinTeamCode.value },
    })
    await loadTeams()
    joinTeamCode.value = ''
    joinTeamNotice.value = `已加入「${result.team_name}」，当前角色为${teamRoleLabels[result.role] || result.role}`
  } catch (error) {
    joinTeamError.value = error?.message || '加入团队失败，请稍后重试'
  } finally {
    joiningTeam.value = false
  }
}

async function ask() {
  if (!question.value.trim()) return
  asking.value = true
  try {
    const result = await api('/ai/chat', { method: 'POST', body: { question: question.value } })
    answer.value = result.answer
  } finally {
    asking.value = false
  }
}

watch([trendValues, accuracyValues], async () => {
  await nextTick()
  renderChart()
})

onMounted(() => {
  load()
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <AppShell @new="showAsk = true">
    <div v-if="!data" class="page-loader">正在加载工作台...</div>
    <div v-else class="dashboard page-wrap">
      <section class="dashboard-overview" aria-label="控制台核心指标">
        <article v-for="card in stats" :key="card.id" class="console-card metric-card" :class="`tone-${card.tone}`">
          <div class="metric-icon"><component :is="card.icon" /></div>
          <span>{{ card.label }}</span>
          <strong>{{ card.value }} <em>{{ card.unit }}</em></strong>
          <small>{{ card.meta }}</small>
          <i><b :style="{ width: Math.max(4, Math.min(card.progress, 100)) + '%' }"></b></i>
        </article>
      </section>

      <div class="dashboard-grid">
        <main class="dashboard-main">
          <section class="console-card evolution-summary">
            <div class="evo-core">
              <div class="evo-ring"><BrainCircuit /></div>
              <span></span>
            </div>
            <div class="evo-copy">
              <span class="status-pill success">
                <CheckCircle2 /> {{ data.latest_task ? '进化周期已记录' : '进化流程待启动' }}
              </span>
              <h2>{{ data.latest_task ? '最新自动进化周期' : '知识进化就绪' }}</h2>
              <p>{{ data.latest_task?.summary || '尚未执行进化任务。导入素材后可在进化中心启动四阶段 Agent 进化流程。' }}</p>
              <div class="evo-meta">
                <span><b>{{ formatNumber(data.coins) }}</b> 智衍币</span>
                <span><b>{{ formatNumber(data.props) }}</b> 道具库存</span>
                <span><b>{{ data.level }}</b> 当前等级</span>
              </div>
              <div class="inline-actions">
                <button class="button secondary" @click="$router.push('/evolution')">
                  {{ data.latest_task ? '审核变更' : '前往进化' }}
                </button>
                <button class="button outline" @click="$router.push('/materials')">导入素材</button>
              </div>
            </div>
          </section>

          <section class="console-card trend-panel">
            <header class="panel-title">
              <div>
                <span class="eyebrow">Learning Signal</span>
                <h3>学习趋势</h3>
              </div>
              <div class="trend-summary">
                <span><b>{{ trendSummary.total }}</b> 本周答题</span>
                <span><b>{{ trendSummary.avgAccuracy }}%</b> 平均准确率</span>
                <span><b>{{ trendSummary.peak }}</b> 单日峰值</span>
              </div>
            </header>
            <div ref="trendChart" class="trend-chart" role="img" aria-label="学习趋势动态图"></div>
          </section>
        </main>

        <aside class="dashboard-aside">
          <div class="quick-actions">
            <button class="console-card" @click="$router.push('/materials')">
              <Upload /><span>上传素材</span><small>导入知识源</small>
            </button>
            <button class="console-card" @click="$router.push('/evolution')">
              <Zap /><span>启动进化</span><small>Agent 处理</small>
            </button>
          </div>

          <section class="console-card profile-mini">
            <div class="avatar large"><Bot /></div>
            <h3>{{ data.nickname || '用户' }}</h3>
            <p>Lv.{{ data.level }} · {{ data.xp ? data.xp.toLocaleString() + ' XP' : '0 XP' }}</p>
            <hr />
            <small>成就勋章</small>
            <div class="badge-row"><b>✦</b><b>▱</b><b>◈</b><b>♟</b></div>
          </section>

          <section class="console-card recent-panel">
            <header>
              <h3>最近动态</h3>
              <span>{{ latestMaterials.length }} 条</span>
            </header>
            <div class="recent-list">
              <article v-for="item in latestMaterials" :key="item.id">
                <FileText />
                <span>
                  <strong>{{ item.name }}</strong>
                  <small>{{ item.status === 'ready' ? '已处理' : '处理中' }}</small>
                </span>
              </article>
            </div>
            <div v-if="!latestMaterials.length" class="empty-recent">暂无素材，点击上方上传开始。</div>
            <button class="button ghost wide" @click="$router.push('/materials')">查看全部动态</button>
          </section>

          <section class="console-card team-basic-panel">
            <header>
              <div>
                <h3>我的团队</h3>
                <span>{{ teams.length }} 个</span>
              </div>
              <button class="button secondary team-join-button" type="button" @click="openJoinTeam">
                <UserPlus /> 加入团队
              </button>
            </header>
            <article v-for="team in teams.slice(0, 3)" :key="team.id">
              <Building2 />
              <span>
                <strong>{{ team.name }}</strong>
                <small>{{ team.role_label }} · {{ team.counts?.members || 0 }} 名成员 · {{ team.counts?.libraries || 0 }} 个知识库</small>
              </span>
            </article>
            <div v-if="!teams.length" class="empty-recent">暂无已加入团队，可使用团队管理员提供的邀请码加入。</div>
            <p class="team-basic-note">进阶成员、权限、分享、进化审核与统计操作需从登录页选择团队端进入。</p>
          </section>
        </aside>
      </div>

      <button class="ai-fab" title="询问知识库" @click="showAsk = !showAsk"><Bot /></button>
      <section v-if="showAsk" class="ask-panel console-card">
        <header>
          <h3>询问知识库</h3>
          <button class="icon-button" @click="showAsk = false">×</button>
        </header>
        <div v-if="answer" class="answer-box">{{ answer }}</div>
        <form @submit.prevent="ask">
          <input v-model="question" placeholder="输入关于知识库的问题..." />
          <button class="button primary" :disabled="asking">{{ asking ? '思考中' : '提问' }}</button>
        </form>
      </section>
    </div>

    <ModalDialog v-if="joinTeamOpen" title="加入团队" :close-disabled="joiningTeam" @close="closeJoinTeam">
      <form class="stack-form team-join-form" @submit.prevent="submitJoinTeam">
        <div class="team-join-intro">
          <span class="team-join-icon"><KeyRound /></span>
          <div>
            <strong>使用团队邀请码加入</strong>
            <p>邀请码由团队管理员在团队端生成。加入成功后，你可以在个人端查看该团队的基础数据；团队管理与进阶协作仍需从登录页进入团队端。</p>
          </div>
        </div>

        <label>
          团队邀请码
          <div class="team-code-input">
            <KeyRound />
            <input
              v-model="joinTeamCode"
              type="text"
              inputmode="text"
              autocomplete="off"
              maxlength="32"
              placeholder="例如 A1B2C3"
              @input="normalizeJoinTeamCode"
            />
          </div>
        </label>

        <p v-if="joinTeamError" class="form-error">{{ joinTeamError }}</p>
        <p v-if="joinTeamNotice" class="form-notice"><CheckCircle2 /> <strong>{{ joinTeamNotice }}</strong></p>

        <div class="team-join-actions">
          <button class="button ghost" type="button" :disabled="joiningTeam" @click="closeJoinTeam">稍后再说</button>
          <button class="button primary" type="submit" :disabled="joiningTeam || !joinTeamCode.trim()">
            <UserPlus /> {{ joiningTeam ? '加入中...' : '确认加入' }}
          </button>
        </div>
      </form>
    </ModalDialog>
  </AppShell>
</template>

<style scoped>
.dashboard {
  width: min(100%, 1500px);
  padding-top: 42px;
}

.dashboard-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 22px;
}

.console-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(9, 35, 58, .9), rgba(6, 20, 38, .86)),
    radial-gradient(circle at 12% 0%, rgba(125, 249, 255, .14), transparent 34%);
  box-shadow:
    0 18px 46px rgba(0, 0, 0, .2),
    inset 0 1px 0 rgba(255, 255, 255, .06);
}

.console-card::before {
  position: absolute;
  top: 0;
  left: 18px;
  right: 18px;
  height: 1px;
  content: '';
  background: linear-gradient(90deg, transparent, rgba(125, 249, 255, .7), transparent);
}

.metric-card {
  min-height: 172px;
  padding: 22px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 46px;
  grid-template-rows: auto auto auto 1fr auto;
  gap: 8px 14px;
}

.metric-icon {
  grid-column: 2;
  grid-row: 1 / span 2;
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(125, 249, 255, .24);
  border-radius: 8px;
  background: rgba(8, 61, 77, .62);
  color: #7df9ff;
}

.metric-card > span {
  grid-column: 1;
  color: #9ec6da;
  font-size: 13px;
}

.metric-card > strong {
  grid-column: 1;
  color: #f1fbff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: clamp(28px, 2.3vw, 38px);
  font-weight: 700;
  line-height: 1;
}

.metric-card > strong em {
  color: #80a8bd;
  font-family: inherit;
  font-size: 12px;
  font-style: normal;
  font-weight: 500;
}

.metric-card > small {
  grid-column: 1 / -1;
  min-height: 18px;
  overflow: hidden;
  color: #86aabc;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-card > i {
  grid-column: 1 / -1;
  align-self: end;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(124, 179, 201, .14);
}

.metric-card > i b {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #22e6ff, #a2ffd6);
  box-shadow: 0 0 18px rgba(125, 249, 255, .34);
}

.tone-mint .metric-icon,
.tone-mint.metric-card > i b {
  color: #a2ffd6;
  background-color: rgba(18, 82, 67, .62);
}

.tone-blue .metric-icon,
.tone-blue.metric-card > i b {
  color: #9bc7ff;
}

.tone-amber .metric-icon,
.tone-amber.metric-card > i b {
  color: #ffd166;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(330px, .72fr);
  gap: 22px;
  align-items: start;
}

.dashboard-main,
.dashboard-aside {
  display: grid;
  gap: 22px;
}

.evolution-summary {
  min-height: 244px;
  padding: 26px;
  display: grid;
  grid-template-columns: 164px minmax(0, 1fr);
  gap: 28px;
  align-items: center;
}

.evo-core {
  min-width: 0;
  display: grid;
  place-items: center;
}

.evo-ring {
  position: relative;
  width: 132px;
  height: 132px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(125, 249, 255, .34);
  border-radius: 50%;
  background:
    conic-gradient(from 180deg, rgba(34, 230, 255, .18), rgba(162, 255, 214, .95), rgba(139, 124, 255, .42), rgba(34, 230, 255, .18)),
    radial-gradient(circle, rgba(8, 24, 42, .96) 58%, transparent 60%);
  color: #7df9ff;
  animation: pulseRing 2.8s ease-in-out infinite;
}

.evo-ring::after {
  position: absolute;
  inset: 16px;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: inherit;
  content: '';
}

.evo-ring svg {
  width: 42px;
  height: 42px;
  filter: drop-shadow(0 0 18px rgba(125, 249, 255, .52));
}

.evo-copy {
  min-width: 0;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  color: #a2ffd6;
  background: rgba(33, 84, 71, .44);
  border: 1px solid rgba(162, 255, 214, .24);
  font-size: 12px;
}

.evolution-summary h2 {
  margin: 16px 0 10px;
  color: #f3fbff;
  font-size: 26px;
}

.evolution-summary p {
  margin: 0;
  color: #9fbfd0;
  line-height: 1.7;
}

.evo-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.evo-meta span {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid rgba(125, 249, 255, .12);
  border-radius: 6px;
  background: rgba(7, 24, 41, .62);
  color: #7f9fb1;
  font-size: 12px;
}

.evo-meta b {
  display: block;
  margin-bottom: 3px;
  color: #dffbff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 15px;
}

.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
}

.trend-panel {
  min-height: 520px;
  padding: 26px 26px 20px;
}

.panel-title {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 12px;
}

.panel-title h3 {
  margin: 8px 0 0;
  color: #f1fbff;
  font-size: 24px;
}

.trend-summary {
  display: grid;
  grid-template-columns: repeat(3, auto);
  gap: 10px;
}

.trend-summary span {
  min-width: 96px;
  padding: 10px 12px;
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 6px;
  background: rgba(6, 22, 38, .68);
  color: #88a9bb;
  font-size: 11px;
}

.trend-summary b {
  display: block;
  margin-bottom: 4px;
  color: #a2ffd6;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 16px;
}

.trend-chart {
  width: 100%;
  height: 405px;
}

.quick-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.quick-actions button {
  min-height: 126px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  color: #dffbff;
}

.quick-actions button:hover {
  border-color: rgba(125, 249, 255, .42);
  transform: translateY(-1px);
}

.quick-actions svg {
  width: 30px;
  height: 30px;
  color: #7df9ff;
}

.quick-actions span {
  font-weight: 700;
}

.quick-actions small {
  color: #85a7b9;
}

.profile-mini {
  padding: 28px;
  text-align: center;
}

.avatar.large {
  width: 78px;
  height: 78px;
  margin: auto;
  border-color: rgba(125, 249, 255, .42);
  background: rgba(7, 51, 68, .72);
}

.profile-mini h3 {
  margin: 18px 0 4px;
  color: #eefaff;
}

.profile-mini p {
  color: #8fb4c9;
  font-size: 13px;
}

.profile-mini hr {
  margin: 24px 0;
  border: 0;
  border-top: 1px solid rgba(125, 249, 255, .14);
}

.profile-mini > small {
  display: block;
  text-align: left;
  color: #aacbdd;
}

.badge-row {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 18px;
}

.badge-row b {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 8px;
  background: rgba(18, 65, 92, .72);
  color: #7df9ff;
}

.recent-panel {
  padding: 26px;
}

.recent-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.recent-panel h3 {
  margin: 0;
  color: #f1fbff;
  font-size: 22px;
}

.recent-panel header span {
  color: #8fb4c9;
  font-size: 12px;
}

.recent-list {
  display: grid;
  gap: 14px;
}

.recent-list article {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 54px;
}

.recent-list svg {
  width: 44px;
  height: 44px;
  padding: 10px;
  border-radius: 7px;
  background: rgba(0, 121, 126, .5);
  color: #7df9ff;
}

.recent-list strong,
.recent-list small {
  display: block;
}

.recent-list strong {
  overflow: hidden;
  color: #e8f7ff;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-list small {
  margin-top: 4px;
  color: #9ab9c8;
  font-size: 12px;
}

.empty-recent {
  padding: 18px 0;
  color: #89a9ba;
}

.recent-panel .button {
  margin-top: 18px;
}

.team-basic-panel {
  padding: 24px;
}

.team-basic-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 18px;
}

.team-basic-panel header > div {
  min-width: 0;
}

.team-basic-panel h3 {
  margin: 0;
  color: #f1fbff;
  font-size: 22px;
}

.team-basic-panel header > div > span {
  display: block;
  margin-top: 5px;
  color: #7df9ff;
  font-size: 12px;
}

.team-join-button {
  flex: none;
  min-height: 38px;
  padding: 0 12px;
  font-size: 12px;
}

.team-basic-panel header .team-join-button {
  margin-top: 0;
}

.team-join-button svg {
  width: 16px;
}

.team-basic-panel article {
  min-height: 62px;
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  border-top: 1px solid rgba(125, 249, 255, .12);
  padding: 12px 0;
}

.team-basic-panel article > svg {
  color: #a2ffd6;
}

.team-basic-panel strong,
.team-basic-panel small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.team-basic-panel small {
  margin-top: 5px;
  color: #86aabc;
  font-size: 11px;
}

.team-basic-panel .button {
  margin-top: 14px;
}

.team-basic-note {
  margin: 14px 0 0;
  color: #8fb4c9;
  font-size: 12px;
  line-height: 1.6;
}

.team-join-form {
  gap: 16px;
}

.team-join-intro {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  gap: 13px;
  align-items: start;
  padding: 14px;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 8px;
  background: rgba(7, 31, 52, .62);
}

.team-join-icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(125, 249, 255, .26);
  border-radius: 8px;
  background: rgba(8, 69, 84, .64);
  color: #7df9ff;
}

.team-join-intro strong {
  display: block;
  color: #dffbff;
}

.team-join-intro p {
  margin: 6px 0 0;
  color: #91b5c6;
  font-size: 12px;
  line-height: 1.65;
}

.team-code-input {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 50px;
  padding: 0 13px;
  border: 1px solid rgba(125, 249, 255, .22);
  border-radius: 8px;
  background: rgba(32, 93, 129, .28);
  transition: border-color .18s ease, box-shadow .18s ease;
}

.team-code-input:focus-within {
  border-color: #7df9ff;
  box-shadow: 0 0 0 3px rgba(125, 249, 255, .08);
}

.team-code-input svg {
  width: 18px;
  color: #7df9ff;
}

.team-code-input input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: #e6f9ff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 17px;
  letter-spacing: 1px;
}

.team-code-input input::placeholder {
  color: #7196aa;
  font-family: inherit;
  font-size: 13px;
  letter-spacing: 0;
}

.team-join-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 2px;
}

.team-join-actions .button {
  min-width: 124px;
}

.team-join-form .form-error {
  margin: -2px 0 0 !important;
}

.team-join-form .form-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: -2px 0 0 !important;
}

.team-join-form .form-notice svg {
  width: 17px;
  flex: none;
  color: #a2ffd6;
}

.ai-fab {
  position: fixed;
  right: 30px;
  bottom: 86px;
  z-index: 10;
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(125, 249, 255, .34);
  border-radius: 50%;
  background: linear-gradient(135deg, #7df9ff, #a2ffd6);
  color: #061421;
  box-shadow: 0 12px 28px rgba(0, 213, 255, .22);
}

.ask-panel {
  position: fixed;
  right: 28px;
  bottom: 148px;
  z-index: 10;
  width: min(440px, calc(100vw - 32px));
  padding: 22px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, .4);
}

.ask-panel header {
  display: flex;
  justify-content: space-between;
}

.ask-panel form {
  display: flex;
  gap: 8px;
}

.ask-panel input {
  flex: 1;
  min-width: 0;
  padding: 0 12px;
  border: 1px solid rgba(125, 249, 255, .2);
  border-radius: 8px;
  outline: 0;
  background: rgba(5, 14, 25, .9);
  color: var(--text);
}

.answer-box {
  max-height: 190px;
  margin-bottom: 14px;
  padding: 14px;
  overflow: auto;
  border-left: 2px solid #7df9ff;
  background: rgba(7, 26, 43, .78);
  color: #d7ebf3;
  font-size: 13px;
  line-height: 1.6;
}

@keyframes pulseRing {
  0%,
  100% {
    box-shadow: 0 0 0 rgba(125, 249, 255, 0);
  }

  50% {
    box-shadow: 0 0 32px rgba(125, 249, 255, .2);
  }
}

@media (max-width: 1180px) {
  .dashboard-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .dashboard {
    padding-top: 24px;
  }

  .dashboard-overview,
  .evolution-summary,
  .evo-meta,
  .trend-summary,
  .quick-actions {
    grid-template-columns: 1fr;
  }

  .trend-panel {
    min-height: 470px;
  }

  .panel-title {
    display: grid;
  }

  .trend-chart {
    height: 330px;
  }

  .team-basic-panel header {
    align-items: flex-start;
  }

  .team-join-button {
    padding: 0 10px;
  }

  .team-join-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .team-join-actions .button {
    min-width: 0;
  }
}
</style>
