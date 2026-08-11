<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Edit3,
  Expand,
  FileText,
  LoaderCircle,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import ToastMessage from '../components/ToastMessage.vue'
import { api, formatBytes } from '../api'

const router = useRouter()
const data = ref(null)
const loadError = ref('')
const mode = ref('manual')
const running = ref(false)
const modal = ref('')
const selectedIds = ref([])
const startError = ref('')
const activeReview = ref(null)
const reviewText = ref('')
const reviewBusy = ref(false)
const reviewError = ref('')
const rollbackError = ref('')
const rollbackBusy = ref(null)
const rollbackConfirmId = ref(null)
const runResult = ref(null)
const toast = ref('')
const toastType = ref('success')
const maxSelection = 10

const availableMaterials = computed(() => data.value?.materials || [])
const autoEvolutionEnabled = computed(() => Boolean(data.value?.settings?.auto_evolution))
const selectedMaterials = computed(() => availableMaterials.value.filter((item) => selectedIds.value.includes(item.id)))
const selectableIds = computed(() => availableMaterials.value.slice(0, maxSelection).map((item) => item.id))
const allSelected = computed(() => selectableIds.value.length > 0 && selectableIds.value.every((id) => selectedIds.value.includes(id)))
const latestReviews = computed(() => data.value?.latest_reviews || [])
const resultTask = computed(() => runResult.value?.task || data.value?.latest || null)
const resultReviews = computed(() => runResult.value?.reviews || latestReviews.value)
const taskProgress = computed(() => Number(data.value?.latest?.progress || 0))
const reportStats = computed(() => [
  { id: 'target', label: '目标', value: data.value?.latest?.review_count || 0, hint: '指定素材', tone: 'cyan' },
  { id: 'accepted', label: '已应用', value: data.value?.latest?.accepted_count || 0, hint: '写入版本', tone: 'mint' },
  {
    id: 'skipped',
    label: '未应用',
    value: (data.value?.latest?.rejected_count || 0) + (data.value?.latest?.rolled_back_count || 0),
    hint: '拒绝或撤销',
    tone: 'red',
  },
  { id: 'progress', label: '进度', value: `${taskProgress.value}%`, hint: data.value?.latest?.mode === 'auto' ? '自动模式' : '手动模式', tone: 'blue' },
])
const agentRadar = computed(() => [
  { label: '审计', value: data.value?.latest ? 96 : 32 },
  { label: '拓展', value: data.value?.latest?.review_count ? 88 : 28 },
  { label: '编辑', value: data.value?.latest?.accepted_count ? 92 : 24 },
  { label: '质检', value: taskProgress.value || 18 },
])

function timelineState(index) {
  if (!data.value?.latest) return index === 0 ? 'active' : 'idle'
  if (data.value.latest.status === 'failed') return index === 0 ? 'error' : 'idle'
  if (data.value.latest.status === 'completed') return 'done'
  if (data.value.latest.status === 'review') return index < 3 ? 'done' : 'active'
  if (data.value.latest.status === 'processing') return index === 0 ? 'done' : index === 1 ? 'active' : 'idle'
  return 'idle'
}

async function load() {
  loadError.value = ''
  try {
    data.value = await api('/evolution')
    if (data.value?.settings) {
      mode.value = data.value.settings.auto_evolution && data.value.settings.evolution_mode === 'auto' ? 'auto' : 'manual'
    }
  } catch (error) {
    loadError.value = error.message
  }
}

onMounted(load)

function notify(message, type = 'success') {
  toast.value = message
  toastType.value = type
  window.setTimeout(() => { toast.value = '' }, 2800)
}

function openStart() {
  if (data.value.pending.length) {
    openReview(data.value.pending[0])
    notify('请先完成当前待审核建议', 'error')
    return
  }
  selectedIds.value = []
  startError.value = ''
  modal.value = 'select'
}

function openAutoConfirmation() {
  if (!autoEvolutionEnabled.value) {
    mode.value = 'manual'
    notify('系统设置已关闭自动进化，请先在系统设置中开启', 'error')
    return
  }
  if (mode.value === 'auto') return
  toast.value = ''
  modal.value = 'auto-confirm'
}

function confirmAutoMode() {
  if (!autoEvolutionEnabled.value) {
    modal.value = ''
    mode.value = 'manual'
    notify('系统设置已关闭自动进化，请先开启后再选择自动模式', 'error')
    return
  }
  mode.value = 'auto'
  modal.value = ''
  notify('已启用自动模式')
}

function selectManualMode() {
  if (mode.value === 'manual') return
  toast.value = ''
  modal.value = 'manual-confirm'
}

function confirmManualMode() {
  mode.value = 'manual'
  modal.value = ''
  notify('已切换至手动模式')
}

function toggleMaterial(materialId) {
  if (selectedIds.value.includes(materialId)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== materialId)
  } else if (selectedIds.value.length >= maxSelection) {
    startError.value = `单次最多选择 ${maxSelection} 个素材`
  } else {
    selectedIds.value = [...selectedIds.value, materialId]
    startError.value = ''
  }
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : selectableIds.value
  startError.value = availableMaterials.value.length > maxSelection ? `已选择前 ${maxSelection} 个素材` : ''
}

async function startEvolution() {
  if (mode.value === 'auto' && !autoEvolutionEnabled.value) {
    mode.value = 'manual'
    startError.value = '系统设置已关闭自动进化，请先开启后再运行'
    modal.value = 'select'
    return
  }
  if (!selectedIds.value.length) {
    startError.value = '请至少选择一个需要进化的素材'
    return
  }
  startError.value = ''
  running.value = true
  modal.value = 'running'
  try {
    runResult.value = await api('/evolution/start', {
      method: 'POST',
      body: { mode: mode.value, material_ids: selectedIds.value },
    })
    await load()
    if (mode.value === 'manual') {
      const firstReview = data.value.pending.find((item) => item.task_id === runResult.value.task_id)
      if (firstReview) openReview(firstReview)
      else modal.value = 'result'
    } else {
      modal.value = 'result'
      notify('指定素材已完成自动进化')
    }
  } catch (error) {
    startError.value = error.message
    await load()
    modal.value = 'select'
  } finally {
    running.value = false
  }
}

function openReview(item) {
  activeReview.value = item
  reviewText.value = item.proposed_text
  reviewError.value = ''
  modal.value = 'review'
}

async function decide(decision) {
  if (!activeReview.value || reviewBusy.value) return
  if (decision === 'accepted' && !reviewText.value.trim()) {
    reviewError.value = '进化后的正文不能为空'
    return
  }
  reviewBusy.value = true
  reviewError.value = ''
  const taskId = activeReview.value.task_id
  const reviewId = activeReview.value.id
  try {
    await api(`/evolution/reviews/${reviewId}`, {
      method: 'PATCH',
      body: {
        decision,
        proposed_text: decision === 'accepted' ? reviewText.value : undefined,
      },
    })
    await load()
    const nextReview = data.value.pending.find((item) => item.task_id === taskId)
    if (nextReview) {
      openReview(nextReview)
      notify(decision === 'accepted' ? '本条建议已应用，继续审核下一条' : '本条建议已拒绝，继续审核下一条')
    } else {
      activeReview.value = null
      runResult.value = { ...runResult.value, task: data.value.latest, reviews: data.value.latest_reviews }
      modal.value = 'result'
      notify('本次知识进化审核已完成')
    }
  } catch (error) {
    reviewError.value = error.message
  } finally {
    reviewBusy.value = false
  }
}

function formatTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function closeResult() {
  modal.value = ''
  runResult.value = null
  rollbackError.value = ''
  rollbackConfirmId.value = null
}

function goMaterials() {
  closeResult()
  router.push('/materials')
}

function taskStatusLabel(status) {
  return {
    processing: '执行中', review: '待审核', completed: '已完成', failed: '执行失败',
  }[status] || '未开始'
}

async function rollbackAuto(item) {
  if (rollbackBusy.value) return
  if (rollbackConfirmId.value !== item.id) {
    rollbackConfirmId.value = item.id
    rollbackError.value = ''
    return
  }
  rollbackBusy.value = item.id
  rollbackError.value = ''
  try {
    await api(`/evolution/reviews/${item.id}/rollback`, { method: 'POST' })
    await load()
    runResult.value = { ...runResult.value, task: data.value.latest, reviews: data.value.latest_reviews }
    rollbackConfirmId.value = null
    notify(`已撤销「${item.material_name || '该素材'}」的自动进化`)
  } catch (error) {
    rollbackError.value = error.message
  } finally {
    rollbackBusy.value = null
  }
}
</script>

<template>
  <AppShell search-placeholder="搜索知识图谱...">
    <div v-if="!data && !loadError" class="page-loader">正在连接进化代理...</div>
    <div v-else-if="loadError" class="page-loader evolution-load-error">
      <AlertTriangle />
      <span>{{ loadError }}</span>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else class="page-wrap evolution-page">
      <div class="evolution-heading">
        <div class="evolution-heading-copy">
          <span class="evolution-eyebrow">Knowledge Evolution Core</span>
          <h1>进化中心</h1>
          <p>选择知识素材，完成审计、优化与版本确认。</p>
          <div class="evolution-signal-strip">
            <span v-for="item in agentRadar" :key="item.label">
              <b :style="{ width: item.value + '%' }"></b>
              <em>{{ item.label }}</em>
            </span>
          </div>
        </div>
        <div class="evolution-orbit" aria-hidden="true">
          <BrainCircuit />
          <i></i><i></i><i></i>
        </div>
        <div class="evolution-controls">
          <div class="segmented">
            <button :class="{ active: mode === 'manual' }" @click="selectManualMode">手动模式</button>
            <button :class="{ active: mode === 'auto', disabled: !autoEvolutionEnabled }" :disabled="!autoEvolutionEnabled" :title="autoEvolutionEnabled ? '切换到自动模式' : '请先在系统设置中开启自动进化'" @click="openAutoConfirmation">自动模式</button>
          </div>
          <button class="button primary" :disabled="running || !availableMaterials.length" @click="openStart">
            <Play /> 选择文件并进化
          </button>
        </div>
      </div>

      <div class="evolution-grid">
        <section class="panel observer evolution-tech-card">
          <header>
            <h2><span></span>观察窗</h2>
            <div><small><ShieldCheck /> 审计</small><small><Edit3 /> 编辑</small><small><Expand /> 拓展</small></div>
          </header>
          <div class="observer-hud" aria-hidden="true">
            <span>{{ taskProgress }}%</span>
            <i :style="{ width: Math.max(4, taskProgress) + '%' }"></i>
          </div>
          <div class="timeline">
            <article v-for="(item, index) in data.timeline" :key="`${item.agent}-${index}`" :class="timelineState(index)">
              <div class="agent-icon"><component :is="index === 0 ? ShieldCheck : index === 1 ? Edit3 : index === 2 ? Expand : BrainCircuit" /></div>
              <div>
                <span>{{ item.time }}</span>
                <h3>{{ item.agent }}</h3>
                <p>{{ item.text }}</p>
                <code>{{ timelineState(index) === 'done' ? 'phase: validated' : timelineState(index) === 'active' ? 'phase: computing' : 'phase: standby' }}</code>
              </div>
            </article>
          </div>
        </section>

        <aside class="evolution-side">
          <section class="panel report evolution-tech-card">
            <h2><BarChart3 /> 最近任务报告</h2>
            <div class="report-progress-core" :style="{ '--progress': taskProgress * 3.6 + 'deg' }">
              <strong>{{ taskProgress }}%</strong>
              <span>{{ taskStatusLabel(data.latest?.status) }}</span>
            </div>
            <div class="report-grid">
              <div v-for="item in reportStats" :key="item.id" :class="`report-${item.tone}`">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.hint }}</small>
              </div>
            </div>
            <footer>
              <span>任务状态: <b>{{ taskStatusLabel(data.latest?.status) }}</b></span>
              <span>启动时间: <b>{{ formatTime(data.latest?.created_at) }}</b></span>
            </footer>
          </section>

          <section class="panel review-panel evolution-tech-card">
            <header><h2><ClipboardCheck /> 手动审核</h2><span>{{ data.pending.length }} 待处理</span></header>
            <article v-for="item in data.pending" :key="item.id">
              <button class="review-title" @click="openReview(item)">{{ item.material_name || item.title }} <ChevronRight /></button>
              <p>{{ item.proposed_text.slice(0, 120) }}</p>
              <small>{{ item.reason }}</small>
              <button class="review-open" @click="openReview(item)"><ClipboardCheck /> 预览并确认</button>
            </article>
            <div v-if="!data.pending.length" class="review-empty"><Sparkles /> 当前没有待审核建议</div>
          </section>
        </aside>
      </div>
    </div>

    <ModalDialog v-if="modal === 'manual-confirm'" title="切换至手动模式" @close="modal = ''">
      <section class="evolution-auto-confirm evolution-manual-confirm">
        <div class="evolution-auto-confirm-heading">
          <ClipboardCheck />
          <div><h3>确认改为逐条人工审核</h3><p>手动模式不会直接覆盖知识库，请确认以下执行规则。</p></div>
        </div>
        <ol>
          <li><span>1</span><div><strong>Agent 只生成进化建议</strong><small>完成知识分析、补充和润色后，结果会进入待审核列表。</small></div></li>
          <li><span>2</span><div><strong>逐个预览并允许编辑</strong><small>可对照原文检查进化版本，也可在确认前修改最终正文。</small></div></li>
          <li><span>3</span><div><strong>确认后才写回知识库</strong><small>接受的内容会更新素材并保存版本；拒绝则完整保留原文。</small></div></li>
          <li><span>4</span><div><strong>需处理完当前审核任务</strong><small>存在待审核建议时不能启动下一次进化，避免版本状态混乱。</small></div></li>
        </ol>
        <div class="evolution-auto-confirm-note manual"><ShieldCheck /> 切换模式不会影响已经完成或正在等待审核的历史任务。</div>
        <div class="url-actions">
          <button class="button ghost" @click="modal = ''">取消</button>
          <button class="button primary" @click="confirmManualMode"><Check /> 确认切换至手动模式</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'auto-confirm'" title="启用自动模式" @close="modal = ''">
      <section class="evolution-auto-confirm">
        <div class="evolution-auto-confirm-heading">
          <ShieldCheck />
          <div><h3>确认由系统自动应用进化结果</h3><p>自动模式无需逐条人工审核，请确认以下执行规则。</p></div>
        </div>
        <ol>
          <li><span>1</span><div><strong>质量审核通过才可应用</strong><small>文档必须满足知识点覆盖、补充幅度、结构和相似度检查。</small></div></li>
          <li><span>2</span><div><strong>整批成功或整批不变</strong><small>所选素材全部成功后统一写回；任一素材失败都不会修改原知识。</small></div></li>
          <li><span>3</span><div><strong>自动覆盖并保留版本</strong><small>通过审核的内容会直接更新知识库，同时保存进化前后的版本记录。</small></div></li>
          <li><span>4</span><div><strong>可撤销且不覆盖新修改</strong><small>完成后可逐个撤销；素材已有后续修改时，系统将阻止旧版本覆盖新内容。</small></div></li>
        </ol>
        <div class="evolution-auto-confirm-note"><AlertTriangle /> Agent 服务异常或质量不达标时，任务会标记失败，原素材保持不变。</div>
        <div class="url-actions">
          <button class="button ghost" @click="modal = ''">取消</button>
          <button class="button primary" @click="confirmAutoMode"><Check /> 确认启用自动模式</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'select'" title="选择进化素材" wide @close="modal = ''">
      <div class="evolution-selector-toolbar">
        <span>已选择 <strong>{{ selectedIds.length }}</strong> / 最多 {{ maxSelection }}</span>
        <button type="button" @click="toggleAll">{{ allSelected ? '取消全选' : '选择全部' }}</button>
      </div>
      <div class="evolution-material-list">
        <label v-for="material in availableMaterials" :key="material.id" :class="{ selected: selectedIds.includes(material.id) }">
          <input type="checkbox" :checked="selectedIds.includes(material.id)" @change="toggleMaterial(material.id)" />
          <FileText />
          <span>
            <strong>{{ material.name }}</strong>
            <small>{{ material.kind }} · {{ material.category }} · {{ formatBytes(material.size) }}</small>
            <em>{{ material.content.slice(0, 110) }}</em>
          </span>
        </label>
        <div v-if="!availableMaterials.length" class="review-empty"><FileText /> 暂无可进化的已就绪素材</div>
      </div>
      <div v-if="mode === 'auto'" class="evolution-auto-notice">
        <ShieldCheck />
        <span><strong>自动应用已开启</strong><small>全部素材通过质量审核后才会统一写回；任一素材失败则整批不更新。完成后可逐个撤销。</small></span>
      </div>
      <p v-if="startError" class="evolution-inline-error" role="alert">{{ startError }}</p>
      <div class="url-actions">
        <button class="button ghost" @click="modal = ''">取消</button>
        <button class="button primary" :disabled="!selectedIds.length" @click="startEvolution">
          <Sparkles /> {{ mode === 'auto' ? '确认并自动应用' : '生成进化建议' }}
        </button>
      </div>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'running'" title="正在执行知识进化" wide close-disabled>
      <section class="url-fetch-state" aria-live="polite">
        <LoaderCircle class="url-spinner" />
        <div><h3>Agent 正在提炼并扩展知识</h3><p>{{ selectedMaterials.map((item) => item.name).join('、') }}</p></div>
        <div class="url-fetch-progress">
          <span class="done"><Check /> 扫描正文并提取主要知识点</span>
          <span class="active"><LoaderCircle /> 补充知识并重构完整文档</span>
          <span><BrainCircuit /> 执行质量审核与相似度检查</span>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'review' && activeReview" :title="activeReview.material_name || activeReview.title" wide :close-disabled="reviewBusy" @close="modal = ''">
      <div class="evolution-review-source">
        <FileText />
        <span><strong>{{ activeReview.material_kind || '文本' }}</strong><small>{{ activeReview.material_category || '未分类' }}</small></span>
        <b>待确认</b>
      </div>
      <p class="evolution-review-reason"><ShieldCheck /> {{ activeReview.reason }}</p>
      <div class="evolution-diff-grid">
        <section>
          <header><span>当前版本</span><small>{{ activeReview.original_text.length.toLocaleString() }} 字符</small></header>
          <pre>{{ activeReview.original_text }}</pre>
        </section>
        <section>
          <header><span>进化版本</span><small>{{ reviewText.length.toLocaleString() }} 字符</small></header>
          <textarea v-model="reviewText" :disabled="reviewBusy" maxlength="100000" spellcheck="false"></textarea>
        </section>
      </div>
      <p v-if="reviewError" class="evolution-inline-error" role="alert">{{ reviewError }}</p>
      <div class="url-actions">
        <button class="button ghost" :disabled="reviewBusy" @click="decide('rejected')"><X /> 拒绝并保留原文</button>
        <button class="button primary" :disabled="reviewBusy || !reviewText.trim()" @click="decide('accepted')">
          <LoaderCircle v-if="reviewBusy" class="button-spinner" /><Check v-else /> 确认应用
        </button>
      </div>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'result'" :title="resultTask?.mode === 'auto' ? '自动进化已完成' : '知识进化已完成'" @close="closeResult">
      <section class="evolution-result">
        <CheckCircle2 />
        <h3>{{ resultTask?.mode === 'auto' ? '进化结果已自动写入知识库' : '指定素材已完成处理' }}</h3>
        <p>{{ resultTask?.summary }}</p>
        <div>
          <span><strong>{{ resultTask?.accepted_count || 0 }}</strong><small>{{ resultTask?.mode === 'auto' ? '自动应用' : '已应用' }}</small></span>
          <span><strong>{{ (resultTask?.rejected_count || 0) + (resultTask?.rolled_back_count || 0) }}</strong><small>保留原文</small></span>
        </div>
        <ul>
          <li v-for="item in resultReviews" :key="item.id">
            <span class="evolution-result-material">
              <strong>{{ item.material_name || `建议 #${item.id}` }}</strong>
              <small>{{ item.version ? `版本 v${item.version}` : '未生成版本' }} · {{ item.original_chars || item.original_text?.length || 0 }} → {{ item.proposed_chars || item.proposed_text?.length || 0 }} 字符</small>
            </span>
            <b :class="item.decision">{{ item.decision === 'accepted' ? '已更新' : item.decision === 'rolled_back' ? '已撤销' : item.decision === 'rejected' ? '已保留' : '待审核' }}</b>
            <button
              v-if="resultTask?.mode === 'auto' && item.decision === 'accepted'"
              class="evolution-rollback"
              :class="{ confirming: rollbackConfirmId === item.id }"
              :disabled="rollbackBusy !== null"
              @click="rollbackAuto(item)"
            >
              <LoaderCircle v-if="rollbackBusy === item.id" class="button-spinner" />
              <RotateCcw v-else />
              {{ rollbackConfirmId === item.id ? '确认撤销' : '撤销' }}
            </button>
          </li>
        </ul>
        <p v-if="rollbackError" class="evolution-inline-error" role="alert">{{ rollbackError }}</p>
        <div class="url-actions">
          <button class="button ghost" @click="closeResult">关闭</button>
          <button class="button primary" @click="goMaterials"><FileText /> 查看知识库</button>
        </div>
      </section>
    </ModalDialog>

    <ToastMessage :message="toast" :type="toastType" />
  </AppShell>
</template>

<style scoped>
.evolution-page {
  position: relative;
  width: min(100%, 1520px);
  padding-top: 48px;
}

.evolution-page::before {
  position: absolute;
  inset: 18px 38px auto;
  height: 310px;
  pointer-events: none;
  content: '';
  background:
    linear-gradient(90deg, rgba(125, 249, 255, .12) 1px, transparent 1px),
    linear-gradient(180deg, rgba(125, 249, 255, .08) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, .72), transparent);
}

.evolution-heading {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px auto;
  gap: 28px;
  align-items: center;
  min-height: 216px;
  margin-bottom: 26px;
  padding: 30px;
  overflow: hidden;
  border: 1px solid rgba(125, 249, 255, .2);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(7, 28, 51, .92), rgba(4, 15, 31, .86)),
    radial-gradient(circle at 80% 20%, rgba(125, 249, 255, .16), transparent 30%);
  box-shadow: 0 24px 60px rgba(0, 0, 0, .24), inset 0 1px 0 rgba(255, 255, 255, .06);
}

.evolution-heading::after {
  position: absolute;
  right: 28px;
  bottom: 22px;
  left: 28px;
  height: 1px;
  content: '';
  background: linear-gradient(90deg, transparent, rgba(125, 249, 255, .56), rgba(162, 255, 214, .34), transparent);
}

.evolution-heading-copy {
  position: relative;
  z-index: 1;
}

.evolution-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #7df9ff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 12px;
  letter-spacing: 0;
}

.evolution-eyebrow::before {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  content: '';
  background: #a2ffd6;
  box-shadow: 0 0 16px rgba(162, 255, 214, .72);
}

.evolution-heading h1 {
  margin: 12px 0 8px;
  color: #f2fbff;
  font-size: clamp(42px, 4vw, 62px);
  line-height: 1.06;
  text-shadow: 0 0 24px rgba(125, 249, 255, .18);
}

.evolution-heading p {
  max-width: 680px;
  margin: 0;
  color: #93b7ca;
  font-size: 17px;
}

.evolution-signal-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  max-width: 620px;
  margin-top: 24px;
}

.evolution-signal-strip span {
  position: relative;
  height: 32px;
  overflow: hidden;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 6px;
  background: rgba(6, 24, 42, .72);
}

.evolution-signal-strip b {
  position: absolute;
  inset: 0 auto 0 0;
  display: block;
  background: linear-gradient(90deg, rgba(34, 230, 255, .72), rgba(162, 255, 214, .52));
  opacity: .68;
}

.evolution-signal-strip em {
  position: relative;
  z-index: 1;
  display: grid;
  height: 100%;
  place-items: center;
  color: #dffbff;
  font-size: 12px;
  font-style: normal;
}

.evolution-orbit {
  position: relative;
  z-index: 1;
  width: 152px;
  height: 152px;
  display: grid;
  place-items: center;
  justify-self: center;
  border: 1px solid rgba(125, 249, 255, .32);
  border-radius: 50%;
  background:
    radial-gradient(circle, rgba(9, 34, 58, .94) 0 48%, transparent 49%),
    conic-gradient(from 210deg, rgba(125, 249, 255, .12), rgba(162, 255, 214, .9), rgba(139, 124, 255, .52), rgba(125, 249, 255, .12));
  box-shadow: inset 0 0 28px rgba(125, 249, 255, .16), 0 0 38px rgba(0, 213, 255, .12);
}

.evolution-orbit svg {
  width: 48px;
  height: 48px;
  color: #7df9ff;
  filter: drop-shadow(0 0 18px rgba(125, 249, 255, .55));
}

.evolution-orbit i {
  position: absolute;
  inset: 15px;
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 50%;
  animation: evolutionSpin 8s linear infinite;
}

.evolution-orbit i:nth-of-type(2) {
  inset: 33px;
  animation-duration: 5.5s;
  animation-direction: reverse;
}

.evolution-orbit i:nth-of-type(3) {
  inset: -10px;
  border-style: dashed;
  animation-duration: 12s;
}

.evolution-controls {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 14px;
  justify-items: stretch;
}

.evolution-controls .button {
  min-width: 232px;
  min-height: 54px;
  border-radius: 7px;
  box-shadow: 0 12px 28px rgba(0, 213, 255, .18);
}

.segmented {
  min-height: 54px;
  padding: 5px;
  border-color: rgba(125, 249, 255, .26);
  border-radius: 8px;
  background: rgba(4, 15, 28, .74);
}

.segmented button {
  min-width: 128px;
  color: #8fb4c9;
  transition: background .16s ease, color .16s ease, box-shadow .16s ease;
}

.segmented button.active {
  background: linear-gradient(135deg, #7df9ff, #a2ffd6);
  box-shadow: 0 0 22px rgba(125, 249, 255, .22);
}

.evolution-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(350px, .86fr);
  gap: 26px;
}

.evolution-tech-card {
  position: relative;
  overflow: hidden;
  border-color: rgba(125, 249, 255, .18) !important;
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(8, 31, 54, .92), rgba(5, 18, 35, .9)),
    radial-gradient(circle at 20% 0%, rgba(125, 249, 255, .14), transparent 32%) !important;
  box-shadow: 0 20px 52px rgba(0, 0, 0, .22), inset 0 1px 0 rgba(255, 255, 255, .055);
}

.evolution-tech-card::before {
  position: absolute;
  top: 0;
  right: 22px;
  left: 22px;
  height: 1px;
  content: '';
  background: linear-gradient(90deg, transparent, rgba(125, 249, 255, .66), transparent);
}

.observer {
  min-height: 760px;
  padding: 34px 38px;
}

.observer > header {
  position: relative;
  z-index: 1;
}

.observer > header h2 {
  color: #f1fbff;
  font-size: 28px;
}

.observer > header h2 span {
  box-shadow: 0 0 18px rgba(125, 249, 255, .8);
}

.observer > header small {
  color: #7df9ff;
  text-shadow: 0 0 12px rgba(125, 249, 255, .24);
}

.observer-hud {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  margin: 28px 0 6px;
  padding: 12px 14px;
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 6px;
  background: rgba(5, 20, 36, .72);
}

.observer-hud span {
  color: #a2ffd6;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-weight: 700;
}

.observer-hud i {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: linear-gradient(90deg, #22e6ff, #a2ffd6, #8b7cff);
  box-shadow: 0 0 18px rgba(125, 249, 255, .28);
}

.timeline {
  position: relative;
  z-index: 1;
  margin-top: 26px;
}

.timeline::before {
  position: absolute;
  top: -4px;
  bottom: 0;
  left: 21px;
  width: 1px;
  content: '';
  background: linear-gradient(180deg, rgba(125, 249, 255, .72), rgba(162, 255, 214, .2), transparent);
}

.timeline article {
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 24px;
  min-height: 142px;
}

.timeline article:not(:last-child)::before {
  display: none;
}

.agent-icon {
  position: relative;
  z-index: 1;
  width: 52px;
  height: 52px;
  border-color: rgba(125, 249, 255, .42);
  background: rgba(8, 57, 76, .82);
  box-shadow: 0 0 24px rgba(0, 213, 255, .18), inset 0 0 18px rgba(125, 249, 255, .12);
}

.timeline article.done .agent-icon {
  background: linear-gradient(135deg, rgba(125, 249, 255, .9), rgba(162, 255, 214, .78));
  color: #061421;
}

.timeline article.active .agent-icon {
  animation: agentPulse 1.8s ease-in-out infinite;
}

.timeline article.error .agent-icon {
  border-color: rgba(245, 108, 108, .55);
  color: #ff9d9d;
  background: rgba(80, 24, 34, .7);
}

.timeline article > div:last-child {
  min-width: 0;
  padding: 4px 0 20px;
}

.timeline article > div:last-child > span {
  color: #668ea2;
}

.timeline h3 {
  color: #7df9ff;
  font-size: 22px;
  text-shadow: 0 0 14px rgba(125, 249, 255, .18);
}

.timeline p {
  max-width: 760px;
  color: #98b9ca;
}

.timeline code {
  width: max-content;
  margin-top: 14px;
  padding: 8px 11px;
  border-color: rgba(125, 249, 255, .16);
  border-radius: 5px;
  background: rgba(4, 18, 31, .78);
  color: #a2ffd6;
  font-size: 11px;
}

.evolution-side {
  gap: 26px;
}

.report {
  padding: 28px 30px;
}

.report h2,
.review-panel h2 {
  color: #f1fbff;
  font-size: 24px;
}

.report h2 svg,
.review-panel h2 svg {
  color: #7df9ff;
}

.report-progress-core {
  --progress: 0deg;
  width: 150px;
  height: 150px;
  margin: 20px auto 24px;
  display: grid;
  place-items: center;
  align-content: center;
  border-radius: 50%;
  background:
    radial-gradient(circle, rgba(7, 24, 43, .95) 0 54%, transparent 55%),
    conic-gradient(#7df9ff var(--progress), rgba(125, 249, 255, .12) 0);
  box-shadow: inset 0 0 28px rgba(125, 249, 255, .1), 0 0 30px rgba(0, 213, 255, .12);
}

.report-progress-core strong,
.report-progress-core span {
  grid-column: 1;
}

.report-progress-core strong {
  color: #eaffff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 32px;
}

.report-progress-core span {
  color: #8fb4c9;
  font-size: 12px;
}

.report-grid {
  gap: 14px;
}

.report-grid > div {
  position: relative;
  overflow: hidden;
  border-color: rgba(125, 249, 255, .15);
  background: rgba(7, 25, 43, .68);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04);
}

.report-grid > div::after {
  position: absolute;
  inset: auto 0 0;
  height: 2px;
  content: '';
  background: linear-gradient(90deg, rgba(125, 249, 255, .7), transparent);
}

.report-grid strong {
  color: #7df9ff;
  font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
  font-size: 32px;
}

.report-grid .report-mint strong {
  color: #a2ffd6;
}

.report-grid .report-red strong {
  color: #ff9d9d;
}

.report-grid .report-blue strong {
  color: #9bc7ff;
}

.report footer {
  border-top-color: rgba(125, 249, 255, .14);
}

.report footer b {
  color: #dffbff;
}

.review-panel {
  padding: 26px;
}

.review-panel > header > span {
  border: 1px solid rgba(230, 162, 60, .26);
  background: rgba(83, 61, 30, .44);
}

.review-panel article {
  border-color: rgba(125, 249, 255, .14);
  background: rgba(7, 25, 43, .66);
}

.review-title {
  color: #e8f7ff;
}

.review-title svg {
  color: #7df9ff;
}

.review-panel article p {
  color: #9fbfd0;
}

.review-open {
  margin-top: 14px;
  border: 1px solid rgba(125, 249, 255, .2);
  border-radius: 6px;
  background: rgba(5, 28, 43, .86);
  color: #7df9ff;
}

.review-empty {
  color: #8fb4c9;
}

@keyframes evolutionSpin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes agentPulse {
  0%,
  100% {
    box-shadow: 0 0 20px rgba(125, 249, 255, .18);
  }

  50% {
    box-shadow: 0 0 34px rgba(125, 249, 255, .42);
  }
}

@media (max-width: 1180px) {
  .evolution-heading {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .evolution-orbit {
    display: none;
  }

  .evolution-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .evolution-heading,
  .evolution-controls,
  .evolution-signal-strip,
  .report-grid {
    grid-template-columns: 1fr;
  }

  .evolution-heading {
    padding: 24px;
  }

  .observer {
    min-height: auto;
    padding: 24px;
  }

  .observer > header {
    display: grid;
    gap: 14px;
  }

  .timeline article {
    grid-template-columns: 44px minmax(0, 1fr);
    gap: 16px;
  }

  .agent-icon {
    width: 44px;
    height: 44px;
  }
}
</style>
