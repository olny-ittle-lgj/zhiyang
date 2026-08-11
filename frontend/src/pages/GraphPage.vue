<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { Download, FileText, Filter, Focus, Layers3, Minus, Network, Plus, RefreshCw, Search, Sparkles, X } from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { api } from '../api'

const chartEl = ref(null)
const graph = ref(null)
const selected = ref(null)
const selectedDetail = ref(null)
const category = ref('')
const query = ref('')
const viewMode = ref('knowledge3d')
const pathMode = ref(false)
const loading = ref(true)
const rebuilding = ref(false)
const materials = ref([])
const materialPickerOpen = ref(false)
const materialQuery = ref('')
const selectedMaterialIds = ref([])
const nodeTarget = ref(80)
const graphZoom = ref(1)
const graphTilt = ref({ x: -16, y: 24 })
const revealReview = ref(false)
const reviewFeedback = ref('')
const error = ref('')
const notice = ref('')
const rebuildStage = ref(0)
let chart
let noticeTimer
let rebuildTimer
const nodeTargetOptions = [30, 60, 100, 160, 240]
const palette = ['#00eaff', '#69ffcb', '#8fcaff', '#ffd27a', '#ff9bd4', '#b7a6ff']
const rebuildStages = ['读取素材', '提取核心词', '建立关系', '整理布局']

const visibleNodes = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return (graph.value?.nodes || []).filter((node) => {
    const categoryMatch = !category.value || node.category === category.value
    const queryMatch = !needle || [node.label, node.summary, node.source_material_name].some((value) => String(value || '').toLowerCase().includes(needle))
    return categoryMatch && queryMatch
  })
})

const visibleIds = computed(() => new Set(visibleNodes.value.map((node) => String(node.id))))
const visibleEdges = computed(() => (graph.value?.edges || []).filter((edge) => visibleIds.value.has(String(edge.source)) && visibleIds.value.has(String(edge.target))))
const readyMaterials = computed(() => materials.value.filter((item) => item.status === 'ready' && String(item.content || '').trim()))
const filteredMaterials = computed(() => {
  const needle = materialQuery.value.trim().toLowerCase()
  if (!needle) return readyMaterials.value
  return readyMaterials.value.filter((item) => [item.name, item.category, item.kind].some((value) => String(value || '').toLowerCase().includes(needle)))
})
const selectedNeighbors = computed(() => {
  if (!selected.value || !pathMode.value) return new Set()
  const ids = new Set([String(selected.value.id)])
  visibleEdges.value.forEach((edge) => {
    if (String(edge.source) === String(selected.value.id)) ids.add(String(edge.target))
    if (String(edge.target) === String(selected.value.id)) ids.add(String(edge.source))
  })
  return ids
})
const graphModel = computed(() => {
  const nodes = visibleNodes.value
  const edges = visibleEdges.value
  const categories = graph.value?.categories?.length ? graph.value.categories : [...new Set(nodes.map((node) => node.category || '未分类'))]
  const categoryColors = new Map(categories.map((item, index) => [item, palette[index % palette.length]]))
  const categoryGroups = new Map(categories.map((item) => [item, []]))
  const degree = new Map(nodes.map((node) => [String(node.id), 0]))
  edges.forEach((edge) => {
    degree.set(String(edge.source), (degree.get(String(edge.source)) || 0) + 1)
    degree.set(String(edge.target), (degree.get(String(edge.target)) || 0) + 1)
  })
  nodes.forEach((node) => {
    const key = node.category || '未分类'
    if (!categoryGroups.has(key)) categoryGroups.set(key, [])
    categoryGroups.get(key).push(node)
  })

  const layoutNodes = []
  const categoryCount = Math.max(1, categoryGroups.size)
  Array.from(categoryGroups.entries()).forEach(([categoryName, group], categoryIndex) => {
    const ordered = [...group].sort((left, right) => (degree.get(String(right.id)) || 0) - (degree.get(String(left.id)) || 0))
    const laneOffset = categoryCount === 1 ? 0 : (categoryIndex - (categoryCount - 1) / 2) * Math.min(18, 62 / categoryCount)
    ordered.forEach((node, index) => {
      const mastery = Number(node.mastery || 0)
      const tier = mastery >= 80 ? 2 : mastery >= 50 ? 1 : 0
      const angle = (Math.PI * 2 * index) / Math.max(1, ordered.length) + categoryIndex * 0.56
      const radius = 7 + Math.min(15, ordered.length * 1.2)
      const relationPull = Math.min(7, degree.get(String(node.id)) || 0)
      const x = 50 + laneOffset + Math.cos(angle) * (radius - relationPull * 0.35)
      const y = 51 + Math.sin(angle) * radius * 0.55 + (1 - tier) * 11
      const z = -260 + tier * 260 + relationPull * 18 + (categoryIndex - (categoryCount - 1) / 2) * 34
      const focused = !pathMode.value || selectedNeighbors.value.has(String(node.id))
      layoutNodes.push({
        ...node,
        id: String(node.id),
        x,
        y,
        z,
        color: categoryColors.get(node.category) || palette[0],
        size: 38 + Math.min(18, relationPull * 3) + Math.max(0, mastery) / 10,
        tier,
        focused,
        degree: relationPull,
        layer: tier === 2 ? '已掌握层' : tier === 1 ? '巩固层' : '待复习层',
      })
    })
  })
  const byId = new Map(layoutNodes.map((node) => [node.id, node]))
  return {
    nodes: layoutNodes,
    edges: edges.map((edge) => {
      const source = byId.get(String(edge.source))
      const target = byId.get(String(edge.target))
      if (!source || !target) return null
      const active = !pathMode.value || !selected.value || source.id === String(selected.value.id) || target.id === String(selected.value.id)
      const dx = target.x - source.x
      const dy = target.y - source.y
      const length = Math.sqrt(dx * dx + dy * dy)
      const angle = Math.atan2(dy, dx) * 180 / Math.PI
      return {
        id: `${source.id}-${target.id}`,
        source,
        target,
        weight: Number(edge.weight || 0),
        active,
        length,
        angle,
        z: (source.z + target.z) / 2,
      }
    }).filter(Boolean),
    layers: [
      { id: 'weak', label: '待复习层', z: -260, y: 62 },
      { id: 'steady', label: '巩固层', z: 0, y: 52 },
      { id: 'mastered', label: '已掌握层', z: 260, y: 42 },
    ],
  }
})
const graphTransformStyle = computed(() => ({
  transform: `translateZ(-120px) rotateX(${graphTilt.value.x}deg) rotateY(${graphTilt.value.y}deg) scale(${graphZoom.value})`,
}))
const reviewPrompt = computed(() => selected.value ? `请先不看答案，回忆“${selected.value.label}”的核心含义、用途和它关联的知识点。` : '')
const reviewAnswer = computed(() => selected.value?.summary || '该节点暂无完整解释，请从关联素材中补充复习。')
const reviewFollowups = computed(() => (selectedDetail.value?.related || []).slice(0, 3).map((item) => `它和“${item.label}”之间是什么关系？`))

function flash(message) {
  notice.value = message
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = '' }, 3200)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    graph.value = await api('/graph')
    if (selected.value) {
      const fresh = graph.value.nodes.find((node) => String(node.id) === String(selected.value.id))
      if (fresh) await selectNode(fresh, false)
    }
    await nextTick()
    render()
  } catch (err) {
    error.value = err.message || '知识图谱加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMaterials() {
  try {
    materials.value = await api('/materials')
  } catch (err) {
    flash(err.message || '素材列表加载失败')
  }
}

async function selectNode(node, rerender = true) {
  selected.value = node
  revealReview.value = false
  reviewFeedback.value = ''
  try {
    selectedDetail.value = await api(`/graph/nodes/${node.id}`)
    // The detail endpoint carries the latest mastery counters. Merge them
    // back into the selected graph node so related-node navigation never
    // falls back to stale or missing display values.
    if (selectedDetail.value?.node) selected.value = { ...node, ...selectedDetail.value.node }
  } catch (err) {
    selectedDetail.value = { node, related: [], materials: [], activity: [] }
    flash(err.message || '节点详情加载失败')
  }
  if (rerender) render()
}

function render() {
  if (viewMode.value === 'knowledge3d') {
    chart?.dispose()
    chart = undefined
    return
  }
  if (!chartEl.value || !graph.value) return
  chart?.dispose()
  chart = echarts.init(chartEl.value)
  const categoryColors = new Map((graph.value.categories || []).map((item, index) => [item, palette[index % palette.length]]))
  const focusIds = selectedNeighbors.value
  const data = visibleNodes.value.map((node) => {
    const color = categoryColors.get(node.category) || palette[0]
    const focused = !pathMode.value || focusIds.has(String(node.id))
    return {
      id: String(node.id),
      name: node.label,
      value: node.mastery,
      category: node.category,
      symbolSize: 18 + Math.max(0, Number(node.mastery || 0)) / 5,
      itemStyle: { color, opacity: focused ? 1 : 0.18, shadowBlur: focused ? 14 : 0, shadowColor: color },
      label: { show: focused, color: '#31566b' },
    }
  })
  const links = visibleEdges.value.map((edge) => {
    const active = !pathMode.value || !selected.value || (String(edge.source) === String(selected.value.id) || String(edge.target) === String(selected.value.id))
    return { source: String(edge.source), target: String(edge.target), value: edge.weight, lineStyle: { width: 1 + Number(edge.weight || 0) * 3, color: active ? '#69b5be' : '#6d737b', opacity: active ? 0.74 : 0.12 } }
  })
  chart.setOption({
    animationDuration: 600,
    tooltip: { formatter: (params) => params.dataType === 'node' ? `${params.data.name}<br/>掌握度 ${params.data.value}%` : '' },
    series: [{
      type: 'graph',
      layout: viewMode.value === 'circular' ? 'circular' : 'force',
      roam: true,
      draggable: true,
      circular: { rotateLabel: false },
      force: { repulsion: 420, edgeLength: [110, 220], gravity: 0.08 },
      data,
      links,
      lineStyle: { curveness: 0.08 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
    }],
  })
  chart.on('click', (params) => {
    if (params.dataType !== 'node') return
    const node = visibleNodes.value.find((item) => String(item.id) === String(params.data.id))
    if (node) selectNode(node)
  })
}

function zoom(delta) {
  if (viewMode.value === 'knowledge3d') {
    graphZoom.value = Math.max(0.64, Math.min(1.75, graphZoom.value * delta))
    return
  }
  if (!chart) return
  const current = Number(chart.getOption().series?.[0]?.zoom || 1)
  chart.setOption({ series: [{ zoom: Math.max(0.45, Math.min(4, current * delta)) }] })
}

function resetView() {
  if (viewMode.value === 'knowledge3d') {
    graphZoom.value = 1
    graphTilt.value = { x: -16, y: 24 }
    return
  }
  if (!chart) return
  chart.dispatchAction({ type: 'restore' })
  render()
}

async function exportGraph() {
  if (viewMode.value === 'knowledge3d') {
    flash('3D 模型请切换到关系布局后导出静态图片')
    return
  }
  if (!chart) return
  try {
    await api('/graph/export-authorize', { method: 'POST' })
  } catch (err) {
    flash(err?.message || '高清图谱导出失败')
    return
  }
  const link = document.createElement('a')
  link.download = `zhiyan-knowledge-graph-${new Date().toISOString().slice(0, 10)}.png`
  link.href = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: getComputedStyle(chartEl.value).backgroundColor || '#111316' })
  link.click()
  flash('图谱图片已导出')
}

function tiltGraph(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const x = (event.clientX - rect.left) / Math.max(1, rect.width) - 0.5
  const y = (event.clientY - rect.top) / Math.max(1, rect.height) - 0.5
  graphTilt.value = {
    x: Math.max(-30, Math.min(10, -16 - y * 20)),
    y: Math.max(-42, Math.min(42, 24 + x * 32)),
  }
}

function reviewNode(result) {
  reviewFeedback.value = result === 'known'
    ? '已记录本次自测：该节点可以进入下一轮间隔复习。'
    : '已标记为薄弱节点：建议优先查看关联素材并进入游戏化复习。'
  flash(reviewFeedback.value)
}

function masteryLevel(value) {
  const mastery = Number(value || 0)
  if (mastery <= 0) return 'empty'
  if (mastery >= 80) return 'mastered'
  if (mastery >= 50) return 'steady'
  return 'weak'
}

function masteryLabel(value) {
  const level = masteryLevel(value)
  if (level === 'empty') return '尚未学习'
  if (level === 'mastered') return '出色掌握'
  if (level === 'steady') return '稳步推进'
  return '需要强化'
}

function openMaterialPicker() {
  materialQuery.value = ''
  selectedMaterialIds.value = []
  materialPickerOpen.value = true
}

async function submitGraphReview(result) {
  if (!selected.value) return
  reviewFeedback.value = result === 'known' ? '正在记录掌握结果...' : '正在标记薄弱节点...'
  try {
    selectedDetail.value = await api(`/graph/nodes/${selected.value.id}/review`, { method: 'POST', body: { result } })
    if (selectedDetail.value?.node) selected.value = { ...selected.value, ...selectedDetail.value.node }
    reviewFeedback.value = result === 'known'
      ? '已记录本次自测：该节点会进入下一轮间隔复习。'
      : '已标记为薄弱节点：建议优先查看关联素材并进入游戏化复习。'
    flash(reviewFeedback.value)
    await load()
  } catch (err) {
    reviewFeedback.value = err.message || '复习记录保存失败'
    flash(reviewFeedback.value)
  }
}

function toggleMaterial(id) {
  selectedMaterialIds.value = selectedMaterialIds.value.includes(id)
    ? selectedMaterialIds.value.filter((item) => item !== id)
    : [...selectedMaterialIds.value, id]
}

function toggleAllMaterials() {
  const ids = filteredMaterials.value.map((item) => item.id)
  const allSelected = ids.length > 0 && ids.every((id) => selectedMaterialIds.value.includes(id))
  selectedMaterialIds.value = allSelected
    ? selectedMaterialIds.value.filter((id) => !ids.includes(id))
    : [...new Set([...selectedMaterialIds.value, ...ids])]
}

async function rebuild(materialIds = []) {
  rebuilding.value = true
  materialPickerOpen.value = false
  rebuildStage.value = 0
  clearInterval(rebuildTimer)
  rebuildTimer = setInterval(() => {
    rebuildStage.value = (rebuildStage.value + 1) % rebuildStages.length
  }, 900)
  try {
    const target = Math.max(8, Math.min(300, Number(nodeTarget.value || 80)))
    nodeTarget.value = target
    graph.value = await api('/graph/rebuild', { method: 'POST', body: { material_ids: materialIds, node_limit: target } })
    selected.value = null
    selectedDetail.value = null
    materialPickerOpen.value = false
    await nextTick()
    render()
    const scope = materialIds.length ? `已选 ${materialIds.length} 个素材` : '全部已入库素材'
    const agentLabel = graph.value.source_mode === 'deepseek-agent' ? 'Agent' : '本地 Agent'
    flash(`${scope}已由${agentLabel}提取并生成 ${graph.value.stats?.nodes || 0} 个核心节点`)
  } catch (err) {
    flash(err.message || '图谱重建失败')
  } finally {
    clearInterval(rebuildTimer)
    rebuildTimer = undefined
    rebuilding.value = false
  }
}

function rebuildSelected() {
  if (!selectedMaterialIds.value.length) {
    flash('请至少选择一个已入库素材')
    return
  }
  rebuild([...selectedMaterialIds.value])
}

function resize() { chart?.resize() }
watch([category, query, viewMode, pathMode], () => nextTick(render))
onMounted(() => { load(); loadMaterials(); window.addEventListener('resize', resize) })
onBeforeUnmount(() => { chart?.dispose(); clearTimeout(noticeTimer); clearInterval(rebuildTimer); window.removeEventListener('resize', resize) })
</script>

<template>
  <AppShell search-placeholder="搜索知识节点...">
    <div class="graph-page">
      <section class="graph-canvas">
        <header class="graph-header">
          <div>
            <span class="eyebrow"><Network /> 知识可视化</span>
            <h1>知识图谱</h1>
            <p>从素材、进化结果和学习行为中持续更新的个人知识网络。</p>
          </div>
          <div class="graph-actions">
            <button class="button outline" :disabled="rebuilding" @click="openMaterialPicker"><RefreshCw :class="{ spinning: rebuilding }" /> {{ rebuilding ? '同步中' : '选择素材生成' }}</button>
            <button class="button outline" title="导出图谱图片" @click="exportGraph"><Download /> 导出</button>
          </div>
        </header>
        <div class="graph-stats" v-if="graph?.stats">
          <span><strong>{{ graph.stats.nodes }}</strong>节点</span>
          <span><strong>{{ graph.stats.edges }}</strong>关联</span>
          <span><strong>{{ graph.stats.average_mastery }}%</strong>平均掌握度</span>
          <span><strong>{{ graph.stats.mastered }}</strong>已掌握</span>
        </div>
        <div class="graph-toolbar">
          <label><Search /><input v-model="query" placeholder="搜索节点、摘要或来源" /></label>
          <div class="graph-filter"><Filter /><button :class="{ active: category === '' }" @click="category = ''">全部</button><button v-for="item in (graph?.categories || [])" :key="item" :class="{ active: category === item }" @click="category = item">{{ item }}</button></div>
          <button class="path-toggle" :class="{ active: pathMode }" :disabled="!selected" @click="pathMode = !pathMode"><Sparkles /> {{ pathMode ? '显示全图' : '高亮关联' }}</button>
        </div>
        <div v-if="rebuilding" class="graph-rebuild-overlay" role="status" aria-live="polite">
          <div class="graph-rebuild-orbit" aria-hidden="true">
            <span class="orbit-node orbit-node-a"></span><span class="orbit-node orbit-node-b"></span><span class="orbit-node orbit-node-c"></span>
            <i class="orbit-line orbit-line-a"></i><i class="orbit-line orbit-line-b"></i><i class="orbit-line orbit-line-c"></i>
            <Network class="orbit-icon" />
          </div>
          <strong>正在生成知识图谱</strong>
          <span>{{ rebuildStages[rebuildStage] }}...</span>
          <div class="graph-rebuild-steps"><i v-for="(stage, index) in rebuildStages" :key="stage" :class="{ active: index === rebuildStage, done: index < rebuildStage }"></i></div>
        </div>
        <div v-if="loading" class="graph-state">正在加载知识网络…</div>
        <div v-else-if="error" class="graph-state error-state"><strong>{{ error }}</strong><button class="button secondary" @click="load">重新加载</button></div>
        <div v-else-if="!visibleNodes.length" class="graph-state"><strong>暂无匹配节点</strong><span>请调整筛选条件，或点击“选择素材生成”从已入库素材生成知识节点。</span></div>
        <div v-else-if="viewMode === 'knowledge3d'" class="graph-model3d" @pointermove="tiltGraph" @pointerleave="resetView">
          <div class="graph-depth-stage" :style="graphTransformStyle">
            <span
              v-for="layer in graphModel.layers"
              :key="layer.id"
              class="graph-depth-layer"
              :class="layer.id"
              :style="{ top: `${layer.y}%`, transform: `translate(-50%, -50%) translateZ(${layer.z}px) rotateX(78deg)` }"
            >
              <b>{{ layer.label }}</b>
            </span>
            <i
              v-for="edge in graphModel.edges"
              :key="edge.id"
              class="graph-model-edge"
              :class="{ dimmed: !edge.active }"
              :style="{ left: `${edge.source.x}%`, top: `${edge.source.y}%`, width: `${edge.length}%`, transform: `translateY(-50%) translateZ(${edge.z}px) rotate(${edge.angle}deg)`, '--edge-color': edge.active ? edge.source.color : '#42616d', '--edge-opacity': edge.active ? Math.max(.2, edge.weight) : .08, '--edge-thickness': `${Math.max(2, 2 + edge.weight * 5)}px` }"
            ></i>
            <button
              v-for="node in graphModel.nodes"
              :key="node.id"
              class="graph-model-node"
              :class="{ selected: selected && String(selected.id) === node.id, dimmed: !node.focused, mastered: node.tier === 2, weak: node.tier === 0 }"
              :style="{ left: `${node.x}%`, top: `${node.y}%`, width: `${node.size}px`, height: `${node.size}px`, '--node-color': node.color, transform: `translate(-50%, -50%) translateZ(${node.z}px)` }"
              @click.stop="selectNode(node)"
            >
              <span>{{ node.label }}</span>
              <small>{{ node.layer }}</small>
            </button>
          </div>
          <div class="graph-layer-legend">
            <span><b class="weak"></b>待复习层</span>
            <span><b></b>巩固层</span>
            <span><b class="mastered"></b>已掌握层</span>
          </div>
        </div>
        <div v-else ref="chartEl" class="echart"></div>
        <div class="view-switch"><button :class="{ active: viewMode === 'knowledge3d' }" @click="viewMode = 'knowledge3d'"><Layers3 /> 3D 层级</button><button :class="{ active: viewMode === 'force' }" @click="viewMode = 'force'"><Network /> 关系布局</button><button :class="{ active: viewMode === 'circular' }" @click="viewMode = 'circular'"><Layers3 /> 主题布局</button></div>
        <div class="zoom-controls"><button title="放大" @click="zoom(1.2)"><Plus /></button><button title="缩小" @click="zoom(.8)"><Minus /></button><button title="居中" @click="resetView"><Focus /></button></div>
        <span v-if="notice" class="graph-notice">{{ notice }}</span>
      </section>
      <aside class="node-detail">
        <button v-if="selected" class="close-detail" title="关闭节点详情" @click="selected = null; selectedDetail = null"><X /></button>
        <span class="node-badge">{{ selected ? '知识节点' : '图谱说明' }}</span>
        <template v-if="selected">
          <h1>{{ selected.label }}</h1>
          <p class="node-source">{{ selected.category }} · {{ selected.source_material_name || '知识库' }}</p>
          <section><h3><FileText /> 知识摘要</h3><p>{{ selected.summary || '暂无摘要。' }}</p></section>
          <section>
            <h3>掌握进度</h3>
            <div class="mastery-card" :class="`mastery-${masteryLevel(selected.mastery)}`">
              <div class="mastery-card-head">
                <strong>{{ Math.round(Number(selected.mastery || 0)) }}%</strong>
                <span>{{ masteryLabel(selected.mastery) }}</span>
              </div>
              <i class="mastery-track" aria-hidden="true">
                <b :style="{ width: `${Math.max(0, Math.min(100, Number(selected.mastery || 0)))}%` }"></b>
              </i>
              <div class="mastery-meta">
                <small>{{ selected.learning_attempts || 0 }} 次练习</small>
                <small>正确率 {{ selected.accuracy || 0 }}%</small>
              </div>
            </div>
          </section>
          <section class="graph-review-card">
            <h3><Sparkles /> 节点主动回忆</h3>
            <p>{{ reviewPrompt }}</p>
            <button v-if="!revealReview" class="button outline wide" type="button" @click="revealReview = true">揭示标准解释</button>
            <div v-else class="graph-review-answer">
              <strong>标准解释</strong>
              <p>{{ reviewAnswer }}</p>
              <ul v-if="reviewFollowups.length">
                <li v-for="item in reviewFollowups" :key="item">{{ item }}</li>
              </ul>
              <div class="graph-review-actions">
                <button class="button ghost" type="button" @click="submitGraphReview('weak')">仍需复习</button>
                <button class="button primary" type="button" @click="submitGraphReview('known')">已经掌握</button>
              </div>
            </div>
            <small v-if="reviewFeedback">{{ reviewFeedback }}</small>
          </section>
          <section><h3>关联素材 <small>{{ selectedDetail?.materials?.length || 0 }}</small></h3><article v-for="material in (selectedDetail?.materials || [])" :key="material.id"><small>{{ material.kind }} · {{ material.category }}</small><strong>{{ material.name }}</strong><p>{{ material.excerpt }}</p></article><p v-if="!selectedDetail?.materials?.length" class="muted-copy">暂无关联素材</p></section>
          <section><h3>关联节点 <small>{{ selectedDetail?.related?.length || 0 }}</small></h3><div class="related-list"><button v-for="item in (selectedDetail?.related || [])" :key="item.id" @click="selectNode(item)"><span :style="{ width: `${Math.max(18, item.mastery)}%` }"></span><b>{{ item.label }}</b><em>{{ Math.round(Number(item.weight || 0) * 100) }}%</em></button><p v-if="!selectedDetail?.related?.length" class="muted-copy">暂无关系，尝试同步图谱。</p></div></section>
          <section><h3>最近学习</h3><div class="activity-list"><div v-for="item in (selectedDetail?.activity || [])" :key="`${item.created_at}-${item.game}`"><span :class="item.correct ? 'ok' : 'bad'">{{ item.correct ? '✓' : '×' }}</span><p>{{ item.game }} · {{ item.correct ? '答对' : '待巩固' }}<small>{{ item.created_at?.slice(0, 10) }}</small></p><b>{{ item.score }} XP</b></div><p v-if="!selectedDetail?.activity?.length" class="muted-copy">还没有与该节点相关的学习记录。</p></div></section>
          <button class="button primary wide" @click="$router.push('/evolution')"><Sparkles /> 去进化中心</button>
        </template>
        <template v-else>
          <h1>你的知识网络</h1>
          <section><h3>如何使用</h3><p>节点代表从已入库素材提取的核心概念，连线代表共同来源、主题或语义关联。拖拽节点探索结构，点击节点查看摘要、关联文档和学习进度。</p></section>
          <section><h3>保持图谱更新</h3><p>知识进化完成后，系统会自动尝试刷新相关节点。导入新素材后点击“同步图谱”，即可将最新知识纳入网络。</p></section>
          <button class="button primary wide" @click="openMaterialPicker"><RefreshCw /> 选择素材生成</button>
        </template>
      </aside>
    </div>
    <ModalDialog v-if="materialPickerOpen" title="选择图谱素材" wide @close="materialPickerOpen = false">
      <div class="graph-picker">
        <header>
          <div><strong>从知识库提取概念与关联</strong><small>可选择一个或多个已入库素材，生成独立的知识图谱视图。</small></div>
          <span>已选 {{ selectedMaterialIds.length }} / {{ readyMaterials.length }}</span>
        </header>
        <div class="graph-picker-tools">
          <label><Search /><input v-model="materialQuery" placeholder="搜索素材名称、分类或类型" /></label>
          <button type="button" @click="toggleAllMaterials">{{ filteredMaterials.length && filteredMaterials.every((item) => selectedMaterialIds.includes(item.id)) ? '取消全选' : '全选当前结果' }}</button>
        </div>
        <div class="graph-node-target">
          <span>
            <strong>知识节点数量</strong>
            <small>数量越多越适合系统复习，生成耗时也会增加。</small>
          </span>
          <div>
            <button v-for="item in nodeTargetOptions" :key="item" type="button" :class="{ active: nodeTarget === item }" @click="nodeTarget = item">{{ item }}</button>
            <input v-model.number="nodeTarget" type="number" min="8" max="300" step="1" />
          </div>
        </div>
        <div v-if="!readyMaterials.length" class="graph-picker-empty"><FileText /><strong>暂无可用素材</strong><span>请先在素材管理中导入并处理文本、网页、图片或视频内容。</span></div>
        <div v-else class="graph-material-list">
          <label v-for="item in filteredMaterials" :key="item.id" class="graph-material-option" :class="{ selected: selectedMaterialIds.includes(item.id) }">
            <input type="checkbox" :checked="selectedMaterialIds.includes(item.id)" @change="toggleMaterial(item.id)" />
            <span class="graph-material-check">{{ selectedMaterialIds.includes(item.id) ? '✓' : '' }}</span>
            <span class="graph-material-copy">
              <strong :title="item.name">{{ item.name }}</strong>
              <span class="graph-material-meta">
                <b>{{ item.kind || '素材' }}</b>
                <b>{{ item.category || '未分类' }}</b>
                <b>{{ (item.content?.length || 0).toLocaleString() }} 字</b>
              </span>
              <em>{{ item.content?.slice(0, 180) || '暂无可预览内容，生成时会根据已入库文本提取概念。' }}</em>
            </span>
            <span class="graph-material-state">{{ selectedMaterialIds.includes(item.id) ? '已加入' : '待选择' }}</span>
          </label>
          <p v-if="!filteredMaterials.length" class="graph-picker-empty">没有匹配的素材。</p>
        </div>
        <footer class="graph-picker-actions">
          <button class="button ghost" type="button" @click="materialPickerOpen = false">取消</button>
          <button class="button outline" type="button" :disabled="rebuilding || !readyMaterials.length" @click="rebuild([])"><RefreshCw /> 全库生成</button>
          <button class="button primary" type="button" :disabled="rebuilding || !selectedMaterialIds.length" @click="rebuildSelected"><Sparkles /> 生成所选图谱</button>
        </footer>
      </div>
    </ModalDialog>
  </AppShell>
</template>
