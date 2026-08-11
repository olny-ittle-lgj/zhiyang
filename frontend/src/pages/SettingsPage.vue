<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Gamepad2,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ToastMessage from '../components/ToastMessage.vue'
import { api } from '../api'

const settings = ref(null)
const loading = ref(true)
const saving = ref(false)
const refreshing = ref(false)
const error = ref('')
const toast = ref('')
const health = ref(null)

const schedulePercent = computed(() => {
  const [hour = 0, minute = 0] = String(settings.value?.trigger_time || '00:00').split(':').map(Number)
  return Math.max(0, Math.min(100, ((hour * 60 + minute) / 1440) * 100))
})

function notify(message) {
  toast.value = message
  window.setTimeout(() => { toast.value = '' }, 2800)
}

async function loadHealth() {
  refreshing.value = true
  try {
    health.value = await api('/health')
  } catch (err) {
    health.value = null
    notify(err.message || '系统状态读取失败')
  } finally {
    refreshing.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await api('/settings')
    await loadHealth()
  } catch (err) {
    error.value = err.message || '设置读取失败'
  } finally {
    loading.value = false
  }
}

function ensureManualMode() {
  if (settings.value && !settings.value.auto_evolution && settings.value.evolution_mode === 'auto') {
    settings.value.evolution_mode = 'manual'
    notify('关闭自动进化后已切回手动模式')
  }
}

function chooseEvolutionMode(mode) {
  if (mode === 'auto' && !settings.value.auto_evolution) {
    notify('请先开启自动进化，再选择自动模式')
    return
  }
  settings.value.evolution_mode = mode
}

async function save() {
  if (!settings.value || saving.value) return
  saving.value = true
  try {
    settings.value = await api('/settings', { method: 'PUT', body: settings.value })
    notify('设置已保存并立即生效')
  } catch (err) {
    notify(err.message || '设置保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell search-placeholder="搜索系统设置...">
    <div v-if="loading" class="page-loader">读取设置...</div>
    <div v-else-if="error" class="page-wrap settings-page">
      <div class="graph-state error-state"><strong>{{ error }}</strong><button class="button secondary" @click="load">重新加载</button></div>
    </div>
    <div v-else-if="settings" class="page-wrap settings-page">
      <div class="page-heading"><h1>系统设置</h1><p>统一管理知识进化、游戏难度和运行环境。保存后设置会立即应用到对应功能。</p></div>
      <div class="settings-grid">
        <main>
          <section class="panel settings-card">
            <h2><BrainCircuit /> 知识进化</h2>
            <label class="setting-row"><span><strong>自动进化</strong><small>允许系统按计划运行自动进化；关闭后只能手动启动。</small></span><input v-model="settings.auto_evolution" type="checkbox" class="toggle" @change="ensureManualMode" /></label>
            <label class="schedule"><span><strong>触发时间</strong><small>自动进化每天使用该时间作为执行计划。</small></span><input v-model="settings.trigger_time" type="time" /><i><b :style="{ width: `${schedulePercent}%` }"></b></i><em><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></em></label>
            <div class="mode-cards"><button :class="{ active: settings.evolution_mode === 'manual' }" @click="chooseEvolutionMode('manual')"><SlidersHorizontal /><strong>手动确认</strong><small>生成建议后逐条预览、确认和写回。</small></button><button :class="{ active: settings.evolution_mode === 'auto', disabled: !settings.auto_evolution }" :disabled="!settings.auto_evolution" @click="chooseEvolutionMode('auto')"><BrainCircuit /><strong>自动执行</strong><small>质量审核通过后自动写回知识库。</small></button></div>
          </section>

          <section class="panel settings-card">
            <h2><Gamepad2 /> 游戏偏好</h2>
            <label class="select-setting"><span>知识大富翁难度</span><select v-model="settings.monopoly_difficulty"><option value="easy">简单 · 入门规则</option><option value="medium">中等 · 推荐</option><option value="hard">困难 · 高强度</option></select></label>
            <label class="select-setting"><span>知识闪卡难度</span><select v-model="settings.flashcard_difficulty"><option value="easy">简单 · 4×4 / 8 对</option><option value="hard">困难 · 6×6 / 18 对</option></select></label>
            <label class="select-setting"><span>智识对弈难度</span><select v-model="settings.matching_difficulty"><option value="easy">简单 · 宽松匹配</option><option value="medium">中等 · 标准匹配</option><option value="hard">困难 · 严格匹配</option></select></label>
            <label class="setting-row inset"><span><strong>游戏化复习</strong><small>允许游戏中心使用知识库素材生成复习题包。</small></span><input v-model="settings.gamified_review" type="checkbox" class="toggle mint" /></label>
          </section>

          <section class="panel settings-card settings-info-card">
            <h2><Settings2 /> 当前配置</h2>
            <div class="settings-info-grid"><span>进化模式<strong>{{ settings.evolution_mode === 'auto' ? '自动执行' : '手动确认' }}</strong></span><span>计划时间<strong>{{ settings.trigger_time }}</strong></span><span>自动进化<strong>{{ settings.auto_evolution ? '已开启' : '已关闭' }}</strong></span><span>游戏化复习<strong>{{ settings.gamified_review ? '已开启' : '已关闭' }}</strong></span></div>
          </section>
          <button class="button primary save-settings" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存全部设置' }}</button>
        </main>

        <aside>
          <section class="panel system-card">
            <header><div><small>系统状态</small><strong>v{{ health?.version || '-' }} {{ health?.status === 'ok' ? '正常运行' : '需要检查' }}</strong></div><Radio /></header>
            <p><span>DeepSeek AI</span><b>{{ health?.services?.deepseek === 'configured' ? '已配置' : '未配置' }}</b></p><p><span>数据库</span><b>{{ health?.services?.database === 'active' ? '运行中' : '异常' }}</b></p><p><span>Milvus 向量库</span><b>{{ health?.services?.milvus === 'active' || health?.services?.milvus === 'configured' ? '运行中' : '待配置' }}</b></p><p><span>Redis 缓存</span><b>{{ health?.services?.redis === 'active' || health?.services?.redis === 'configured' ? '运行中' : '未启用' }}</b></p>
            <button class="button outline wide" :disabled="refreshing" @click="loadHealth"><RefreshCw :class="{ spinning: refreshing }" /> {{ refreshing ? '检查中...' : '刷新状态' }}</button>
          </section>
          <section class="panel security-card"><h2><ShieldCheck /> 账户与数据</h2><div class="settings-account-note"><CheckCircle2 /><span><strong>个人设置隔离</strong><small>当前设置仅作用于当前账户，不会影响其他用户。</small></span></div><div class="settings-account-note"><Clock3 /><span><strong>保存策略</strong><small>每次保存都会写入系统日志，便于追踪配置变更。</small></span></div></section>
          <section class="settings-notice"><AlertTriangle /><span>关闭自动进化不会删除已有素材或版本，只会阻止自动模式启动。</span></section>
        </aside>
      </div>
      <ToastMessage :message="toast" />
    </div>
  </AppShell>
</template>
