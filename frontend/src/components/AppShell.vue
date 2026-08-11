<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, BrainCircuit, CircleDollarSign, Database, Gamepad2, Grid2X2, Menu, MessageCircleQuestion, Network, Plus, Search, Settings, Star, Trophy, UserRound, UsersRound, X } from 'lucide-vue-next'
import { api, token } from '../api'
import CustomerServiceMascot from './CustomerServiceMascot.vue'
import ShinyText from './ShinyText.vue'

const props = defineProps({
  searchPlaceholder: { type: String, default: '搜索知识...' },
  immersive: { type: Boolean, default: false },
})
const emit = defineEmits(['search', 'new'])
const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const userInfo = ref(null)
const healthStatus = ref(null)
const topbarSummary = ref(null)
const notificationOpen = ref(false)
const coinOpen = ref(false)
const notifications = ref([])
const notificationsLoading = ref(false)
const globalSearch = ref('')
const searchOpen = ref(false)
const searchLoading = ref(false)
const searchError = ref('')
const searchPayload = ref({ total: 0, groups: [] })
let searchTimer = null

const nav = [
  { to: '/my-teams', label: '我的团队', desc: '查看团队基础数据与个人权限操作', icon: UsersRound },
  { to: '/currency', label: '货币中心', desc: '查看个人钱包、额度与收支流水', icon: CircleDollarSign },
  { to: '/dashboard', label: '控制台', desc: '系统数据与学习态势', icon: Grid2X2 },
  { to: '/materials', label: '知识库', desc: '采集、预览与处理素材', icon: Database },
  { to: '/evolution', label: '进化中心', desc: '审计并扩展知识版本', icon: BrainCircuit },
  { to: '/games', label: '游戏中心', desc: '用知识生成挑战', icon: Gamepad2 },
  { to: '/graph', label: '图谱分析', desc: '查看概念关系网络', icon: Network },
  { to: '/customer-service', label: '客服中心', desc: '获取项目操作与规范帮助', icon: MessageCircleQuestion },
  { to: '/settings', label: '系统设置', desc: '配置模型与自动化', icon: Settings },
]
const pageLabels = { '/achievements': '成就中心', '/favorites': '收藏夹', '/profile': '个人中心' }
const activeLabel = computed(() => nav.find((item) => item.to === route.path)?.label || pageLabels[route.path] || '')

async function loadUser() {
  if (!token()) return
  try { userInfo.value = await api('/auth/me') } catch { userInfo.value = null }
}

async function loadHealth() {
  try { healthStatus.value = await api('/health') } catch { healthStatus.value = null }
}

async function loadTopbar() {
  if (!token()) return
  try { topbarSummary.value = await api('/topbar') } catch { topbarSummary.value = null }
}

onMounted(() => { loadUser(); loadHealth(); loadTopbar() })
onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
})

watch(() => props.immersive, (enabled) => {
  if (!enabled) return
  mobileOpen.value = false
  notificationOpen.value = false
  coinOpen.value = false
  searchOpen.value = false
})

function go(to) {
  mobileOpen.value = false
  notificationOpen.value = false
  coinOpen.value = false
  searchOpen.value = false
  router.push(to)
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function toggleNotifications() {
  coinOpen.value = false
  notificationOpen.value = !notificationOpen.value
  if (!notificationOpen.value) return
  notificationsLoading.value = true
  try {
    const data = await api('/notifications')
    notifications.value = data.items || []
    await api('/notifications/read', { method: 'POST' })
    await loadTopbar()
  } finally {
    notificationsLoading.value = false
  }
}

function toggleCoins() {
  notificationOpen.value = false
  searchOpen.value = false
  coinOpen.value = !coinOpen.value
  if (coinOpen.value) loadTopbar()
}

const flatSearchResults = computed(() => searchPayload.value.groups?.flatMap((group) => group.items || []) || [])

function scheduleGlobalSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  const value = globalSearch.value.trim()
  if (value.length < 2) {
    searchPayload.value = { total: 0, groups: [] }
    searchError.value = ''
    searchLoading.value = false
    searchOpen.value = Boolean(value)
    return
  }
  searchOpen.value = true
  searchLoading.value = true
  searchTimer = window.setTimeout(runGlobalSearch, 180)
}

async function runGlobalSearch() {
  const value = globalSearch.value.trim()
  if (value.length < 2) return
  searchError.value = ''
  try {
    searchPayload.value = await api(`/search?q=${encodeURIComponent(value)}&limit=5`)
  } catch (error) {
    searchError.value = error.message
    searchPayload.value = { total: 0, groups: [] }
  } finally {
    searchLoading.value = false
  }
}

function handleSearchInput(event) {
  globalSearch.value = event.target.value
  emit('search', globalSearch.value)
  notificationOpen.value = false
  coinOpen.value = false
  scheduleGlobalSearch()
}

function focusGlobalSearch() {
  if (globalSearch.value.trim()) {
    searchOpen.value = true
    if (!flatSearchResults.value.length) scheduleGlobalSearch()
  }
}

function closeSearchSoon() {
  window.setTimeout(() => { searchOpen.value = false }, 150)
}

function clearGlobalSearch() {
  globalSearch.value = ''
  searchPayload.value = { total: 0, groups: [] }
  searchError.value = ''
  searchOpen.value = false
  emit('search', '')
}

function openSearchResult(item) {
  globalSearch.value = item.title
  emit('search', item.title)
  searchOpen.value = false
  router.push(item.route)
}

function submitGlobalSearch() {
  const value = globalSearch.value.trim()
  if (!value) return
  const first = flatSearchResults.value[0]
  if (first) openSearchResult(first)
  else router.push({ path: '/materials', query: { q: value } })
}

const displayName = computed(() => userInfo.value?.nickname || '用户')
const coinBalance = computed(() => topbarSummary.value?.coins || 0)
const knowledgeBalance = computed(() => topbarSummary.value?.knowledge_balance ?? coinBalance.value)
const truthBalance = computed(() => topbarSummary.value?.truth_balance || 0)
const unreadNotifications = computed(() => topbarSummary.value?.unread_notifications || 0)
const achievementProgress = computed(() => `${topbarSummary.value?.unlocked_achievements || 0}/${topbarSummary.value?.total_achievements || 0}`)
const services = computed(() => {
  if (!healthStatus.value?.services) return []
  const map = { deepseek: 'DeepSeek', database: '数据库', milvus: 'Milvus', redis: 'Redis', sms: '短信', elasticsearch: 'ES' }
  return Object.entries(healthStatus.value.services)
    .filter(([key]) => map[key])
    .map(([key, value]) => ({ name: map[key] || key, status: value }))
})
</script>

<template>
  <div class="app-shell" :class="{ immersive: props.immersive }">
    <div class="tech-backdrop" aria-hidden="true"></div>
    <button v-if="!props.immersive" class="mobile-menu icon-button" aria-label="打开导航" @click="mobileOpen = true"><Menu /></button>

    <aside v-if="!props.immersive" class="floating-module-nav" :class="{ open: mobileOpen }" aria-label="主模块导航">
      <button class="mobile-close icon-button" aria-label="关闭导航" @click="mobileOpen = false"><X /></button>
      <nav class="module-nav">
        <button
          v-for="item in nav"
          :key="item.to"
          class="module-nav-item"
          :class="{ active: route.path === item.to }"
          :aria-label="item.label"
          :title="item.label"
          @click="go(item.to)"
        >
          <component :is="item.icon" :size="21" />
          <span class="module-tooltip"><b>{{ item.label }}</b><small>{{ item.desc }}</small></span>
        </button>
      </nav>
      <button class="module-nav-item dock-new" aria-label="新建知识" title="新建知识" @click="emit('new'); go('/materials')">
        <Plus :size="20" />
        <span class="module-tooltip"><b>新建知识</b><small>打开采集入口并写入素材</small></span>
      </button>
    </aside>

    <div v-if="!props.immersive && mobileOpen" class="nav-backdrop" @click="mobileOpen = false"></div>

    <header v-if="!props.immersive" class="topbar">
      <button class="topbar-brand" @click="go('/dashboard')">
        <img src="/zhiyan_logo/screen.png" alt="知衍标识" />
        <span><strong>知衍</strong><ShinyText text="AI 知识进化工坊" :speed="2.6" color="#7fbfe1" shine-color="#f5fdff" /></span>
      </button>
      <div class="global-search-shell" @focusout="closeSearchSoon">
        <label class="global-search" :class="{ active: searchOpen }">
          <Search :size="20" />
          <input
            :value="globalSearch"
            :placeholder="props.searchPlaceholder"
            @focus="focusGlobalSearch"
            @input="handleSearchInput"
            @keydown.enter.prevent="submitGlobalSearch"
            @keydown.esc.prevent="searchOpen = false"
          />
          <button v-if="globalSearch" type="button" class="search-clear" title="清空搜索" @mousedown.prevent="clearGlobalSearch"><X :size="16" /></button>
        </label>
        <section v-if="searchOpen" class="global-search-panel">
          <header>
            <span>全局检索</span>
            <strong v-if="globalSearch.trim().length >= 2">{{ searchPayload.total || 0 }} 条结果</strong>
            <strong v-else>继续输入关键词</strong>
          </header>
          <div v-if="globalSearch.trim().length < 2" class="search-state">输入至少 2 个字符，检索素材、图谱和进化记录。</div>
          <div v-else-if="searchLoading" class="search-state">正在检索知识库...</div>
          <div v-else-if="searchError" class="search-state error">{{ searchError }}</div>
          <div v-else-if="!flatSearchResults.length" class="search-state">未找到匹配内容，可换一个关键词。</div>
          <template v-else>
            <div v-for="group in searchPayload.groups" :key="group.type" class="search-result-group">
              <span>{{ group.label }}</span>
              <button v-for="item in group.items" :key="item.id" type="button" class="search-result-item" @mousedown.prevent="openSearchResult(item)">
                <b>{{ item.type_label }}</b>
                <span><strong>{{ item.title }}</strong><small>{{ item.subtitle }}</small></span>
                <p>{{ item.excerpt || item.meta }}</p>
              </button>
            </div>
            <button type="button" class="search-all-link" @mousedown.prevent="submitGlobalSearch">打开最相关结果</button>
          </template>
        </section>
      </div>
      <div class="top-actions">
        <button class="icon-button top-action-button" title="通知" @click="toggleNotifications">
          <Bell />
          <span v-if="unreadNotifications" class="top-action-badge">{{ unreadNotifications > 9 ? '9+' : unreadNotifications }}</span>
        </button>
        <button class="icon-button top-action-button" title="成就" @click="go('/achievements')">
          <Trophy />
          <span class="top-action-mini">{{ achievementProgress }}</span>
        </button>
        <button class="icon-button top-action-button" title="收藏" @click="go('/favorites')"><Star /></button>
        <button class="icon-button top-action-button" title="智衍币" @click="toggleCoins"><CircleDollarSign /></button>
        <button class="profile-chip" @click="go('/profile')"><span><strong>{{ displayName }}</strong><small>{{ activeLabel }}</small></span><span class="avatar"><UserRound /></span></button>
        <section v-if="coinOpen" class="top-popover coin-popover">
          <span>个人钱包</span>
          <strong>{{ knowledgeBalance.toLocaleString() }} 学识币</strong>
          <b>{{ truthBalance.toLocaleString() }} 真知晶</b>
          <small>个人钱包与团队公共资金池完全隔离。</small>
          <button class="button compact secondary" type="button" @click="go('/currency')"><CircleDollarSign />查看钱包与流水</button>
        </section>
      </div>
    </header>

    <aside v-if="!props.immersive && notificationOpen" class="notification-drawer" aria-label="通知中心">
      <header>
        <div><span>通知中心</span><strong>{{ notifications.length }} 条消息</strong></div>
        <button class="icon-button" @click="notificationOpen = false"><X /></button>
      </header>
      <div v-if="notificationsLoading" class="notification-empty">正在同步消息...</div>
      <div v-else-if="!notifications.length" class="notification-empty">暂无通知</div>
      <article v-else v-for="item in notifications" :key="item.id" class="notification-item" :class="{ unread: !item.read }">
        <span>{{ item.module }} / {{ item.action }}</span>
        <p>{{ item.detail }}</p>
        <small>{{ formatTime(item.created_at) }}</small>
      </article>
    </aside>

    <main class="app-content"><slot /></main>
    <CustomerServiceMascot v-if="!props.immersive" />
    <footer v-if="!props.immersive" class="status-footer">
      <span>知衍进化系统 v3.7</span>
      <span class="systems" v-if="services.length">
        <b
          v-for="svc in services"
          :key="svc.name"
          :style="{ color: svc.status === 'active' || svc.status === 'configured' || svc.status === 'online' ? 'var(--mint)' : svc.status === 'not_configured' ? 'var(--muted)' : 'var(--amber)' }"
        >{{ svc.name }}: {{ svc.status === 'active' || svc.status === 'online' ? '活跃' : svc.status === 'configured' ? '已配置' : svc.status === 'not_configured' ? '待配' : svc.status }}</b>
      </span>
      <span class="systems" v-else><b>RAGFlow: 联机</b><b>Milvus: 活跃</b><b>RabbitMQ: 稳定</b></span>
    </footer>
  </div>
</template>
