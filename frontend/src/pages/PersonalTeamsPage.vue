<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  BarChart3,
  BookOpen,
  Building2,
  CheckCircle2,
  ClipboardList,
  CircleDollarSign,
  Gem,
  FilePlus2,
  KeyRound,
  RefreshCw,
  Search,
  ShieldCheck,
  Trophy,
  Upload,
  UserPlus,
  UsersRound,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { api, formatBytes } from '../api'

const roleLabels = {
  owner: '负责人',
  admin: '管理员',
  editor: '编辑成员',
  viewer: '只读成员',
}
const teamTypeLabels = {
  learning: '学习小组',
  research: '科研课题组',
  studio: '创作工作室',
}

const teams = ref([])
const selectedTeamId = ref('')
const workspace = ref(null)
const loading = ref(true)
const detailLoading = ref(false)
const saving = ref(false)
const scoreSaving = ref(false)
const error = ref('')
const notice = ref('')
const searchTerm = ref('')
const searchResults = ref([])
const searching = ref(false)
const searchDone = ref(false)
const searchError = ref('')
const showDiscover = ref(false)
const discoverModalOpen = ref(false)
const joinModalOpen = ref(false)
const joinTarget = ref(null)
const joinCode = ref('')
const joinError = ref('')
const joining = ref(false)
const uploadModalOpen = ref(false)
const uploadForm = ref({ lib_id: '', name: '', content: '', tags: '' })
const uploadMode = ref('manual')
const personalMaterials = ref([])
const personalMaterialsLoading = ref(false)
const selectedPersonalMaterialId = ref('')
const scoreModalOpen = ref(false)
const scoreForm = ref({ game: 'flashcard', score: 120, correct: 8, total: 10 })
const teamNotifications = ref([])
const notificationsLoading = ref(false)
const reviewModalOpen = ref(false)
const activeNotification = ref(null)
const reviewForm = ref({ task_id: '', decision: 'accepted', feedback: '' })
let noticeTimer = null

const selectedTeam = computed(() => teams.value.find((team) => String(team.id) === String(selectedTeamId.value)))
const team = computed(() => workspace.value?.team || selectedTeam.value || null)
const counts = computed(() => workspace.value?.counts || selectedTeam.value?.counts || {})
const libraries = computed(() => workspace.value?.libraries || [])
const materials = computed(() => workspace.value?.materials || [])
const teamRole = computed(() => team.value?.role || selectedTeam.value?.role || 'viewer')
const roleLabel = computed(() => roleLabels[teamRole.value] || teamRole.value)
const canUpload = computed(() => ['owner', 'admin', 'editor'].includes(teamRole.value))
const selectedPersonalMaterial = computed(() => personalMaterials.value.find(
  (item) => String(item.id) === String(selectedPersonalMaterialId.value),
))
const pendingNotifications = computed(() => teamNotifications.value.filter((item) => item.status === 'pending'))
const permissionItems = computed(() => {
  const items = ['查看团队基础数据', '浏览团队知识库与近期素材', '提交个人学习成绩']
  if (canUpload.value) items.splice(2, 0, '上传团队素材')
  return items
})

function toast(message) {
  notice.value = message
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    if (notice.value === message) notice.value = ''
  }, 2800)
}

function normalizeCode() {
  joinCode.value = joinCode.value.replace(/\s+/g, '').toUpperCase()
}

function splitTags(value) {
  return String(value || '').replaceAll('，', ',').split(',').map((item) => item.trim()).filter(Boolean)
}

async function fetchTeams() {
  const payload = await api('/teams')
  teams.value = (payload.teams || []).filter((item) => item.member_status === 'active' && item.status === 'active')
  if (!teams.value.length) {
    selectedTeamId.value = ''
    workspace.value = null
    return
  }
  if (!teams.value.some((item) => String(item.id) === String(selectedTeamId.value))) {
    selectedTeamId.value = String(teams.value[0].id)
  }
}

async function loadWorkspace() {
  if (!selectedTeamId.value) {
    workspace.value = null
    return
  }
  detailLoading.value = true
  try {
    workspace.value = await api(`/teams/${selectedTeamId.value}/workspace`)
  } finally {
    detailLoading.value = false
  }
}

async function loadTeamNotifications() {
  notificationsLoading.value = true
  try {
    const payload = await api('/teams/personal/notifications?limit=40')
    teamNotifications.value = payload.items || []
  } catch (err) {
    error.value = err?.message || '团队通知加载失败'
  } finally {
    notificationsLoading.value = false
  }
}

async function loadPage() {
  loading.value = true
  error.value = ''
  try {
    await fetchTeams()
    await loadWorkspace()
    await loadTeamNotifications()
  } catch (err) {
    error.value = err?.message || '团队数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function selectTeam(teamId) {
  selectedTeamId.value = String(teamId)
  error.value = ''
  try {
    await loadWorkspace()
  } catch (err) {
    error.value = err?.message || '团队详情加载失败，请稍后重试'
  }
}

function notificationLabel(item) {
  const labels = {
    join_approved: '已加入',
    join_rejected: '申请结果',
    member_update: '权限变更',
    member_remove: '权限回收',
    owner_transfer: '负责人变更',
    review_requested: '待审核',
    needs_changes: '需调整',
    completed: '已完成',
    create: '新建',
    update: '更新',
    score_settled: '已结算',
  }
  return labels[item.action] || item.action || '团队消息'
}

function canOpenNotificationAction(item) {
  if (item.status !== 'pending') return false
  if (item.target_type === 'evolution_task' && item.action === 'review_requested') return true
  if (item.target_type === 'activity') return true
  if (item.team_id && ['member_update', 'join_approved', 'permission', 'permission_remove', 'create', 'update'].includes(item.action)) return true
  return false
}

async function selectNotificationTeam(item) {
  if (!item?.team_id) return false
  if (!teams.value.some((teamItem) => String(teamItem.id) === String(item.team_id))) return false
  if (String(selectedTeamId.value) !== String(item.team_id)) {
    selectedTeamId.value = String(item.team_id)
    await loadWorkspace()
  }
  return true
}

async function readNotification(item) {
  await api(`/teams/personal/notifications/${item.id}/read`, { method: 'POST' })
  await loadTeamNotifications()
}

async function completeNotification(item, message = '已确认团队消息') {
  await api(`/teams/personal/notifications/${item.id}/handle`, { method: 'POST' })
  await loadTeamNotifications()
  await fetchTeams()
  await loadWorkspace()
  toast(message)
}

async function openNotificationAction(item) {
  const selected = await selectNotificationTeam(item)
  if (item.target_type === 'evolution_task' && item.action === 'review_requested') {
    if (!selected) {
      toast('该团队当前不可访问，无法在个人端处理审核')
      return
    }
    activeNotification.value = item
    reviewForm.value = { task_id: item.target_id, decision: 'accepted', feedback: '' }
    reviewModalOpen.value = true
    await readNotification(item)
    return
  }
  if (item.target_type === 'activity') {
    if (selected) scoreModalOpen.value = true
    await completeNotification(item, '已打开团队活动处理入口')
    return
  }
  if (selected) await loadWorkspace()
  await completeNotification(item, '团队消息已同步')
}

async function submitEvolutionReviewFromNotification() {
  if (!activeNotification.value || !selectedTeamId.value || !reviewForm.value.task_id) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/evolution/${reviewForm.value.task_id}/reviews`, {
      method: 'POST',
      body: { decision: reviewForm.value.decision, feedback: reviewForm.value.feedback },
    })
    reviewModalOpen.value = false
    await completeNotification(activeNotification.value, '团队进化审核已提交')
    activeNotification.value = null
  } catch (err) {
    error.value = err?.message || '团队进化审核提交失败'
  } finally {
    saving.value = false
  }
}

async function searchTeams() {
  const keyword = searchTerm.value.trim()
  if (keyword.length < 2) {
    searchError.value = '请输入至少 2 个字的团队名称或简介关键词'
    searchDone.value = false
    searchResults.value = []
    return
  }
  searching.value = true
  searchError.value = ''
  searchDone.value = false
  try {
    const payload = await api(`/teams/discover?q=${encodeURIComponent(keyword)}`)
    searchResults.value = payload.items || []
    searchDone.value = true
  } catch (err) {
    searchError.value = err?.message || '团队搜索失败，请稍后重试'
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

async function requestJoin(target) {
  try {
    const result = await api(`/teams/${target.id}/join-requests`, {
      method: 'POST',
      body: { message: '通过个人端搜索申请加入团队' },
    })
    target.join_request_status = result.status
    toast(`已向「${result.team_name}」提交加入申请，请等待团队审核`)
  } catch (err) {
    searchError.value = err?.message || '提交加入申请失败'
  }
}

function openDiscoverModal() {
  searchTerm.value = ''
  searchResults.value = []
  searchDone.value = false
  searchError.value = ''
  discoverModalOpen.value = true
}

function closeDiscoverModal() {
  if (!searching.value) discoverModalOpen.value = false
}

function openJoinModal(target = null) {
  joinTarget.value = target
  joinCode.value = ''
  joinError.value = ''
  joinModalOpen.value = true
}

function closeJoinModal() {
  if (!joining.value) joinModalOpen.value = false
}

async function joinTeam() {
  normalizeCode()
  if (!joinCode.value) {
    joinError.value = '请输入团队邀请码'
    return
  }
  joining.value = true
  joinError.value = ''
  try {
    const result = await api('/teams/join', { method: 'POST', body: { code: joinCode.value } })
    joinModalOpen.value = false
    discoverModalOpen.value = false
    showDiscover.value = false
    searchTerm.value = ''
    searchResults.value = []
    searchDone.value = false
    toast(`已向「${result.team_name}」提交加入申请，等待团队审核`)
    await fetchTeams()
  } catch (err) {
    joinError.value = err?.message || '提交加入申请失败'
  } finally {
    joining.value = false
  }
}

function openJoinForTeam(target) {
  discoverModalOpen.value = false
  openJoinModal(target)
}

function openUploadModal() {
  if (!canUpload.value || !selectedTeamId.value) return
  uploadForm.value = { lib_id: libraries.value[0]?.id || '', name: '', content: '', tags: '' }
  uploadMode.value = 'manual'
  selectedPersonalMaterialId.value = ''
  uploadModalOpen.value = true
  loadPersonalMaterials()
}

async function loadPersonalMaterials() {
  personalMaterialsLoading.value = true
  try {
    const payload = await api('/materials')
    personalMaterials.value = Array.isArray(payload) ? payload : payload.items || []
    if (!personalMaterials.value.some((item) => String(item.id) === String(selectedPersonalMaterialId.value))) {
      selectedPersonalMaterialId.value = ''
    }
  } catch (err) {
    error.value = err?.message || '个人素材加载失败'
  } finally {
    personalMaterialsLoading.value = false
  }
}

async function importPersonalMaterial() {
  if (!selectedPersonalMaterialId.value) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials/import-personal`, {
      method: 'POST',
      body: {
        material_id: Number(selectedPersonalMaterialId.value),
        lib_id: uploadForm.value.lib_id ? Number(uploadForm.value.lib_id) : null,
        name: uploadForm.value.name.trim() || null,
        tags: splitTags(uploadForm.value.tags),
      },
    })
    uploadModalOpen.value = false
    await loadPage()
    toast('个人素材已同步到团队素材库')
  } catch (err) {
    error.value = err?.message || '个人素材同步失败'
  } finally {
    saving.value = false
  }
}

async function submitUpload() {
  if (uploadMode.value === 'personal') {
    await importPersonalMaterial()
    return
  }
  if (!uploadForm.value.name.trim() || !uploadForm.value.content.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials`, {
      method: 'POST',
      body: {
        lib_id: uploadForm.value.lib_id ? Number(uploadForm.value.lib_id) : null,
        name: uploadForm.value.name.trim(),
        content: uploadForm.value.content.trim(),
        tags: splitTags(uploadForm.value.tags),
        kind: 'Markdown',
      },
    })
    uploadModalOpen.value = false
    await loadPage()
    toast('团队素材已上传')
  } catch (err) {
    error.value = err?.message || '团队素材上传失败'
  } finally {
    saving.value = false
  }
}

async function submitScore() {
  scoreSaving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/games/score`, { method: 'POST', body: scoreForm.value })
    scoreModalOpen.value = false
    await loadPage()
    toast('个人学习成绩已同步到团队')
  } catch (err) {
    error.value = err?.message || '学习成绩提交失败'
  } finally {
    scoreSaving.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <AppShell search-placeholder="搜索团队名称或简介...">
    <div class="page-wrap personal-teams-page">
      <header class="personal-team-heading">
        <div>
          <span class="eyebrow"><UsersRound /> 个人团队空间</span>
          <h1>我的团队</h1>
          <p>在个人端查看已加入团队的基础数据，并按当前角色完成上传与学习记录等基础协作。</p>
        </div>
        <div class="personal-team-heading-actions">
          <button class="button ghost" type="button" :disabled="loading" @click="loadPage"><RefreshCw />刷新</button>
          <button class="button primary" type="button" @click="openDiscoverModal"><UserPlus />加入团队</button>
        </div>
      </header>

      <p v-if="error" class="personal-team-alert error">{{ error }}</p>
      <p v-if="notice" class="personal-team-alert"><CheckCircle2 /> {{ notice }}</p>
      <div v-if="loading" class="panel personal-team-loading">正在加载个人团队空间...</div>

      <section v-if="!loading" class="panel personal-team-inbox">
        <header class="personal-section-heading">
          <div>
            <span class="eyebrow"><ClipboardList /> Team Inbox</span>
            <h2>团队消息与待办</h2>
            <p>接收团队端产生的成员、权限、活动与协同进化操作，并在个人端完成可用处理。</p>
          </div>
          <button class="button ghost" type="button" :disabled="notificationsLoading" @click="loadTeamNotifications">
            <RefreshCw />{{ notificationsLoading ? '同步中...' : '刷新消息' }}
          </button>
        </header>
        <div class="personal-inbox-summary">
          <span><strong>{{ teamNotifications.length }}</strong><small>全部消息</small></span>
          <span><strong>{{ pendingNotifications.length }}</strong><small>待处理</small></span>
        </div>
        <div v-if="notificationsLoading" class="personal-team-empty-inline">正在同步团队消息...</div>
        <div v-else-if="!teamNotifications.length" class="personal-team-empty-inline">暂无团队端同步过来的消息。</div>
        <div v-else class="personal-inbox-list">
          <article v-for="item in teamNotifications.slice(0, 8)" :key="item.id" :class="{ done: item.status === 'done', unread: !item.read }">
            <span class="personal-list-icon"><ClipboardList /></span>
            <div>
              <strong>{{ item.title }}</strong>
              <small>{{ item.team_name || '历史团队' }} · {{ notificationLabel(item) }} · {{ item.actor_name || '系统' }}</small>
              <p>{{ item.detail }}</p>
            </div>
            <div class="personal-inbox-actions">
              <button v-if="canOpenNotificationAction(item)" class="button compact secondary" type="button" @click="openNotificationAction(item)">处理</button>
              <button v-if="item.status === 'pending'" class="button compact ghost" type="button" @click="completeNotification(item)">确认</button>
              <button v-else-if="!item.read" class="button compact ghost" type="button" @click="readNotification(item)">已读</button>
            </div>
          </article>
        </div>
      </section>

      <template v-if="!loading && teams.length">
        <div class="personal-team-layout">
          <aside class="panel personal-team-list">
            <header><div><strong>已加入团队</strong><small>{{ teams.length }} 个团队空间</small></div><UsersRound /></header>
            <button v-for="item in teams" :key="item.id" type="button" class="personal-team-list-item" :class="{ active: String(item.id) === String(selectedTeamId) }" @click="selectTeam(item.id)">
              <span class="personal-team-avatar">{{ item.name.slice(0, 1) }}</span>
              <span><strong>{{ item.name }}</strong><small>{{ item.role_label || roleLabels[item.role] }} · {{ item.counts?.members || 0 }} 名成员</small></span>
            </button>
            <button class="personal-team-search-link" type="button" @click="openDiscoverModal"><Search />搜索并申请加入其他团队</button>
          </aside>

          <main class="personal-team-main">
            <section v-if="detailLoading" class="panel personal-team-loading">正在同步团队数据...</section>
            <template v-else-if="team">
              <section class="panel personal-team-summary">
                <header>
                  <div class="personal-team-title">
                    <span class="personal-team-emblem"><Building2 /></span>
                    <div><span class="eyebrow">Personal Team View</span><h2>{{ team.name }}</h2><p>{{ team.description || '该团队暂未填写介绍。' }}</p></div>
                  </div>
                  <div class="personal-team-status"><span class="role-badge"><ShieldCheck />{{ roleLabel }}</span><small>{{ teamTypeLabels[team.team_type] || team.team_type }} · 正常运行</small></div>
                </header>
                <div class="personal-team-stat-grid">
                  <article><UsersRound /><span>团队成员</span><strong>{{ counts.members || 0 }}</strong></article>
                  <article><BookOpen /><span>知识库</span><strong>{{ counts.libraries || 0 }}</strong></article>
                  <article><ClipboardList /><span>团队素材</span><strong>{{ counts.materials || 0 }}</strong></article>
                  <article><BarChart3 /><span>存储占用</span><strong>{{ formatBytes(counts.storage_used) }}</strong></article>
                  <article><CircleDollarSign /><span>团队学识币</span><strong>{{ (workspace?.currency?.knowledge_balance || 0).toLocaleString() }}</strong></article>
                  <article><Gem /><span>团队真知晶</span><strong>{{ (workspace?.currency?.truth_balance || 0).toLocaleString() }}</strong></article>
                </div>
              </section>

              <section class="panel personal-team-permissions">
                <header class="personal-section-heading"><div><span class="eyebrow">My Permissions</span><h2>我的可用操作</h2></div><span class="permission-note">按当前团队角色开放</span></header>
                <div class="personal-permission-layout">
                  <div class="personal-permission-list"><span v-for="item in permissionItems" :key="item"><CheckCircle2 />{{ item }}</span></div>
                  <div class="personal-team-actions">
                    <button v-if="canUpload" class="button primary" type="button" @click="openUploadModal"><Upload />上传团队素材</button>
                    <button class="button secondary" type="button" @click="scoreModalOpen = true"><Trophy />提交学习成绩</button>
                  </div>
                </div>
                <p class="personal-team-boundary">成员管理、邀请码、团队设置、外部分享和协同进化审核等进阶操作只能在独立团队端完成。</p>
              </section>

              <div class="personal-team-content-grid">
                <section class="panel personal-team-list-card">
                  <header class="personal-section-heading"><div><h2>团队知识库</h2><small>{{ libraries.length }} 个知识库</small></div><BookOpen /></header>
                  <article v-for="library in libraries" :key="library.id"><span class="personal-list-icon"><BookOpen /></span><span><strong>{{ library.name }}</strong><small>{{ library.description || '团队协作知识库' }}</small></span></article>
                  <div v-if="!libraries.length" class="personal-team-empty-inline">团队暂未创建知识库。</div>
                </section>
                <section class="panel personal-team-list-card">
                  <header class="personal-section-heading"><div><h2>近期团队素材</h2><small>{{ materials.length }} 条</small></div><ClipboardList /></header>
                  <article v-for="material in materials.slice(0, 6)" :key="material.id"><span class="personal-list-icon"><FilePlus2 /></span><span><strong>{{ material.name }}</strong><small>{{ material.uploader?.nickname || '团队成员' }} · {{ material.status === 'ready' ? '已处理' : '处理中' }}</small></span></article>
                  <div v-if="!materials.length" class="personal-team-empty-inline">团队暂未上传素材。</div>
                </section>
              </div>
            </template>
          </main>
        </div>
      </template>

      <section v-if="!loading && !teams.length" class="panel personal-team-empty">
        <div class="personal-team-empty-icon"><UsersRound /></div>
        <span class="eyebrow">No Team Space</span>
        <h2>你还没有加入团队</h2>
        <p>搜索团队名称或简介，或向团队管理员索取邀请码提交加入申请。</p>
      </section>

      <section v-if="!loading && !teams.length" class="panel personal-team-discover">
        <header class="personal-section-heading">
          <div><span class="eyebrow"><Search /> Discover Teams</span><h2>搜索并申请加入团队</h2><p>搜索只展示活动团队，正式加入需要团队管理员审核。</p></div>
          <button v-if="teams.length" class="icon-button" type="button" title="收起搜索" @click="showDiscover = false">×</button>
        </header>
        <form class="personal-team-search-form" @submit.prevent="searchTeams">
          <div class="personal-team-search-input"><Search /><input v-model="searchTerm" placeholder="输入团队名称或简介关键词" maxlength="80" /></div>
          <button class="button primary" type="submit" :disabled="searching"><Search />{{ searching ? '搜索中...' : '搜索团队' }}</button>
        </form>
        <p v-if="searchError" class="form-error">{{ searchError }}</p>
        <div v-if="searchDone && !searchResults.length" class="personal-team-empty-inline">没有找到可加入的团队，请更换关键词。</div>
        <div v-if="searchResults.length" class="personal-team-discover-list">
          <article v-for="item in searchResults" :key="item.id">
            <span class="personal-team-avatar">{{ item.name.slice(0, 1) }}</span>
            <div><strong>{{ item.name }}</strong><small>{{ teamTypeLabels[item.team_type] || item.team_type }} · {{ item.counts?.members || 0 }} 名成员 · {{ item.counts?.libraries || 0 }} 个知识库</small><p>{{ item.description || '该团队暂未填写简介。' }}</p></div>
            <div class="personal-team-result-actions">
              <button class="button secondary" type="button" :disabled="item.join_request_status === 'pending'" @click="requestJoin(item)"><UserPlus />{{ item.join_request_status === 'pending' ? '已提交申请' : '申请加入' }}</button>
              <button class="button ghost" type="button" @click="openJoinForTeam(item)"><KeyRound />邀请码加入</button>
            </div>
          </article>
        </div>
      </section>

      <ModalDialog v-if="joinModalOpen" title="通过邀请码加入团队" :close-disabled="joining" @close="closeJoinModal">
        <form class="stack-form personal-team-modal-form" @submit.prevent="joinTeam">
          <div v-if="joinTarget" class="personal-team-target"><span class="personal-list-icon"><Building2 /></span><span><strong>{{ joinTarget.name }}</strong><small>输入正确的邀请码即可免审核直接加入团队。</small></span></div>
          <div v-else class="personal-team-modal-intro"><KeyRound />输入团队邀请码可免审核直接加入，无需等待管理员审批。</div>
          <label>团队邀请码<div class="personal-team-code-input"><KeyRound /><input v-model="joinCode" maxlength="32" autocomplete="off" placeholder="例如 A1B2C3" @input="normalizeCode" /></div></label>
          <p v-if="joinError" class="form-error">{{ joinError }}</p>
          <div class="personal-team-modal-actions"><button class="button ghost" type="button" :disabled="joining" @click="closeJoinModal">取消</button><button class="button primary" type="submit" :disabled="joining || !joinCode.trim()"><UserPlus />{{ joining ? '提交中...' : '提交申请' }}</button></div>
        </form>
      </ModalDialog>

      <ModalDialog v-if="discoverModalOpen" title="搜索并申请加入团队" :close-disabled="searching" @close="closeDiscoverModal">
        <div class="stack-form personal-team-modal-form">
          <div class="personal-team-modal-intro"><Search />搜索团队后可直接申请加入（需管理员审核），或使用邀请码免审核直接加入。</div>
          <form class="personal-team-search-form" @submit.prevent="searchTeams">
            <div class="personal-team-search-input"><Search /><input v-model="searchTerm" placeholder="输入团队名称或简介关键词" maxlength="80" @keydown.enter.prevent="searchTeams" /></div>
            <button class="button primary" type="submit" :disabled="searching"><Search />{{ searching ? '搜索中...' : '搜索' }}</button>
          </form>
          <p v-if="searchError" class="form-error">{{ searchError }}</p>
          <div v-if="searching" class="personal-team-empty-inline">正在搜索团队...</div>
          <div v-else-if="searchDone && !searchResults.length" class="personal-team-empty-inline">没有找到可加入的团队，请更换关键词。</div>
          <div v-if="searchResults.length" class="personal-team-discover-list">
            <article v-for="item in searchResults" :key="item.id">
              <span class="personal-team-avatar">{{ item.name.slice(0, 1) }}</span>
              <div>
                <strong>{{ item.name }}</strong>
                <small>{{ teamTypeLabels[item.team_type] || item.team_type }} · {{ item.counts?.members || 0 }} 名成员 · {{ item.counts?.libraries || 0 }} 个知识库</small>
                <p>{{ item.description || '该团队暂未填写简介。' }}</p>
              </div>
              <div class="personal-team-result-actions">
                <button class="button secondary" type="button" :disabled="item.join_request_status === 'pending'" @click="requestJoin(item)"><UserPlus />{{ item.join_request_status === 'pending' ? '已提交申请' : '申请加入' }}</button>
                <button class="button ghost" type="button" @click="openJoinForTeam(item)"><KeyRound />邀请码加入</button>
              </div>
            </article>
          </div>
          <div class="personal-team-modal-actions" style="margin-top: 12px; border-top: 1px solid var(--outline); padding-top: 12px;">
            <span class="personal-team-modal-intro" style="flex:1; min-width:0;"><KeyRound />邀请码可免审核直接加入团队：</span>
            <button class="button secondary" type="button" @click="openJoinForTeam(null)">直接输入邀请码</button>
          </div>
        </div>
      </ModalDialog>

      <ModalDialog v-if="reviewModalOpen" title="处理团队进化审核" :close-disabled="saving" @close="reviewModalOpen = false">
        <form class="stack-form personal-team-modal-form" @submit.prevent="submitEvolutionReviewFromNotification">
          <div class="personal-team-modal-intro"><ClipboardList />来自团队端的协同进化任务，可在个人端按当前角色提交审核意见。</div>
          <label>任务编号<input v-model="reviewForm.task_id" disabled /></label>
          <label>审核结论
            <select v-model="reviewForm.decision">
              <option value="accepted">接受修改</option>
              <option value="needs_changes">反馈后重生成</option>
              <option value="rejected">拒绝修改</option>
            </select>
          </label>
          <label>审核反馈<textarea v-model="reviewForm.feedback" rows="5" placeholder="可补充理由、修改建议或重生成要求"></textarea></label>
          <div class="personal-team-modal-actions">
            <button class="button ghost" type="button" :disabled="saving" @click="reviewModalOpen = false">取消</button>
            <button class="button primary" type="submit" :disabled="saving"><CheckCircle2 />{{ saving ? '提交中...' : '提交审核' }}</button>
          </div>
        </form>
      </ModalDialog>

      <ModalDialog v-if="uploadModalOpen" title="上传团队素材" @close="uploadModalOpen = false">
        <form class="stack-form personal-team-modal-form" @submit.prevent="submitUpload">
          <div class="personal-upload-mode" role="tablist" aria-label="素材来源">
            <button class="button" :class="uploadMode === 'manual' ? 'primary' : 'ghost'" type="button" @click="uploadMode = 'manual'">手动输入</button>
            <button class="button" :class="uploadMode === 'personal' ? 'primary' : 'ghost'" type="button" @click="uploadMode = 'personal'">从个人素材选择</button>
          </div>
          <label>归属知识库<select v-model="uploadForm.lib_id"><option value="">未指定知识库</option><option v-for="library in libraries" :key="library.id" :value="library.id">{{ library.name }}</option></select></label>
          <template v-if="uploadMode === 'personal'">
            <label>个人素材
              <select v-model="selectedPersonalMaterialId" :disabled="personalMaterialsLoading">
                <option value="">{{ personalMaterialsLoading ? '正在加载个人素材...' : '请选择个人素材' }}</option>
                <option v-for="item in personalMaterials" :key="item.id" :value="item.id">
                  {{ item.name }} · {{ item.kind }} · {{ formatBytes(item.size) }}
                </option>
              </select>
            </label>
            <div v-if="selectedPersonalMaterial" class="personal-selected-material">
              <strong>{{ selectedPersonalMaterial.name }}</strong>
              <small>{{ selectedPersonalMaterial.source || 'upload' }} · {{ selectedPersonalMaterial.status || 'ready' }}</small>
            </div>
            <div v-if="!personalMaterialsLoading && !personalMaterials.length" class="personal-team-empty-inline">
              个人素材库中暂无可导入素材，请先在个人端保存素材。
            </div>
          </template>
          <label>素材名称<input v-model="uploadForm.name" maxlength="200" placeholder="例如：本周学习笔记" /></label>
          <label>标签<input v-model="uploadForm.tags" placeholder="多个标签用逗号分隔" /></label>
          <label v-if="uploadMode === 'manual'">素材内容<textarea v-model="uploadForm.content" rows="8" placeholder="输入要同步到团队空间的内容"></textarea></label>
          <div class="personal-team-modal-actions"><button class="button ghost" type="button" :disabled="saving" @click="uploadModalOpen = false">取消</button><button class="button primary" type="submit" :disabled="saving || (uploadMode === 'manual' ? !uploadForm.name.trim() || !uploadForm.content.trim() : !selectedPersonalMaterialId)"><FilePlus2 />{{ saving ? '处理中...' : uploadMode === 'personal' ? '导入到团队' : '确认上传' }}</button></div>
        </form>
      </ModalDialog>

      <ModalDialog v-if="scoreModalOpen" title="提交学习成绩" @close="scoreModalOpen = false">
        <form class="stack-form personal-team-modal-form" @submit.prevent="submitScore">
          <label>学习项目<select v-model="scoreForm.game"><option value="flashcard">闪卡</option><option value="monopoly">知识大富翁</option><option value="matching">配对竞速</option></select></label>
          <label>得分<input v-model.number="scoreForm.score" type="number" min="0" /></label>
          <div class="personal-score-grid"><label>答对题数<input v-model.number="scoreForm.correct" type="number" min="0" /></label><label>总题数<input v-model.number="scoreForm.total" type="number" min="1" /></label></div>
          <div class="personal-team-modal-actions"><button class="button ghost" type="button" :disabled="scoreSaving" @click="scoreModalOpen = false">取消</button><button class="button primary" type="submit" :disabled="scoreSaving"><Trophy />{{ scoreSaving ? '提交中...' : '同步成绩' }}</button></div>
        </form>
      </ModalDialog>
    </div>
  </AppShell>
</template>

<style scoped>
.personal-teams-page {
  padding-top: 30px;
  padding-bottom: 46px;
}

.personal-team-heading,
.personal-section-heading,
.personal-team-summary > header,
.personal-permission-layout {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
}

.personal-team-heading {
  margin-bottom: 22px;
}

.personal-team-heading h1 {
  margin: 9px 0 6px;
  font-size: 34px;
}

.personal-team-heading p,
.personal-section-heading p,
.personal-team-summary p,
.personal-team-boundary {
  color: var(--muted);
  line-height: 1.7;
}

.personal-team-heading-actions,
.personal-team-actions,
.personal-team-modal-actions {
  display: flex;
  gap: 9px;
  flex-wrap: wrap;
}

.personal-team-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
  padding: 12px 14px;
  border: 1px solid rgba(162, 255, 214, .28);
  border-radius: 8px;
  color: var(--mint);
  background: rgba(28, 72, 58, .3);
}

.personal-team-alert.error {
  border-color: rgba(255, 155, 155, .34);
  color: var(--red);
  background: rgba(88, 34, 42, .3);
}

.personal-team-loading,
.personal-team-empty {
  min-height: 320px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--muted);
}

.personal-team-layout {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.personal-team-list {
  position: sticky;
  top: 106px;
  padding: 17px;
}

.personal-team-list > header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--outline);
}

.personal-team-list header strong,
.personal-team-list header small {
  display: block;
}

.personal-team-list header small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}

.personal-team-list-item {
  width: 100%;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-top: 8px;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
}

.personal-team-list-item:hover,
.personal-team-list-item.active {
  border-color: rgba(125, 249, 255, .42);
  background: rgba(125, 249, 255, .08);
}

.personal-team-avatar,
.personal-team-emblem {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 8px;
  color: var(--mint);
  background: rgba(162, 255, 214, .13);
  font-weight: 800;
}

.personal-team-list-item strong,
.personal-team-list-item small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.personal-team-list-item small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}

.personal-team-search-link {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 14px;
  padding: 10px 2px;
  border: 0;
  border-top: 1px solid var(--outline);
  background: transparent;
  color: var(--cyan);
  text-align: left;
}

.personal-team-main {
  display: grid;
  gap: 18px;
}

.personal-team-summary,
.personal-team-permissions,
.personal-team-list-card,
.personal-team-discover {
  padding: 22px;
}

.personal-team-summary > header {
  align-items: flex-start;
}

.personal-team-title {
  display: flex;
  gap: 12px;
  align-items: center;
}

.personal-team-title h2 {
  margin: 7px 0 5px;
}

.personal-team-title p {
  margin: 0;
}

.personal-team-status {
  text-align: right;
}

.personal-team-status small {
  display: block;
  margin-top: 8px;
  color: var(--muted);
}

.role-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--mint);
}

.personal-team-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
}

.personal-team-stat-grid article {
  display: grid;
  gap: 7px;
  min-height: 116px;
  align-content: center;
  padding: 16px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  background: rgba(10, 30, 52, .52);
}

.personal-team-stat-grid article svg {
  color: var(--cyan);
}

.personal-team-stat-grid article span {
  color: var(--muted);
  font-size: 12px;
}

.personal-team-stat-grid article strong {
  font-size: 25px;
}

.personal-section-heading {
  align-items: flex-start;
}

.personal-section-heading h2 {
  margin: 7px 0 4px;
}

.permission-note {
  color: var(--cyan);
  font-size: 12px;
}

.personal-permission-layout {
  align-items: flex-start;
  margin-top: 16px;
}

.personal-permission-list {
  display: grid;
  gap: 8px;
  color: var(--muted);
}

.personal-permission-list span {
  display: flex;
  align-items: center;
  gap: 7px;
}

.personal-permission-list svg {
  width: 16px;
  color: var(--mint);
}

.personal-team-boundary {
  margin: 17px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--outline);
  font-size: 12px;
}

.personal-team-content-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.personal-team-list-card article {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 13px 0;
  border-top: 1px solid var(--outline);
}

.personal-team-list-card article:first-of-type {
  margin-top: 10px;
}

.personal-list-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  color: var(--cyan);
  background: rgba(125, 249, 255, .08);
}

.personal-team-list-card strong,
.personal-team-list-card small {
  display: block;
}

.personal-team-list-card small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}

.personal-team-empty-inline {
  display: grid;
  min-height: 90px;
  place-items: center;
  color: var(--muted);
}

.personal-team-inbox {
  display: grid;
  gap: 16px;
  margin-bottom: 18px;
  padding: 22px;
}

.personal-inbox-summary {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.personal-inbox-summary span {
  min-width: 118px;
  display: grid;
  gap: 3px;
  padding: 12px 14px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  background: rgba(10, 30, 52, .52);
}

.personal-inbox-summary strong {
  color: var(--mint);
  font-size: 22px;
}

.personal-inbox-summary small {
  color: var(--muted);
}

.personal-inbox-list {
  display: grid;
  gap: 10px;
}

.personal-inbox-list article {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 13px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  background: rgba(5, 17, 31, .48);
}

.personal-inbox-list article.unread {
  border-color: rgba(125, 249, 255, .34);
}

.personal-inbox-list article.done {
  opacity: .72;
}

.personal-inbox-list strong,
.personal-inbox-list small,
.personal-inbox-list p {
  display: block;
  min-width: 0;
}

.personal-inbox-list small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}

.personal-inbox-list p {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.6;
}

.personal-inbox-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.personal-team-empty-icon {
  color: var(--cyan);
}

.personal-team-empty h2 {
  margin: 0;
  color: var(--text);
}

.personal-team-empty p {
  max-width: 460px;
  margin: 0;
  text-align: center;
  line-height: 1.7;
}

.personal-team-discover {
  margin-top: 18px;
}

.personal-team-discover > header {
  margin-bottom: 18px;
}

.personal-team-search-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 9px;
}

.personal-team-search-input,
.personal-team-code-input {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  padding: 0 12px;
  background: rgba(5, 17, 31, .72);
}

.personal-team-search-input input,
.personal-team-code-input input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  padding: 12px 0;
}

.personal-team-discover-list {
  display: grid;
  gap: 9px;
  margin-top: 16px;
}

.personal-team-discover-list article {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--outline);
  border-radius: 8px;
}

.personal-team-discover-list article strong,
.personal-team-discover-list article small,
.personal-team-discover-list article p {
  display: block;
}

.personal-team-discover-list article small,
.personal-team-discover-list article p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 11px;
}

.personal-team-result-actions {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

@media (min-width: 681px) {
  .personal-team-result-actions {
    flex-direction: row;
    flex-wrap: wrap;
  }
}

.personal-team-modal-form {
  min-width: min(460px, 76vw);
}

.personal-upload-mode {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--outline);
}

.personal-selected-material {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid rgba(125, 249, 255, .26);
  border-radius: 8px;
  background: rgba(125, 249, 255, .06);
}

.personal-selected-material small {
  color: var(--muted);
}

.personal-team-target,
.personal-team-modal-intro {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--muted);
  line-height: 1.6;
}

.personal-team-target strong,
.personal-team-target small {
  display: block;
}

.personal-team-target small {
  margin-top: 4px;
  color: var(--muted);
}

.personal-score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 980px) {
  .personal-team-layout {
    grid-template-columns: 1fr;
  }

  .personal-team-list {
    position: static;
  }

  .personal-team-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .personal-team-heading,
  .personal-team-summary > header,
  .personal-permission-layout,
  .personal-team-heading-actions {
    display: grid;
  }

  .personal-team-heading h1 {
    font-size: 28px;
  }

  .personal-team-content-grid,
  .personal-team-stat-grid,
  .personal-team-search-form,
  .personal-team-discover-list article {
    grid-template-columns: 1fr;
  }

  .personal-team-status {
    text-align: left;
  }

  .personal-team-discover-list article .button {
    width: auto;
  }

  .personal-team-result-actions {
    flex-direction: column;
    width: 100%;
  }

  .personal-team-modal-form {
    min-width: 0;
  }
}
</style>
