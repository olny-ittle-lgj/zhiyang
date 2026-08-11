<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Archive,
  BarChart3,
  BookOpen,
  BrainCircuit,
  Check,
  CircleDollarSign,
  ClipboardList,
  Database,
  Download,
  FilePlus2,
  FileText,
  Link2,
  List,
  LockKeyhole,
  LogOut,
  MessageSquareText,
  Play,
  Plus,
  RefreshCw,
  ReceiptText,
  RotateCcw,
  Save,
  Settings,
  ShieldCheck,
  StopCircle,
  Tag,
  Trash2,
  Trophy,
  Upload,
  UserPlus,
  UsersRound,
  X,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import {
  activeTeamId,
  api,
  apiBlob,
  clearToken,
  formatBytes,
  setActiveTeamId,
  token,
} from '../api'
import ModalDialog from '../components/ModalDialog.vue'

const router = useRouter()
const teams = ref([])
const selectedTeamId = ref(activeTeamId())
const workspace = ref(null)
const members = ref([])
const invites = ref([])
const joinRequests = ref([])
const libraries = ref([])
const materials = ref([])
const shares = ref([])
const qaArchives = ref([])
const qaResult = ref(null)
const selectedQaArchive = ref(null)
const qaLoading = ref(false)
const qaQuota = ref(null)
const qaFilters = ref({ q: '', mine: false, lib_id: '' })
const evolution = ref([])
const rank = ref([])
const achievements = ref([])
const activities = ref([])
const stats = ref(null)
const graph = ref(null)
const logs = ref([])
const teamCurrency = ref(null)
const currencyTransactions = ref([])
const settingsForm = ref(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const tab = ref('overview')
const rankPeriod = ref('all')
const selectedMaterial = ref(null)
const comments = ref([])
const versions = ref([])
const selectedFile = ref(null)
const materialFileInput = ref(null)
const commentText = ref('')
const personalMaterials = ref([])
const personalMaterialsLoading = ref(false)

const teamForm = ref({ name: '', description: '', team_type: 'learning' })
const inviteForm = ref({ role: 'viewer', expires_days: 7 })
const libraryForm = ref({
  name: '',
  description: '',
  category: '通用',
  visibility: 'team',
  permission_mode: 'team_editors',
})
const materialForm = ref({ lib_id: '', name: '', content: '', tags: '' })
const personalImportForm = ref({ lib_id: '', material_id: '', name: '', tags: '' })
const urlForm = ref({ lib_id: '', name: '', url: '', content: '', tags: '' })
const knowledgeModal = ref(null) // null | 'create-library' | 'write-material' | 'upload-file' | 'import-personal' | 'url-material'
function openKnowledgeModal(name) { knowledgeModal.value = name }
function closeKnowledgeModal() { knowledgeModal.value = null }
const libraryEditForm = ref({ name: '', category: '', description: '' })
const editingLibrary = ref(null) // 正在编辑的知识库对象
function openLibraryEdit(lib) {
  editingLibrary.value = lib
  libraryEditForm.value = { name: lib.name, category: lib.category || '通用', description: lib.description || '' }
}
function closeLibraryEdit() { editingLibrary.value = null }

// Generic confirm dialog
const confirmDialog = ref({ open: false, message: '', title: '确认操作', onConfirm: null })
function showConfirm(message, onConfirm, title = '确认操作') {
  confirmDialog.value = { open: true, message, title, onConfirm }
}
function closeConfirm() { confirmDialog.value.open = false }
function execConfirm() {
  if (confirmDialog.value.onConfirm) confirmDialog.value.onConfirm()
  closeConfirm()
}

// Library access modal (设置成员权限)
const accessForm = ref({ member_id: '', access: 'read' })
const editingAccessLibrary = ref(null)
function openLibraryAccessModal(lib) {
  editingAccessLibrary.value = lib
  accessForm.value = { member_id: '', access: 'read' }
}
function closeLibraryAccessModal() { editingAccessLibrary.value = null }

// Transfer materials modal (移交素材)
const transferForm = ref({ target_user_id: '' })
const transferringMember = ref(null)
function openTransferModal(member) {
  transferringMember.value = member
  transferForm.value = { target_user_id: '' }
}
function closeTransferModal() { transferringMember.value = null }
const shareForm = ref({
  name: '',
  description: '',
  lib_id: '',
  scope: 'team',
  expires_days: 30,
  password: '',
  watermark: true,
  member_ids: '',
})
const qaForm = ref({ question: '', lib_ids: [] })
const evolutionForm = ref({
  lib_id: '',
  mode: 'manual',
  visibility: 'team',
  review_strategy: 'owner_final',
  summary: '',
})
const scoreForm = ref({ game: 'flashcard', score: 120, correct: 8, total: 10 })
const activityForm = ref({
  name: '',
  activity_type: 'contest',
  starts_at: '',
  ends_at: '',
  reward: '',
})
const gameSocket = ref(null)
const wsConnected = ref(false)
const multiplayerUsers = ref([])
const materialEdit = ref({ name: '', content: '', tags: '' })

const tabs = [
  { id: 'teams', icon: List, label: '我的团队', hint: '团队空间与创建' },
  { id: 'overview', icon: BarChart3, label: '总览', hint: '团队核心数据' },
  { id: 'currency', icon: CircleDollarSign, label: '团队资金', hint: '公共资金池与流水' },
  { id: 'members', icon: UserPlus, label: '成员管理', hint: '角色、申请与邀请' },
  { id: 'knowledge', icon: Database, label: '协作知识库', hint: '素材、版本与批注' },
  { id: 'shares', icon: Link2, label: '团队分享', hint: '内部与外部访问' },
  { id: 'qa', icon: MessageSquareText, label: '团队问答', hint: '授权范围内检索' },
  { id: 'evolution', icon: BrainCircuit, label: '协同进化', hint: '审核与重新生成' },
  { id: 'games', icon: Trophy, label: '游戏与活动', hint: '榜单、竞赛与成就' },
  { id: 'stats', icon: BarChart3, label: '统计导出', hint: '成员、图谱与报表' },
  { id: 'settings', icon: Settings, label: '团队设置', hint: '策略、安全与备份' },
]

const teamTypeLabels = {
  learning: '学习小组',
  research: '科研课题组',
  studio: '创作工作室',
}
const roleLabels = {
  owner: '负责人',
  admin: '管理员',
  editor: '编辑成员',
  viewer: '只读成员',
}
const statusLabels = {
  pending_review: '待审核',
  needs_changes: '需要修改',
  completed: '已完成',
  processing: '处理中',
  ready: '已就绪',
  planned: '已规划',
  published: '已发布',
  running: '进行中',
  ended: '已结束',
  cancelled: '已取消',
}

const selectedTeam = computed(() => teams.value.find((item) => String(item.id) === String(selectedTeamId.value)))
const team = computed(() => workspace.value?.team || selectedTeam.value || null)
const counts = computed(() => workspace.value?.counts || selectedTeam.value?.counts || {})
const queueInfo = computed(() => workspace.value?.queues || {})
const canManage = computed(() => ['owner', 'admin'].includes(team.value?.role))
const isOwner = computed(() => team.value?.role === 'owner')
const canEdit = computed(() => ['owner', 'admin', 'editor'].includes(team.value?.role))

function toast(message) {
  notice.value = message
  window.setTimeout(() => {
    if (notice.value === message) notice.value = ''
  }, 2800)
}

function normalizeId(value) {
  return value ? Number(value) : null
}

function splitTags(value) {
  return String(value || '')
    .replaceAll('，', ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function statusLabel(value) {
  return statusLabels[value] || value || '未标记'
}

function formatDate(value) {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function loadTeams() {
  const payload = await api('/teams')
  teams.value = payload.teams || []
  if (teams.value.length && !teams.value.some((item) => String(item.id) === String(selectedTeamId.value))) {
    selectedTeamId.value = String(teams.value[0].id)
    setActiveTeamId(selectedTeamId.value)
  }
  if (!teams.value.length) selectedTeamId.value = ''
}

async function loadWorkspace() {
  if (!selectedTeamId.value) {
    workspace.value = null
    return
  }
  workspace.value = await api(`/teams/${selectedTeamId.value}/workspace`)
  libraries.value = workspace.value.libraries || []
  materials.value = workspace.value.materials || []
  settingsForm.value = {
    storage_quota: workspace.value.team.storage_quota || 1073741824,
    daily_deepseek_quota: workspace.value.team.api_quota || 1000,
    ...workspace.value.team.settings,
  }
}

async function loadTabData() {
  if (!selectedTeamId.value || tab.value === 'teams') return
  const id = selectedTeamId.value
  if (tab.value === 'members') {
    members.value = (await api(`/teams/${id}/members`)).items || []
    invites.value = (await api(`/teams/${id}/invites`).catch(() => ({ items: [] }))).items || []
    joinRequests.value = (await api(`/teams/${id}/join-requests`).catch(() => ({ items: [] }))).items || []
  }
  if (tab.value === 'knowledge') {
    libraries.value = (await api(`/teams/${id}/libraries`)).items || []
    materials.value = (await api(`/teams/${id}/materials`)).items || []
    await loadPersonalMaterials()
  }
  if (tab.value === 'shares') shares.value = (await api(`/teams/${id}/shares`)).items || []
  if (tab.value === 'qa') await loadQAArchive()
  if (tab.value === 'evolution') evolution.value = (await api(`/teams/${id}/evolution`)).items || []
  if (tab.value === 'games') {
    const payload = await api(`/teams/${id}/games/rank?period=${rankPeriod.value}`)
    rank.value = payload.items || []
    activities.value = (await api(`/teams/${id}/activities`)).items || []
    achievements.value = (await api(`/teams/${id}/games/achievements`)).items || []
    connectGameWebSocket()
  }
  if (tab.value === 'stats') {
    stats.value = await api(`/teams/${id}/stats`)
    graph.value = await api(`/teams/${id}/graph`)
  }
  if (tab.value === 'settings') {
    settingsForm.value = (await api(`/teams/${id}/settings`)).settings
    logs.value = (await api(`/teams/${id}/logs`)).items || []
  }
  if (tab.value === 'currency') {
    teamCurrency.value = await api(`/teams/${id}/currency`)
    currencyTransactions.value = (await api(`/teams/${id}/currency/transactions?limit=100`)).items || []
  }
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    await loadTeams()
    await loadWorkspace()
    await loadTabData()
  } catch (err) {
    error.value = err?.message || '团队端加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function changeTab(next) {
  if (tab.value === 'games') disconnectGameWebSocket()
  tab.value = next
  error.value = ''
  try {
    await loadTabData()
  } catch (err) {
    error.value = err?.message || '模块数据加载失败'
  }
}

async function selectTeam(id) {
  selectedTeamId.value = String(id)
  setActiveTeamId(selectedTeamId.value)
  tab.value = 'overview'
  await reload()
}

async function createTeam() {
  if (!teamForm.value.name.trim()) return
  saving.value = true
  try {
    const created = await api('/teams', { method: 'POST', body: teamForm.value })
    teamForm.value = { name: '', description: '', team_type: 'learning' }
    selectedTeamId.value = String(created.id)
    setActiveTeamId(selectedTeamId.value)
    await reload()
    toast('团队已创建，默认知识库已准备好')
  } catch (err) {
    error.value = err?.message || '创建团队失败'
  } finally {
    saving.value = false
  }
}

async function createInvite() {
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/invites`, { method: 'POST', body: inviteForm.value })
    await loadTabData()
    toast('邀请码已生成，成员加入后需要负责人审核')
  } catch (err) {
    error.value = err?.message || '生成邀请码失败'
  } finally {
    saving.value = false
  }
}

function revokeInvite(invite) {
  showConfirm(`确定停用邀请码 ${invite.code} 吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/invites/${invite.id}`, { method: 'DELETE' })
      await loadTabData()
      toast('邀请码已停用')
    } catch (err) {
      error.value = err?.message || '停用邀请码失败'
    }
  })
}

async function reviewJoinRequest(item, decision) {
  try {
    await api(`/teams/${selectedTeamId.value}/join-requests/${item.id}`, {
      method: 'PATCH',
      body: { decision, role: item.requested_role || 'viewer', note: decision === 'approved' ? '团队审核通过' : '暂不符合团队加入条件' },
    })
    await loadTabData()
    await loadWorkspace()
    toast(decision === 'approved' ? '加入申请已通过' : '加入申请已拒绝')
  } catch (err) {
    error.value = err?.message || '审核加入申请失败'
  }
}

async function saveTransfer() {
  if (!transferringMember.value) return
  saving.value = true
  try {
    const body = transferForm.value.target_user_id.trim() ? { target_user_id: Number(transferForm.value.target_user_id.trim()) } : {}
    await api(`/teams/${selectedTeamId.value}/members/${transferringMember.value.user_id}/transfer`, { method: 'POST', body })
    await loadWorkspace()
    await loadTabData()
    closeTransferModal()
    toast('成员素材已完成移交')
  } catch (err) {
    error.value = err?.message || '移交成员素材失败'
  } finally {
    saving.value = false
  }
}

async function updateMember(member) {
  try {
    await api(`/teams/${selectedTeamId.value}/members/${member.user_id}`, {
      method: 'PATCH',
      body: { role: member.role, status: member.status },
    })
    await loadTabData()
    toast('成员权限已更新')
  } catch (err) {
    error.value = err?.message || '更新成员权限失败'
  }
}

function removeMember(member) {
  showConfirm(`确定移出成员「${member.nickname}」吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/members/${member.user_id}`, { method: 'DELETE' })
      await loadTabData()
      await loadWorkspace()
      toast('成员已移出团队')
    } catch (err) {
      error.value = err?.message || '移出成员失败'
    }
  })
}

async function createLibrary() {
  if (!libraryForm.value.name.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/libraries`, { method: 'POST', body: libraryForm.value })
    libraryForm.value = { name: '', description: '', category: '通用', visibility: 'team', permission_mode: 'team_editors' }
    await loadWorkspace()
    await loadTabData()
    closeKnowledgeModal()
    toast('团队知识库已创建')
  } catch (err) {
    error.value = err?.message || '创建知识库失败'
  } finally {
    saving.value = false
  }
}

async function saveLibraryEdit() {
  if (!editingLibrary.value || !libraryEditForm.value.name.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/libraries/${editingLibrary.value.id}`, {
      method: 'PATCH',
      body: {
        name: libraryEditForm.value.name.trim(),
        category: libraryEditForm.value.category.trim(),
        description: libraryEditForm.value.description.trim(),
      },
    })
    await loadWorkspace()
    await loadTabData()
    closeLibraryEdit()
    toast('知识库信息已更新')
  } catch (err) {
    error.value = err?.message || '更新知识库失败'
  } finally {
    saving.value = false
  }
}

function deleteLibrary(lib) {
  showConfirm(`确定删除知识库「${lib.name}」吗？素材会保留为未归属。`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/libraries/${lib.id}`, { method: 'DELETE' })
      await loadWorkspace()
      await loadTabData()
      toast('知识库已删除，素材已保留')
    } catch (err) {
      error.value = err?.message || '删除知识库失败'
    }
  })
}

async function saveLibraryAccess() {
  if (!editingAccessLibrary.value || !accessForm.value.member_id.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/libraries/${editingAccessLibrary.value.id}/members/${Number(accessForm.value.member_id.trim())}`, {
      method: 'PUT',
      body: { access: accessForm.value.access === 'write' ? 'write' : 'read' },
    })
    await loadWorkspace()
    await loadTabData()
    closeLibraryAccessModal()
    toast('知识库成员权限已更新')
  } catch (err) {
    error.value = err?.message || '更新知识库权限失败'
  } finally {
    saving.value = false
  }
}

function removeLibraryAccess(lib, permission) {
  showConfirm(`确定移除 ${permission.nickname} 的自定义权限吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/libraries/${lib.id}/members/${permission.user_id}`, { method: 'DELETE' })
      await loadWorkspace()
      await loadTabData()
      toast('知识库自定义权限已移除')
    } catch (err) {
      error.value = err?.message || '移除知识库权限失败'
    }
  })
}

async function createMaterial() {
  if (!materialForm.value.name.trim() || !materialForm.value.content.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials`, {
      method: 'POST',
      body: {
        lib_id: normalizeId(materialForm.value.lib_id),
        name: materialForm.value.name.trim(),
        content: materialForm.value.content.trim(),
        tags: splitTags(materialForm.value.tags),
        kind: 'Markdown',
      },
    })
    materialForm.value = { lib_id: '', name: '', content: '', tags: '' }
    await loadWorkspace()
    await loadTabData()
    closeKnowledgeModal()
    toast('团队素材已写入知识库')
  } catch (err) {
    error.value = err?.message || '创建团队素材失败'
  } finally {
    saving.value = false
  }
}

async function loadPersonalMaterials() {
  personalMaterialsLoading.value = true
  try {
    const payload = await api('/materials')
    personalMaterials.value = Array.isArray(payload) ? payload : payload.items || []
    if (!personalMaterials.value.some((item) => String(item.id) === String(personalImportForm.value.material_id))) {
      personalImportForm.value.material_id = ''
    }
  } catch (err) {
    error.value = err?.message || '个人素材加载失败'
  } finally {
    personalMaterialsLoading.value = false
  }
}

async function importPersonalMaterial() {
  if (!personalImportForm.value.material_id) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials/import-personal`, {
      method: 'POST',
      body: {
        material_id: Number(personalImportForm.value.material_id),
        lib_id: normalizeId(personalImportForm.value.lib_id),
        name: personalImportForm.value.name.trim() || null,
        tags: splitTags(personalImportForm.value.tags),
      },
    })
    personalImportForm.value = { lib_id: '', material_id: '', name: '', tags: '' }
    await loadWorkspace()
    await loadTabData()
    closeKnowledgeModal()
    toast('个人文件已导入团队素材库')
  } catch (err) {
    error.value = err?.message || '个人文件导入失败'
  } finally {
    saving.value = false
  }
}

function chooseFile(event) {
  selectedFile.value = event.target.files?.[0] || null
}

async function uploadMaterial() {
  if (!selectedFile.value) return
  const form = new FormData()
  form.append('file', selectedFile.value)
  form.append('lib_id', materialForm.value.lib_id || '')
  form.append('name', materialForm.value.name || selectedFile.value.name)
  form.append('tags', materialForm.value.tags)
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials/upload`, { method: 'POST', body: form })
    selectedFile.value = null
    materialForm.value = { lib_id: '', name: '', content: '', tags: '' }
    if (materialFileInput.value) materialFileInput.value.value = ''
    await loadWorkspace()
    await loadTabData()
    closeKnowledgeModal()
    toast('素材已进入团队异步处理队列')
  } catch (err) {
    error.value = err?.message || '上传团队素材失败'
  } finally {
    saving.value = false
  }
}

async function createUrlMaterial() {
  if (!urlForm.value.name.trim() || !urlForm.value.url.trim()) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/materials/url`, {
      method: 'POST',
      body: {
        ...urlForm.value,
        lib_id: normalizeId(urlForm.value.lib_id),
        tags: splitTags(urlForm.value.tags),
      },
    })
    urlForm.value = { lib_id: '', name: '', url: '', content: '', tags: '' }
    await loadWorkspace()
    await loadTabData()
    closeKnowledgeModal()
    toast('网页链接已纳入团队素材')
  } catch (err) {
    error.value = err?.message || '保存网页素材失败'
  } finally {
    saving.value = false
  }
}

async function openMaterial(item) {
  selectedMaterial.value = item
  materialEdit.value = { name: item.name, content: item.content || '', tags: (item.tags || []).join(',') }
  try {
    const [commentPayload, versionPayload] = await Promise.all([
      api(`/teams/${selectedTeamId.value}/materials/${item.id}/comments`),
      api(`/teams/${selectedTeamId.value}/materials/${item.id}/versions`),
    ])
    comments.value = commentPayload.items || []
    versions.value = versionPayload.items || []
  } catch (err) {
    error.value = err?.message || '素材详情加载失败'
  }
}

async function saveMaterialEdit() {
  if (!selectedMaterial.value) return
  try {
    await api(`/teams/${selectedTeamId.value}/materials/${selectedMaterial.value.id}`, {
      method: 'PATCH',
      body: { ...materialEdit.value, tags: splitTags(materialEdit.value.tags), note: '团队端编辑' },
    })
    await loadTabData()
    await loadWorkspace()
    await openMaterial(materials.value.find((item) => item.id === selectedMaterial.value.id) || selectedMaterial.value)
    toast('素材已保存并生成新版本')
  } catch (err) {
    error.value = err?.message || '保存素材失败'
  }
}

function deleteMaterial() {
  if (!selectedMaterial.value) return
  showConfirm(`确定删除团队素材「${selectedMaterial.value.name}」吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/materials/${selectedMaterial.value.id}`, { method: 'DELETE' })
      selectedMaterial.value = null
      comments.value = []
      versions.value = []
      await loadWorkspace()
      await loadTabData()
      toast('团队素材已删除')
    } catch (err) {
      error.value = err?.message || '删除素材失败'
    }
  })
}

async function addComment() {
  if (!selectedMaterial.value || !commentText.value.trim()) return
  try {
    await api(`/teams/${selectedTeamId.value}/materials/${selectedMaterial.value.id}/comments`, {
      method: 'POST',
      body: { body: commentText.value.trim() },
    })
    commentText.value = ''
    await openMaterial(selectedMaterial.value)
    toast('批注已添加')
  } catch (err) {
    error.value = err?.message || '添加批注失败'
  }
}

async function resolveComment(comment) {
  try {
    await api(`/teams/${selectedTeamId.value}/materials/${selectedMaterial.value.id}/comments/${comment.id}`, {
      method: 'PATCH',
      body: { resolved: !comment.resolved },
    })
    await openMaterial(selectedMaterial.value)
  } catch (err) {
    error.value = err?.message || '更新批注状态失败'
  }
}

async function createShare() {
  if (!shareForm.value.name.trim()) return
  try {
    await api(`/teams/${selectedTeamId.value}/shares`, {
      method: 'POST',
      body: {
        ...shareForm.value,
        lib_id: normalizeId(shareForm.value.lib_id),
        member_ids: shareForm.value.member_ids
          .split(',')
          .map((item) => Number(item.trim()))
          .filter(Boolean),
      },
    })
    shareForm.value = { name: '', description: '', lib_id: '', scope: 'team', expires_days: 30, password: '', watermark: true, member_ids: '' }
    await loadTabData()
    toast('团队分享链接已创建')
  } catch (err) {
    error.value = err?.message || '创建分享失败'
  }
}

function revokeShare(share) {
  showConfirm(`确定撤销团队分享「${share.name}」吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/shares/${share.id}`, { method: 'DELETE' })
      await loadTabData()
      await loadWorkspace()
      toast('团队分享已撤销')
    } catch (err) {
      error.value = err?.message || '撤销分享失败'
    }
  })
}

async function loadQAArchive() {
  if (!selectedTeamId.value) return
  const params = new URLSearchParams({ limit: '80' })
  if (qaFilters.value.q.trim()) params.set('q', qaFilters.value.q.trim())
  if (qaFilters.value.mine) params.set('mine', 'true')
  if (qaFilters.value.lib_id) params.set('lib_id', String(qaFilters.value.lib_id))
  const payload = await api(`/teams/${selectedTeamId.value}/qa/archive?${params.toString()}`)
  qaArchives.value = payload.items || []
  qaQuota.value = payload.quota || null
  if (selectedQaArchive.value && !qaArchives.value.some((item) => item.id === selectedQaArchive.value.id)) {
    selectedQaArchive.value = null
  }
}

async function askTeam() {
  if (!qaForm.value.question.trim()) return
  qaLoading.value = true
  error.value = ''
  try {
    const answer = await api(`/teams/${selectedTeamId.value}/qa`, {
      method: 'POST',
      body: {
        question: qaForm.value.question.trim(),
        lib_ids: qaForm.value.lib_ids.map(Number),
      },
    })
    qaResult.value = answer
    selectedQaArchive.value = answer
    qaArchives.value.unshift(answer)
    qaForm.value.question = ''
    qaQuota.value = answer.currency?.quota || qaQuota.value
    if (answer.currency?.wallet) {
      workspace.value = { ...workspace.value, currency: answer.currency.wallet }
    }
    toast(answer.source_count ? '团队问答已生成并归档' : '未检索到素材，已归档本次问题')
  } catch (err) {
    error.value = err?.message || '团队问答失败'
  } finally {
    qaLoading.value = false
  }
}

async function openQAArchive(item) {
  try {
    const detail = await api(`/teams/${selectedTeamId.value}/qa/archive/${item.id}`)
    selectedQaArchive.value = detail
    qaResult.value = detail
  } catch (err) {
    error.value = err?.message || '加载问答归档失败'
  }
}

function reuseQAArchive(item) {
  qaForm.value.question = item.question
  qaForm.value.lib_ids = [...(item.lib_ids || [])]
  selectedQaArchive.value = item
  toast('已复用归档问题，可调整后重新提问')
}

function deleteQAArchive(item) {
  showConfirm(`确定删除问答归档「${item.question}」吗？`, async () => {
    try {
      await api(`/teams/${selectedTeamId.value}/qa/archive/${item.id}`, { method: 'DELETE' })
      qaArchives.value = qaArchives.value.filter((archive) => archive.id !== item.id)
      if (selectedQaArchive.value?.id === item.id) selectedQaArchive.value = null
      if (qaResult.value?.id === item.id) qaResult.value = null
      await loadWorkspace()
      toast('问答归档已删除')
    } catch (err) {
      error.value = err?.message || '删除问答归档失败'
    }
  })
}

function qaLibraryLabel(item) {
  const ids = item?.lib_ids || []
  if (!ids.length) return '可访问全部知识库'
  const names = ids.map((id) => libraries.value.find((lib) => Number(lib.id) === Number(id))?.name).filter(Boolean)
  return names.length ? names.join('、') : `${ids.length} 个知识库`
}

function qaModeLabel(mode) {
  const labels = {
    'deepseek-team-rag': 'DeepSeek 团队 RAG',
    'team-local-rag': '本地团队检索',
    'team-local-rag-fallback': '本地兜底',
    'team-local-fallback': '本地归档',
    'team-no-match': '未命中',
  }
  return labels[mode] || mode || '已归档'
}

async function createEvolution() {
  try {
    await api(`/teams/${selectedTeamId.value}/evolution`, {
      method: 'POST',
      body: { ...evolutionForm.value, lib_id: normalizeId(evolutionForm.value.lib_id) },
    })
    evolutionForm.value.summary = ''
    await loadTabData()
    await loadWorkspace()
    toast('团队进化任务已创建')
  } catch (err) {
    error.value = err?.message || '创建进化任务失败'
  }
}

async function reviewTask(task, decision) {
  try {
    await api(`/teams/${selectedTeamId.value}/evolution/${task.id}/reviews`, {
      method: 'POST',
      body: { decision, feedback: decision === 'accepted' ? '通过团队审核' : '请根据团队反馈继续修改' },
    })
    await loadTabData()
    await loadWorkspace()
    toast('进化审核意见已记录')
  } catch (err) {
    error.value = err?.message || '提交进化审核失败'
  }
}

async function regenerateTask(task) {
  try {
    await api(`/teams/${selectedTeamId.value}/evolution/${task.id}/regenerate`, { method: 'POST' })
    await loadTabData()
    toast('已根据反馈重新生成审核任务')
  } catch (err) {
    error.value = err?.message || '重新生成失败'
  }
}

async function submitScore() {
  try {
    await api(`/teams/${selectedTeamId.value}/games/score`, { method: 'POST', body: scoreForm.value })
    await loadWorkspace()
    await loadTabData()
    toast('游戏成绩已同步到团队榜单')
  } catch (err) {
    error.value = err?.message || '提交游戏成绩失败'
  }
}

async function createActivity() {
  if (!activityForm.value.name.trim()) return
  try {
    await api(`/teams/${selectedTeamId.value}/activities`, { method: 'POST', body: activityForm.value })
    activityForm.value = { name: '', activity_type: 'contest', starts_at: '', ends_at: '', reward: '' }
    await loadTabData()
    toast('团队活动已创建')
  } catch (err) {
    error.value = err?.message || '创建活动失败'
  }
}

async function updateActivity(activity, status) {
  try {
    await api(`/teams/${selectedTeamId.value}/activities/${activity.id}`, {
      method: 'PATCH',
      body: { status },
    })
    await loadTabData()
    toast('活动状态已更新')
  } catch (err) {
    error.value = err?.message || '更新活动失败'
  }
}

async function changeRankPeriod(period) {
  rankPeriod.value = period
  if (tab.value === 'games') await loadTabData()
}

function connectGameWebSocket() {
  if (gameSocket.value) return
  if (!team.value?.settings?.game_multiplayer_enabled) return
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/teams/${selectedTeamId.value}/games/ws?token=${token()}`
  const socket = new WebSocket(wsUrl)
  gameSocket.value = socket
  socket.onopen = () => { wsConnected.value = true }
  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'connected') {
        if (!multiplayerUsers.value.find(u => u.user_id === msg.user_id)) {
          multiplayerUsers.value = [...multiplayerUsers.value, { user_id: msg.user_id, online: true }]
        }
      } else if (msg.type === 'game_event') {
        if (!multiplayerUsers.value.find(u => u.user_id === msg.user_id)) {
          multiplayerUsers.value = [...multiplayerUsers.value, { user_id: msg.user_id, online: true }]
        }
      }
    } catch { /* ignore malformed messages */ }
  }
  socket.onclose = () => { wsConnected.value = false; multiplayerUsers.value = [] }
  socket.onerror = () => { wsConnected.value = false; disconnectGameWebSocket() }
}

function disconnectGameWebSocket() {
  if (gameSocket.value) {
    gameSocket.value.close()
    gameSocket.value = null
  }
  wsConnected.value = false
  multiplayerUsers.value = []
}

async function saveSettings() {
  if (!settingsForm.value) return
  saving.value = true
  try {
    await api(`/teams/${selectedTeamId.value}/settings`, { method: 'PUT', body: settingsForm.value })
    await reload()
    toast('团队设置已保存')
  } catch (err) {
    error.value = err?.message || '保存团队设置失败'
  } finally {
    saving.value = false
  }
}

async function updateLifecycle(status) {
  try {
    await api(`/teams/${selectedTeamId.value}`, { method: 'PATCH', body: { status } })
    await reload()
    toast(status === 'archived' ? '团队已归档' : '团队已冻结')
  } catch (err) {
    error.value = err?.message || '更新团队状态失败'
  }
}

async function restoreTeam() {
  try {
    await api(`/teams/${selectedTeamId.value}/restore`, { method: 'POST' })
    await reload()
    toast('团队已恢复')
  } catch (err) {
    error.value = err?.message || '恢复团队失败'
  }
}

function dissolveTeam() {
  showConfirm('解散团队会删除团队数据、知识库和协作记录，确定继续吗？', async () => {
    try {
      await api(`/teams/${selectedTeamId.value}?confirm=true`, { method: 'DELETE' })
      setActiveTeamId('')
      selectedTeamId.value = ''
      await reload()
      toast('团队已解散')
    } catch (err) {
      error.value = err?.message || '解散团队失败'
    }
  }, '解散团队')
}

async function downloadExport(kind) {
  try {
    const blob = await apiBlob(`/teams/${selectedTeamId.value}/exports/${kind}`)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `team-${selectedTeamId.value}-${kind}.xlsx`
    anchor.click()
    URL.revokeObjectURL(url)
    toast('Excel 报表已导出')
  } catch (err) {
    error.value = err?.message || '导出报表失败'
  }
}

async function downloadBackup() {
  try {
    const blob = await apiBlob(`/teams/${selectedTeamId.value}/backup`)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `team-${selectedTeamId.value}-backup.zip`
    anchor.click()
    URL.revokeObjectURL(url)
    toast('团队备份包已导出')
  } catch (err) {
    error.value = err?.message || '导出团队备份失败'
  }
}

function logoutTeam() {
  clearToken()
  router.push('/login')
}

onMounted(reload)
onUnmounted(() => { disconnectGameWebSocket() })
</script>

<template>
  <div class="team-console-shell">
    <header class="team-console-topbar">
      <button class="team-console-brand" type="button" @click="reload">
        <img src="/zhiyan_logo/screen.png" alt="知衍标识" />
        <span><strong>知衍团队端</strong><small>Team Knowledge Console</small></span>
      </button>
      <div class="team-console-actions">
        <button class="button secondary" :disabled="loading" @click="reload"><RefreshCw />刷新</button>
        <button class="button ghost" type="button" @click="logoutTeam"><LogOut />退出团队端</button>
      </div>
    </header>

    <section class="page-wrap team-page">
      <header class="team-hero">
        <div>
          <span class="eyebrow"><UsersRound /> 团队端独立工作台</span>
          <h1>团队协作、知识进化与数据治理</h1>
          <p>团队成员、知识库、素材处理、问答归档、协同审核、游戏活动、统计导出和安全设置在同一个闭环中完成。</p>
        </div>
        <div class="team-hero-badges">
          <span>独立团队空间</span>
          <span>角色分级</span>
          <span>数据隔离</span>
        </div>
      </header>

      <p v-if="error" class="team-alert error">{{ error }}</p>
      <p v-if="notice" class="team-alert">{{ notice }}</p>

      <div class="team-layout">
        <aside class="team-sidebar panel">
          <header>
            <strong>团队导航</strong>
            <small>{{ teams.length }} 个空间</small>
          </header>
          <div class="team-module-divider"></div>
          <nav class="team-module-nav" aria-label="团队端模块">
            <button
              v-for="item in tabs"
              :key="item.id"
              :class="{ active: tab === item.id }"
              :aria-label="item.label"
              :title="item.label"
              :disabled="(['members', 'settings'].includes(item.id) && !canManage) || (item.id === 'evolution' && !canEdit)"
              @click="changeTab(item.id)"
            >
              <component :is="item.icon" :size="21" />
              <span class="team-module-tooltip"><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span>
            </button>
          </nav>
        </aside>

        <main v-if="loading" class="panel team-empty">正在加载团队空间...</main>
        <main v-else class="team-main">
          <section v-if="selectedTeam && tab !== 'teams'" class="team-title panel">
            <div>
              <span>{{ roleLabels[team?.role] || team?.role }}</span>
              <h2>{{ team?.name }}</h2>
              <p>{{ team?.description || '这个团队还没有填写简介。' }}</p>
            </div>
            <div class="team-title-metrics">
              <div class="team-quota">
                <small>存储占用</small>
                <strong>{{ formatBytes(counts.storage_used) }}</strong>
                <span>/ {{ formatBytes(team?.storage_quota) }}</span>
              </div>
              <button v-if="tab !== 'currency'" class="team-fund-mini" type="button" @click="changeTab('currency')">
                <CircleDollarSign />
                <span><small>团队公共资金</small><strong>{{ (workspace?.currency?.knowledge_balance ?? selectedTeam?.currency?.knowledge_balance ?? 0).toLocaleString() }} 学识币</strong></span>
                <b>{{ (workspace?.currency?.truth_balance ?? selectedTeam?.currency?.truth_balance ?? 0).toLocaleString() }} 真知晶</b>
              </button>
            </div>
          </section>
          <section v-else-if="tab !== 'teams'" class="panel team-empty">请先在“我的团队”中选择一个团队空间。</section>

          <section v-if="tab === 'teams'" class="team-section team-directory">
            <section class="panel team-directory-list">
              <header class="team-content-heading">
                <div>
                  <span class="eyebrow"><List /> Team Spaces</span>
                  <h2>我的团队</h2>
                  <p>团队端与个人端同等独立，只有在团队端登录后才能进行管理和进阶协作。</p>
                </div>
                <span>{{ teams.length }} 个团队空间</span>
              </header>
              <div class="team-directory-grid">
                <button v-for="item in teams" :key="item.id" class="team-directory-card" :class="{ active: String(item.id) === String(selectedTeamId) }" @click="selectTeam(item.id)">
                  <span>{{ item.name.slice(0, 1) }}</span>
                  <strong>{{ item.name }}</strong>
                  <small>{{ roleLabels[item.role] || item.role }} · {{ item.counts?.libraries || 0 }} 个知识库 · {{ item.counts?.members || 0 }} 名成员</small>
                </button>
              </div>
              <div v-if="!teams.length" class="team-empty-inline">暂无已加入团队空间。</div>
            </section>
            <section class="panel team-form-panel team-create-panel">
              <header><strong>创建团队</strong><small>自动生成默认协作知识库</small></header>
              <form @submit.prevent="createTeam">
                <input v-model="teamForm.name" placeholder="团队名称" />
                <select v-model="teamForm.team_type">
                  <option value="learning">学习小组</option>
                  <option value="research">科研课题组</option>
                  <option value="studio">创作工作室</option>
                </select>
                <textarea v-model="teamForm.description" rows="4" placeholder="团队简介"></textarea>
                <button class="button primary" :disabled="saving"><Plus />创建团队</button>
              </form>
            </section>
          </section>

          <template v-if="selectedTeam">
            <section v-if="tab === 'overview'" class="team-section">
              <div class="team-stat-grid">
                <article><UsersRound /><span>成员</span><strong>{{ counts.members || 0 }}</strong></article>
                <article><BookOpen /><span>知识库</span><strong>{{ counts.libraries || 0 }}</strong></article>
                <article><ClipboardList /><span>素材</span><strong>{{ counts.materials || 0 }}</strong></article>
                <article><ShieldCheck /><span>待审核</span><strong>{{ counts.pending_reviews || 0 }}</strong></article>
              </div>
              <div class="team-two-col">
                <section class="panel team-list-panel">
                  <header><strong>团队处理队列</strong><small>RabbitMQ / MCP / 沙箱路由</small></header>
                  <article><Activity /><span><b>{{ queueInfo.media }}</b><small>文档、图片、视频入库</small></span></article>
                  <article><BrainCircuit /><span><b>{{ queueInfo.evolution }}</b><small>团队知识进化任务</small></span></article>
                  <article><LockKeyhole /><span><b>{{ queueInfo.sandbox }}</b><small>游戏题目沙箱校验</small></span></article>
                </section>
                <section class="panel team-list-panel">
                  <header><strong>近期团队素材</strong><small>{{ materials.length }} 条</small></header>
                  <article v-for="item in materials.slice(0, 6)" :key="item.id" class="clickable-row" @click="tab = 'knowledge'; openMaterial(item)">
                    <FileText /><span><b>{{ item.name }}</b><small>{{ statusLabel(item.status) }} · {{ item.uploader?.nickname }}</small></span>
                  </article>
                </section>
              </div>
            </section>

            <section v-if="tab === 'currency'" class="team-section">
              <div class="team-currency-grid">
                <article class="team-currency-card knowledge">
                  <CircleDollarSign />
                  <span><small>团队公共资金池</small><strong>{{ (teamCurrency?.knowledge_balance || workspace?.currency?.knowledge_balance || 0).toLocaleString() }}</strong><b>学识币</b></span>
                </article>
                <article class="team-currency-card truth">
                  <ReceiptText />
                  <span><small>高价值任务储备</small><strong>{{ (teamCurrency?.truth_balance || workspace?.currency?.truth_balance || 0).toLocaleString() }}</strong><b>真知晶</b></span>
                </article>
              </div>
              <section class="panel team-list-panel">
                <header><strong>团队资金流水</strong><small>奖励进入公共池，消耗仅限管理员与负责人</small></header>
                <article v-for="item in currencyTransactions" :key="item.id">
                  <ArrowDownToLine v-if="item.amount > 0" />
                  <ArrowUpFromLine v-else />
                  <span><b>{{ item.reason || item.reason_code }}</b><small>{{ item.currency_label }} · {{ formatDate(item.created_at) }} · {{ item.reference_type || '团队操作' }}</small></span>
                  <strong :class="item.amount > 0 ? 'currency-in' : 'currency-out'">{{ item.amount > 0 ? '+' : '' }}{{ item.amount }}</strong>
                </article>
                <div v-if="!currencyTransactions.length" class="team-empty-inline">暂无团队资金流水。</div>
              </section>
            </section>

            <section v-if="tab === 'members'" class="team-section team-two-col">
              <section class="panel team-list-panel">
                <header><strong>成员与角色</strong><small>负责人 / 管理员 / 编辑 / 只读</small></header>
                <article v-for="member in members" :key="member.user_id" class="member-row">
                  <UsersRound />
                  <span><b>{{ member.nickname }}</b><small>{{ member.username }} · {{ member.status }}</small></span>
                  <select v-model="member.role" :disabled="!canManage || member.role === 'owner'" @change="updateMember(member)">
                    <option value="owner">负责人</option>
                    <option value="admin">管理员</option>
                    <option value="editor">编辑成员</option>
                    <option value="viewer">只读成员</option>
                  </select>
                  <button v-if="member.role !== 'owner'" class="icon-button" title="移交该成员素材" :disabled="!canManage" @click="openTransferModal(member)"><ArrowDownToLine /></button>
                  <button v-if="member.role !== 'owner'" class="icon-button danger" title="移出成员" :disabled="!canManage" @click="removeMember(member)"><Trash2 /></button>
                </article>
              </section>
              <section class="panel team-form-panel">
                <header><strong>邀请码与申请</strong><small>加入后由管理员审核</small></header>
                <form @submit.prevent="createInvite">
                  <select v-model="inviteForm.role">
                    <option value="editor">编辑成员</option>
                    <option value="viewer">只读成员</option>
                    <option v-if="isOwner" value="admin">管理员</option>
                  </select>
                  <input v-model.number="inviteForm.expires_days" type="number" min="1" max="3650" />
                  <button class="button primary" :disabled="!canManage || saving"><UserPlus />生成邀请码</button>
                </form>
                <div class="invite-list">
                  <span v-for="invite in invites" :key="invite.id"><b>{{ invite.code }}</b><small>{{ roleLabels[invite.role] }} · {{ invite.uses }} 次使用 · {{ invite.status }}</small><button class="icon-button danger" title="停用邀请码" :disabled="!canManage || invite.status !== 'active'" @click="revokeInvite(invite)"><X /></button></span>
                </div>
                <div class="subsection-heading"><strong>待审核申请</strong><small>{{ joinRequests.length }} 条</small></div>
                <article v-for="item in joinRequests" :key="item.id" class="request-row">
                  <span><b>{{ item.nickname }}</b><small>{{ item.message || '申请加入团队' }}</small></span>
                  <div class="row-actions">
                    <button class="icon-button success" title="通过" @click="reviewJoinRequest(item, 'approved')"><Check /></button>
                    <button class="icon-button danger" title="拒绝" @click="reviewJoinRequest(item, 'rejected')"><X /></button>
                  </div>
                </article>
                <div v-if="!joinRequests.length" class="team-empty-inline compact">暂无待审核申请</div>
              </section>
            </section>

            <ModalDialog v-if="transferringMember" title="移交成员素材" :close-disabled="saving" @close="closeTransferModal">
              <form class="stack-form" @submit.prevent="saveTransfer">
                <p class="tech-context">将「{{ transferringMember.nickname }}」的素材移交给其他成员或团队负责人。</p>
                <label>接收成员 ID（可选）</label>
                <input v-model="transferForm.target_user_id" placeholder="留空则移交给团队负责人" class="tech-input" />
                <div class="modal-actions"><button class="button ghost" type="button" @click="closeTransferModal">取消</button><button class="button secondary" type="submit" :disabled="!canManage || saving"><ArrowDownToLine />确认移交</button></div>
              </form>
            </ModalDialog>

            <section v-if="tab === 'knowledge'" class="team-section">
              <div class="knowledge-action-bar">
                <button class="button knowledge-action-btn" @click="openKnowledgeModal('create-library')"><Database /><span>新建知识库<small>创建独立数据集与权限</small></span></button>
                <button class="button knowledge-action-btn" @click="openKnowledgeModal('write-material')"><FilePlus2 /><span>手动写入素材<small>Markdown 直接入库</small></span></button>
                <button class="button knowledge-action-btn" @click="openKnowledgeModal('upload-file')"><Upload /><span>上传文件<small>文档 / 图片 / 视频</small></span></button>
                <button class="button knowledge-action-btn" @click="openKnowledgeModal('import-personal')"><ArrowDownToLine /><span>导入个人文件<small>复用个人端素材</small></span></button>
                <button class="button knowledge-action-btn" @click="openKnowledgeModal('url-material')"><Link2 /><span>网页链接入库<small>保存 URL 后续抓取</small></span></button>
              </div>

              <div class="team-two-col">
                <section class="panel team-list-panel">
                  <header><strong>知识库管理</strong><small>{{ libraries.length }} 个库</small></header>
                  <article v-for="lib in libraries" :key="lib.id" class="library-row">
                    <Database />
                    <span><b>{{ lib.name }}</b><small>{{ lib.category }} · {{ lib.permission_mode }} · {{ lib.member_permissions?.length || 0 }} 个自定义权限</small></span>
                    <div class="row-actions">
                      <button class="icon-button" title="编辑知识库" :disabled="!canManage" @click="openLibraryEdit(lib)"><Save /></button>
                      <button class="icon-button" title="设置成员权限" :disabled="!canManage" @click="openLibraryAccessModal(lib)"><LockKeyhole /></button>
                      <button class="icon-button danger" title="删除知识库" :disabled="!canManage" @click="deleteLibrary(lib)"><Trash2 /></button>
                    </div>
                    <div v-if="lib.member_permissions?.length" class="library-permission-list">
                      <button v-for="permission in lib.member_permissions" :key="`${lib.id}-${permission.user_id}`" type="button" @click="removeLibraryAccess(lib, permission)">
                        {{ permission.nickname }} · {{ permission.access }} ×
                      </button>
                    </div>
                  </article>
                  <div v-if="!libraries.length" class="team-empty-inline compact">暂无团队知识库，点击上方按钮创建。</div>
                </section>
              </div>

              <section class="panel team-list-panel wide-panel">
                <header><strong>团队素材</strong><small>{{ materials.length }} 条，可点击查看版本和批注</small></header>
                <article v-for="item in materials" :key="item.id" class="clickable-row" @click="openMaterial(item)">
                  <ClipboardList />
                  <span><b>{{ item.name }}</b><small>{{ item.lib_name || '未归属知识库' }} · {{ item.uploader?.nickname }} · {{ statusLabel(item.status) }} · {{ (item.tags || []).join(' / ') || '无标签' }}</small></span>
                  <span class="row-badge">{{ item.kind }}</span>
                </article>
              </section>
              <section v-if="selectedMaterial" class="panel team-material-detail">
                <header class="team-content-heading">
                  <div><span class="eyebrow"><FileText /> Material Detail</span><h3>{{ selectedMaterial.name }}</h3><p>{{ selectedMaterial.uploader?.nickname }} · {{ statusLabel(selectedMaterial.status) }}</p></div>
                  <div class="row-actions">
                    <button class="icon-button danger" title="删除素材" :disabled="!canEdit" @click="deleteMaterial"><Trash2 /></button>
                    <button class="icon-button" title="关闭详情" @click="selectedMaterial = null"><X /></button>
                  </div>
                </header>
                <div class="team-two-col">
                  <form class="team-form-panel" @submit.prevent="saveMaterialEdit">
                    <input v-model="materialEdit.name" placeholder="素材名称" />
                    <input v-model="materialEdit.tags" placeholder="标签" />
                    <textarea v-model="materialEdit.content" rows="8" placeholder="素材内容"></textarea>
                    <button class="button primary" :disabled="!canEdit"><Save />保存新版本</button>
                  </form>
                  <div class="team-list-panel">
                    <header><strong>批注</strong><small>{{ comments.length }} 条</small></header>
                    <form class="inline-form" @submit.prevent="addComment">
                      <input v-model="commentText" placeholder="写一条团队批注" />
                      <button class="icon-button" title="添加批注"><MessageSquareText /></button>
                    </form>
                    <article v-for="comment in comments" :key="comment.id" class="comment-row">
                      <span><b>{{ comment.nickname }}</b><small :class="{ resolved: comment.resolved }">{{ comment.body }}</small></span>
                      <button class="icon-button" :title="comment.resolved ? '重新打开' : '标记已解决'" @click="resolveComment(comment)"><Check /></button>
                    </article>
                    <div class="subsection-heading"><strong>版本快照</strong><small>{{ versions.length }} 个版本</small></div>
                    <article v-for="version in versions" :key="version.id" class="version-row"><span><b>v{{ version.version }}</b><small>{{ version.note }} · {{ formatDate(version.created_at) }}</small></span></article>
                  </div>
                </div>
              </section>

              <!-- Modals -->
              <ModalDialog v-if="knowledgeModal === 'create-library'" title="新建知识库" :close-disabled="saving" @close="closeKnowledgeModal">
                <form class="stack-form" @submit.prevent="createLibrary">
                  <label>知识库名称<input v-model="libraryForm.name" placeholder="例如：前端技术文档" /></label>
                  <label>分类<input v-model="libraryForm.category" placeholder="例如：前端开发" /></label>
                  <label>权限模式<select v-model="libraryForm.permission_mode"><option value="team_editors">编辑成员可写</option><option value="admins_only">仅管理员</option><option value="custom">自定义成员权限</option></select></label>
                  <label>说明<textarea v-model="libraryForm.description" rows="3" placeholder="知识库说明"></textarea></label>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeKnowledgeModal">取消</button><button class="button primary" type="submit" :disabled="!canManage || saving"><Plus />创建知识库</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="knowledgeModal === 'write-material'" title="手动写入素材" :close-disabled="saving" @close="closeKnowledgeModal">
                <form class="stack-form" @submit.prevent="createMaterial">
                  <label>归属知识库<select v-model="materialForm.lib_id"><option value="">未指定知识库</option><option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option></select></label>
                  <label>素材名称<input v-model="materialForm.name" placeholder="素材名称" /></label>
                  <label>标签<input v-model="materialForm.tags" placeholder="标签，用逗号分隔" /></label>
                  <label>素材内容<textarea v-model="materialForm.content" rows="8" placeholder="Markdown 格式的团队素材内容"></textarea></label>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeKnowledgeModal">取消</button><button class="button primary" type="submit" :disabled="!canEdit || saving"><FilePlus2 />写入素材</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="knowledgeModal === 'upload-file'" title="上传文件" :close-disabled="saving" @close="closeKnowledgeModal">
                <form class="stack-form" @submit.prevent="uploadMaterial">
                  <label>归属知识库<select v-model="materialForm.lib_id"><option value="">未指定知识库</option><option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option></select></label>
                  <label>选择文件<input ref="materialFileInput" type="file" @change="chooseFile" /></label>
                  <label>自定义名称（可选）<input v-model="materialForm.name" placeholder="留空则使用文件名" /></label>
                  <label>标签<input v-model="materialForm.tags" placeholder="用逗号分隔" /></label>
                  <div v-if="selectedFile" class="form-notice">已选择：{{ selectedFile.name }} · {{ formatBytes(selectedFile.size) }}</div>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeKnowledgeModal">取消</button><button class="button secondary" type="submit" :disabled="!canEdit || saving || !selectedFile"><Upload />进入处理队列</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="knowledgeModal === 'import-personal'" title="导入个人文件" :close-disabled="saving" @close="closeKnowledgeModal">
                <form class="stack-form" @submit.prevent="importPersonalMaterial">
                  <label>归属知识库<select v-model="personalImportForm.lib_id"><option value="">未指定知识库</option><option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option></select></label>
                  <label>选择个人素材<select v-model="personalImportForm.material_id" :disabled="personalMaterialsLoading"><option value="">{{ personalMaterialsLoading ? '正在加载...' : '请选择个人素材' }}</option><option v-for="item in personalMaterials" :key="item.id" :value="item.id">{{ item.name }} · {{ item.kind }} · {{ formatBytes(item.size) }}</option></select></label>
                  <label>覆盖名称（可选）<input v-model="personalImportForm.name" placeholder="留空则使用原名" /></label>
                  <label>标签<input v-model="personalImportForm.tags" placeholder="用逗号分隔" /></label>
                  <div v-if="!personalMaterialsLoading && !personalMaterials.length" class="team-empty-inline compact">个人端暂无可导入素材</div>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeKnowledgeModal">取消</button><button class="button secondary" type="submit" :disabled="!canEdit || saving || !personalImportForm.material_id"><FilePlus2 />导入到团队素材库</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="knowledgeModal === 'url-material'" title="网页链接入库" :close-disabled="saving" @close="closeKnowledgeModal">
                <form class="stack-form" @submit.prevent="createUrlMaterial">
                  <label>网页素材名称<input v-model="urlForm.name" placeholder="素材名称" /></label>
                  <label>网页链接<input v-model="urlForm.url" placeholder="https://..." /></label>
                  <label>归属知识库<select v-model="urlForm.lib_id"><option value="">未指定知识库</option><option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option></select></label>
                  <label>标签<input v-model="urlForm.tags" placeholder="标签" /></label>
                  <label>正文内容（可选）<textarea v-model="urlForm.content" rows="4" placeholder="粘贴网页正文，或留空后续接入 MCP 抓取"></textarea></label>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeKnowledgeModal">取消</button><button class="button secondary" type="submit" :disabled="!canEdit || saving"><Link2 />保存网页素材</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="editingLibrary" title="编辑知识库" :close-disabled="saving" @close="closeLibraryEdit">
                <form class="stack-form library-edit-form" @submit.prevent="saveLibraryEdit">
                  <label>知识库名称</label>
                  <input v-model="libraryEditForm.name" placeholder="知识库名称" class="tech-input" />
                  <label>分类</label>
                  <input v-model="libraryEditForm.category" placeholder="例如：前端开发" class="tech-input" />
                  <label>说明</label>
                  <textarea v-model="libraryEditForm.description" rows="4" placeholder="知识库说明" class="tech-input"></textarea>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeLibraryEdit">取消</button><button class="button primary" type="submit" :disabled="!canManage || saving"><Save />保存更改</button></div>
                </form>
              </ModalDialog>

              <ModalDialog v-if="editingAccessLibrary" title="设置成员权限" :close-disabled="saving" @close="closeLibraryAccessModal">
                <form class="stack-form" @submit.prevent="saveLibraryAccess">
                  <label>知识库</label>
                  <p class="tech-context">{{ editingAccessLibrary.name }} · {{ editingAccessLibrary.category }}</p>
                  <label>团队成员 ID</label>
                  <input v-model="accessForm.member_id" placeholder="输入团队成员的 ID" class="tech-input" />
                  <label>权限类型</label>
                  <select v-model="accessForm.access" class="tech-input">
                    <option value="read">只读</option>
                    <option value="write">读写</option>
                  </select>
                  <div class="modal-actions"><button class="button ghost" type="button" @click="closeLibraryAccessModal">取消</button><button class="button primary" type="submit" :disabled="!canManage || saving"><LockKeyhole />保存权限</button></div>
                </form>
              </ModalDialog>
            </section>

            <section v-if="tab === 'shares'" class="team-section team-two-col">
              <section class="panel team-form-panel">
                <header><strong>创建团队分享</strong><small>密码、有效期与水印</small></header>
                <form @submit.prevent="createShare">
                  <input v-model="shareForm.name" placeholder="分享名称" />
                  <select v-model="shareForm.lib_id">
                    <option value="">整个团队范围</option>
                    <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
                  </select>
                  <textarea v-model="shareForm.description" rows="3" placeholder="分享说明"></textarea>
                  <input v-model="shareForm.password" placeholder="可选访问密码" maxlength="12" />
                  <input v-model="shareForm.member_ids" placeholder="可选：指定成员 ID，逗号分隔" />
                  <label class="inline-check"><input v-model="shareForm.watermark" type="checkbox" />启用访客水印</label>
                  <button class="button primary" :disabled="saving"><Link2 />创建分享</button>
                </form>
              </section>
              <section class="panel team-list-panel">
                <header><strong>分享链接</strong><small>{{ shares.length }} 个</small></header>
                <article v-for="share in shares" :key="share.id">
                  <Link2 />
                  <span><b>{{ share.name }}</b><small>/share/team/{{ share.id }} · {{ share.visits }} 次访问 · {{ share.expires_at ? formatDate(share.expires_at) : '长期有效' }} · {{ share.status }}</small></span>
                  <span class="row-badge">{{ share.watermark ? '水印' : '无水印' }}</span>
                  <button class="icon-button danger" title="撤销分享" :disabled="!canManage || share.status !== 'active'" @click="revokeShare(share)"><X /></button>
                </article>
              </section>
            </section>

            <section v-if="tab === 'qa'" class="team-section">
              <div class="team-qa-grid">
                <section class="panel team-form-panel team-qa-ask">
                  <header>
                    <strong>团队 AI 问答</strong>
                    <small>只检索当前成员有权限的知识库，结果自动进入团队公共归档</small>
                  </header>
                  <form @submit.prevent="askTeam">
                    <textarea v-model="qaForm.question" rows="7" placeholder="输入团队知识问题"></textarea>
                    <div class="qa-scope-bar">
                      <span>检索范围</span>
                      <button class="button compact ghost" type="button" @click="qaForm.lib_ids = []">全部可见</button>
                    </div>
                    <div class="check-grid">
                      <label v-for="lib in libraries" :key="lib.id" class="inline-check"><input v-model="qaForm.lib_ids" type="checkbox" :value="lib.id" />{{ lib.name }}</label>
                    </div>
                    <div class="qa-quota-line">
                      <span>今日免费 {{ qaQuota?.free_remaining ?? '...' }} 次</span>
                      <span>超额 {{ qaQuota?.paid_cost ?? 2 }} 学识币/次</span>
                    </div>
                    <button class="button primary" :disabled="qaLoading || !qaForm.question.trim()">
                      <MessageSquareText />{{ qaLoading ? '检索中...' : '检索、生成并归档' }}
                    </button>
                  </form>
                </section>

                <section class="panel team-qa-answer">
                  <header>
                    <strong>当前答案</strong>
                    <small>{{ qaModeLabel(qaResult?.mode) }} · {{ qaResult?.source_count || 0 }} 条来源</small>
                  </header>
                  <template v-if="qaResult">
                    <div class="qa-answer-meta">
                      <span>{{ qaLibraryLabel(qaResult) }}</span>
                      <span>{{ formatDate(qaResult.created_at) }}</span>
                      <span v-if="qaResult.currency?.charged">消耗 {{ qaResult.currency.charged }} 学识币</span>
                    </div>
                    <h3>{{ qaResult.question }}</h3>
                    <pre>{{ qaResult.answer }}</pre>
                    <p v-if="qaResult.agent_note" class="qa-agent-note">{{ qaResult.agent_note }}</p>
                    <div class="qa-source-list">
                      <article v-for="source in qaResult.sources || []" :key="`${qaResult.id}-${source.material_id}`">
                        <FileText />
                        <span><b>{{ source.name }}</b><small>{{ source.library }} · {{ source.uploader }} · 匹配 {{ source.score || 0 }}</small><em>{{ source.snippet }}</em></span>
                      </article>
                    </div>
                  </template>
                  <div v-else class="team-empty-inline compact">提交问题后将在这里展示完整答案、来源片段和额度结算。</div>
                </section>

                <section class="panel team-list-panel team-qa-archive">
                  <header><strong>团队问答存档</strong><small>{{ qaArchives.length }} 条</small></header>
                  <form class="qa-filter-bar" @submit.prevent="loadQAArchive">
                    <input v-model="qaFilters.q" placeholder="搜索问题或答案" />
                    <select v-model="qaFilters.lib_id">
                      <option value="">全部知识库</option>
                      <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
                    </select>
                    <label class="inline-check"><input v-model="qaFilters.mine" type="checkbox" />只看我的</label>
                    <button class="button compact secondary" type="submit"><RefreshCw />筛选</button>
                  </form>
                  <article v-for="item in qaArchives" :key="item.id" class="qa-row" :class="{ active: selectedQaArchive?.id === item.id }" @click="openQAArchive(item)">
                    <MessageSquareText />
                    <span><b>{{ item.question }}</b><small>{{ qaLibraryLabel(item) }} · {{ item.source_count || 0 }} 条来源 · {{ item.nickname }} · {{ formatDate(item.created_at) }}</small></span>
                    <div class="row-actions">
                      <button class="icon-button" title="复用问题" @click.stop="reuseQAArchive(item)"><RotateCcw /></button>
                      <button v-if="item.can_delete" class="icon-button danger" title="删除归档" @click.stop="deleteQAArchive(item)"><Trash2 /></button>
                    </div>
                  </article>
                  <div v-if="!qaArchives.length" class="team-empty-inline compact">暂无匹配的团队问答归档。</div>
                </section>
              </div>
            </section>

            <section v-if="tab === 'evolution'" class="team-section team-two-col">
              <section class="panel team-form-panel">
                <header><strong>协同知识进化</strong><small>人工审核或负责人自动模式</small></header>
                <form @submit.prevent="createEvolution">
                  <select v-model="evolutionForm.lib_id">
                    <option value="">跨知识库联合进化</option>
                    <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
                  </select>
                  <select v-model="evolutionForm.mode">
                    <option value="manual">多人审核模式</option>
                    <option value="auto">AI 自动进化</option>
                  </select>
                  <select v-model="evolutionForm.review_strategy">
                    <option value="owner_final">负责人终审</option>
                    <option value="majority">半数通过</option>
                    <option value="all_agree">全员同意</option>
                  </select>
                  <textarea v-model="evolutionForm.summary" rows="4" placeholder="本次团队进化目标"></textarea>
                  <button class="button primary" :disabled="!canManage"><BrainCircuit />发起进化</button>
                </form>
              </section>
              <section class="panel team-list-panel">
                <header><strong>审核队列</strong><small>{{ evolution.length }} 个任务</small></header>
                <article v-for="task in evolution" :key="task.id" class="review-row">
                  <BrainCircuit />
                  <span><b>#{{ task.id }} {{ task.lib_name || '跨库进化' }}</b><small>{{ statusLabel(task.status) }} · {{ task.review_strategy }} · {{ task.progress }}%</small></span>
                  <div class="row-actions">
                    <button class="icon-button success" title="通过" :disabled="!canEdit" @click="reviewTask(task, 'accepted')"><Check /></button>
                    <button class="icon-button danger" title="拒绝" :disabled="!canEdit" @click="reviewTask(task, 'rejected')"><X /></button>
                    <button class="icon-button" title="重新生成" :disabled="!canEdit || task.status === 'completed'" @click="regenerateTask(task)"><RotateCcw /></button>
                  </div>
                </article>
              </section>
            </section>

            <section v-if="tab === 'games'" class="team-section">
              <div class="team-two-col">
                <section class="panel team-form-panel">
                  <header><strong>提交游戏成绩</strong><small>成绩进入团队日 / 周 / 总榜</small></header>
                  <form @submit.prevent="submitScore">
                    <select v-model="scoreForm.game">
                      <option value="flashcard">闪卡</option>
                      <option value="monopoly">知识大富翁</option>
                      <option value="matching">配对竞速</option>
                    </select>
                    <input v-model.number="scoreForm.score" type="number" min="0" placeholder="积分" />
                    <div class="team-form-grid"><input v-model.number="scoreForm.correct" type="number" min="0" placeholder="答对" /><input v-model.number="scoreForm.total" type="number" min="1" placeholder="总题数" /></div>
                    <button class="button primary"><Trophy />提交成绩</button>
                  </form>
                </section>
                <section class="panel team-list-panel">
                  <header><strong>团队排行榜</strong><div class="segmented-control"><button v-for="period in ['day', 'week', 'all']" :key="period" :class="{ active: rankPeriod === period }" @click="changeRankPeriod(period)">{{ period === 'day' ? '日榜' : period === 'week' ? '周榜' : '总榜' }}</button></div></header>
                  <article v-for="(item, index) in rank" :key="item.user_id"><Trophy /><span><b>#{{ index + 1 }} {{ item.nickname }}</b><small>{{ item.score }} 分 · {{ item.correct }}/{{ item.total }} · {{ item.sessions }} 场</small></span></article>
                </section>
              </div>
              <div class="team-two-col">
                <section class="panel team-form-panel">
                  <header><strong>创建团队活动</strong><small>限时知识竞赛或对战</small></header>
                  <form @submit.prevent="createActivity">
                    <input v-model="activityForm.name" placeholder="活动名称" />
                    <select v-model="activityForm.activity_type"><option value="contest">知识竞赛</option><option value="chapter">章节挑战</option><option value="battle">多人对战</option></select>
                    <div class="team-form-grid"><input v-model="activityForm.starts_at" type="datetime-local" /><input v-model="activityForm.ends_at" type="datetime-local" /></div>
                    <input v-model="activityForm.reward" placeholder="虚拟奖励" />
                    <button class="button secondary" :disabled="!canManage"><Plus />创建活动</button>
                  </form>
                </section>
                <section class="panel team-list-panel">
                  <header><strong>活动与成就</strong><small>{{ activities.length }} 个活动 · {{ achievements.length }} 枚徽章</small></header>
                  <article v-for="activity in activities" :key="activity.id"><Activity /><span><b>{{ activity.name }}</b><small>{{ statusLabel(activity.status) }} · {{ activity.reward || '无奖励' }}</small></span><div v-if="canManage" class="activity-actions"><button v-if="activity.status === 'planned'" class="icon-button" title="发布活动" @click="updateActivity(activity, 'published')"><Play /></button><button v-if="activity.status === 'published'" class="icon-button" title="开始活动" @click="updateActivity(activity, 'running')"><Play /></button><button v-if="activity.status === 'running'" class="icon-button" title="结束活动" @click="updateActivity(activity, 'ended')"><StopCircle /></button><button v-if="!['ended','cancelled'].includes(activity.status)" class="icon-button delete-icon" title="取消活动" @click="updateActivity(activity, 'cancelled')"><X /></button></div></article>
                  <article v-for="achievement in achievements.slice(0, 5)" :key="achievement.id"><ShieldCheck /><span><b>{{ achievement.label }}</b><small>{{ achievement.nickname }} · {{ formatDate(achievement.awarded_at) }}</small></span></article>
                </section>
              </div>
              <section v-if="wsConnected && multiplayerUsers.length" class="panel team-list-panel" style="margin-top:16px">
                <header><strong>多人对战在线</strong><small>{{ multiplayerUsers.length }} 人在线 · WebSocket 已连接</small></header>
                <article v-for="user in multiplayerUsers" :key="user.user_id"><ShieldCheck /><span><b>玩家 #{{ user.user_id }}</b><small>在线</small></span></article>
              </section>
            </section>

            <section v-if="tab === 'stats'" class="team-section">
              <section class="panel stats-export-panel">
                <div class="stats-export-heading">
                  <div>
                    <span class="eyebrow"><BarChart3 /> Team Reports</span>
                    <h3>团队数据与导出</h3>
                    <p>汇总成员贡献、知识库容量、学习行为与操作审计，导出文件用于复盘和归档。</p>
                  </div>
                  <div class="stats-export-metrics">
                    <span><b>{{ stats?.overview?.materials || 0 }}</b><small>团队素材</small></span>
                    <span><b>{{ stats?.overview?.qa_archives || 0 }}</b><small>问答归档</small></span>
                    <span><b>{{ stats?.overview?.pending_reviews || 0 }}</b><small>待审任务</small></span>
                  </div>
                </div>
                <div class="stats-export-actions">
                  <button class="stats-export-button" @click="downloadExport('materials')"><Download /><span><b>素材清单</b><small>名称、类型、标签、上传人</small></span></button>
                  <button class="stats-export-button" @click="downloadExport('evolution')"><Download /><span><b>审核记录</b><small>进化任务与审核决策</small></span></button>
                  <button class="stats-export-button" @click="downloadExport('games')"><Download /><span><b>游戏日志</b><small>答题数据与排行榜</small></span></button>
                  <button class="stats-export-button" @click="downloadExport('logs')"><Download /><span><b>操作日志</b><small>成员、素材、分享行为</small></span></button>
                </div>
              </section>

              <div class="stats-card-grid">
                <section class="panel stats-list-card">
                  <header><strong>成员贡献</strong><small>上传、审核与答题正确率</small></header>
                  <article v-for="item in stats?.members || []" :key="item.user_id" class="stats-member-row">
                    <BarChart3 />
                    <span><b>{{ item.nickname }} · {{ roleLabels[item.role] }}</b><small>素材 {{ item.materials }} · 审核 {{ item.reviews }} · 积分 {{ item.score }}</small></span>
                    <strong>{{ Math.round(item.accuracy * 100) }}%</strong>
                  </article>
                  <div v-if="!(stats?.members || []).length" class="team-empty-inline compact">暂无成员贡献数据。</div>
                </section>
                <section class="panel stats-list-card">
                  <header><strong>知识库统计</strong><small>素材量与存储</small></header>
                  <article v-for="item in stats?.libraries || []" :key="item.id" class="stats-library-row">
                    <Database />
                    <span><b>{{ item.name }}</b><small>{{ item.materials }} 条素材 · {{ formatBytes(item.storage) }}</small></span>
                    <strong>{{ formatBytes(item.storage) }}</strong>
                  </article>
                  <div v-if="!(stats?.libraries || []).length" class="team-empty-inline compact">暂无知识库统计数据。</div>
                </section>
              </div>
              <section class="panel stats-graph-card">
                <header>
                  <div><strong>团队知识图谱</strong><small>{{ graph?.nodes?.length || 0 }} 个节点 · {{ graph?.edges?.length || 0 }} 条关系</small></div>
                  <button class="button compact secondary" @click="downloadExport('materials')"><Download />导出素材</button>
                </header>
                <div v-if="(graph?.nodes || []).length" class="graph-summary"><span v-for="node in (graph?.nodes || []).slice(0, 24)" :key="node.id"><Tag />{{ node.label }}</span></div>
                <div v-else class="stats-graph-empty">暂无图谱节点，上传或导入团队素材后会自动形成概览。</div>
              </section>
            </section>

            <section v-if="tab === 'settings' && settingsForm" class="team-section team-two-col">
              <section class="panel team-form-panel">
                <header><strong>团队策略与资源</strong><small>权限、配额、进化与分享</small></header>
                <form @submit.prevent="saveSettings">
                  <label class="inline-check"><input v-model="settingsForm.allow_editor_external_share" type="checkbox" />允许编辑成员创建外部分享</label>
                  <label class="inline-check"><input v-model="settingsForm.watermark_enabled" type="checkbox" />团队分享默认启用水印</label>
                  <label class="inline-check"><input v-model="settingsForm.auto_evolution_enabled" type="checkbox" />开启定时自动进化</label>
                  <input v-model="settingsForm.auto_evolution_time" placeholder="02:00" />
                  <input v-model.number="settingsForm.storage_quota" type="number" min="0" placeholder="存储配额" />
                  <input v-model.number="settingsForm.daily_deepseek_quota" type="number" min="0" placeholder="每日 AI 配额" />
                  <button class="button primary" :disabled="!canManage || saving"><Save />保存设置</button>
                </form>
              </section>
              <section class="panel team-list-panel">
                <header><strong>生命周期与备份</strong><small>负责人专属操作</small></header>
                <div class="button-stack">
                  <button v-if="isOwner && team?.status === 'active'" class="button secondary" @click="updateLifecycle('archived')"><Archive />归档团队</button>
                  <button v-if="isOwner && team?.status !== 'active'" class="button secondary" @click="restoreTeam"><RotateCcw />恢复团队</button>
                  <button v-if="isOwner" class="button secondary" @click="downloadBackup"><Download />导出完整备份包</button>
                  <button v-if="isOwner" class="button danger" @click="dissolveTeam"><Trash2 />解散团队</button>
                </div>
                <div class="subsection-heading"><strong>团队操作日志</strong><small>{{ logs.length }} 条</small></div>
                <article v-for="item in logs.slice(0, 12)" :key="item.id"><Activity /><span><b>{{ item.module }} / {{ item.action }}</b><small>{{ item.detail }} · {{ formatDate(item.created_at) }}</small></span></article>
              </section>
            </section>
          </template>
        </main>
      </div>
    </section>

    <ModalDialog v-if="confirmDialog.open" :title="confirmDialog.title" @close="closeConfirm">
      <p class="confirm-message">{{ confirmDialog.message }}</p>
      <div class="modal-actions">
        <button class="button ghost" type="button" @click="closeConfirm">取消</button>
        <button class="button primary" type="button" @click="execConfirm">确认</button>
      </div>
    </ModalDialog>
  </div>
</template>

<style scoped>
.team-layout {
  grid-template-columns: 72px minmax(0, 1fr);
}

.team-sidebar {
  width: 72px;
  padding: 10px 8px;
  overflow: visible;
  border-color: rgba(125, 249, 255, .22);
  background: rgba(5, 16, 31, .74);
  box-shadow: 0 20px 55px rgba(0, 0, 0, .34), inset 0 1px 0 rgba(255, 255, 255, .05);
}

.team-sidebar header {
  display: none;
}

.team-module-divider {
  display: none;
}

.team-module-nav {
  display: grid;
  gap: 8px;
}

.team-module-nav button {
  position: relative;
  display: grid;
  width: 54px;
  height: 54px;
  min-height: 54px;
  place-items: center;
  grid-template-columns: 1fr;
  gap: 0;
  padding: 0;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 8px;
  background: rgba(9, 32, 55, .66);
  color: #c6e8f5;
  transition: transform .18s ease, border-color .18s ease, background .18s ease, box-shadow .18s ease, color .18s ease;
}

.team-module-nav button:hover,
.team-module-nav button.active {
  transform: translateX(3px);
  color: #7df9ff;
  border-color: rgba(125, 249, 255, .74);
  background: rgba(9, 55, 83, .86);
  box-shadow: 0 0 24px rgba(0, 213, 255, .22);
}

.team-module-nav button.active {
  box-shadow: 0 0 24px rgba(0, 213, 255, .22), inset 0 0 0 1px rgba(125, 249, 255, .22);
}

.team-module-nav button svg {
  width: 21px;
  height: 21px;
  color: currentColor;
}

.team-module-tooltip {
  pointer-events: none;
  position: absolute;
  left: calc(100% + 14px);
  top: 50%;
  z-index: 20;
  width: 188px;
  min-height: 54px;
  display: grid;
  align-content: center;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid rgba(125, 249, 255, .24);
  border-radius: 8px;
  background: rgba(5, 20, 39, .94);
  box-shadow: 0 18px 44px rgba(0, 0, 0, .34);
  opacity: 0;
  transform: translate(-8px, -50%);
  transition: opacity .18s ease, transform .18s ease;
  text-align: left;
}

.team-module-tooltip strong,
.team-module-tooltip small {
  display: block;
}

.team-module-tooltip strong {
  color: #e7fbff;
  font-size: 14px;
}

.team-module-tooltip small {
  color: #8fb4c9;
  font-size: 11px;
  line-height: 1.35;
}

.team-module-nav button:hover .team-module-tooltip,
.team-module-nav button:focus-visible .team-module-tooltip {
  opacity: 1;
  transform: translate(0, -50%);
}

.team-module-nav button:disabled {
  cursor: not-allowed;
  opacity: .42;
  transform: none;
}

.team-module-nav button:disabled .team-module-tooltip {
  opacity: 0;
}

.team-three-col {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.team-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.team-qa-grid {
  display: grid;
  grid-template-columns: minmax(280px, .82fr) minmax(0, 1.18fr);
  gap: 18px;
  align-items: start;
}

.team-qa-archive {
  grid-column: 1 / -1;
}

.qa-scope-bar,
.qa-quota-line,
.qa-answer-meta,
.qa-filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.qa-scope-bar {
  justify-content: space-between;
  color: var(--muted);
  font-size: 12px;
}

.qa-quota-line,
.qa-answer-meta {
  color: var(--muted);
  font-size: 12px;
}

.team-qa-answer {
  display: grid;
  gap: 14px;
  padding: 18px 20px;
}

.team-qa-answer h3 {
  margin: 0;
  color: #effdff;
  font-size: 18px;
}

.team-qa-answer pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: #dff8ff;
  font: inherit;
  line-height: 1.75;
}

.qa-agent-note {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.qa-source-list {
  display: grid;
  gap: 10px;
}

.qa-source-list article {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 10px;
  padding: 10px;
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 8px;
  background: rgba(8, 28, 48, .54);
}

.qa-source-list span,
.qa-source-list b,
.qa-source-list small,
.qa-source-list em {
  display: block;
  min-width: 0;
}

.qa-source-list small {
  color: var(--muted);
}

.qa-source-list em {
  margin-top: 5px;
  color: #bfefff;
  font-style: normal;
  line-height: 1.6;
}

.qa-filter-bar {
  margin-bottom: 10px;
}

.qa-filter-bar input,
.qa-filter-bar select {
  flex: 1 1 180px;
}

.qa-row {
  cursor: pointer;
}

.qa-row.active {
  border-color: rgba(125, 249, 255, .42);
  background: rgba(14, 64, 88, .62);
}

.library-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.library-permission-list {
  grid-column: 2 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.library-permission-list button {
  border: 1px solid rgba(125, 249, 255, .2);
  border-radius: 6px;
  background: rgba(8, 28, 48, .48);
  color: var(--muted);
  padding: 4px 7px;
  font-size: 11px;
}

.stats-export-panel {
  display: grid;
  gap: 18px;
  padding: 22px 24px;
}

.stats-export-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: end;
}

.stats-export-heading h3,
.stats-export-heading p {
  margin: 0;
}

.stats-export-heading h3 {
  color: #effdff;
  font-size: 24px;
}

.stats-export-heading p {
  margin-top: 8px;
  max-width: 680px;
  color: var(--muted);
  line-height: 1.6;
}

.stats-export-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(82px, 1fr));
  gap: 8px;
}

.stats-export-metrics span {
  display: grid;
  gap: 3px;
  min-width: 86px;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 8px;
  background: rgba(8, 28, 48, .48);
  padding: 10px 12px;
}

.stats-export-metrics b {
  color: #effdff;
  font-size: 20px;
}

.stats-export-metrics small {
  color: var(--muted);
  white-space: nowrap;
}

.stats-export-actions {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 10px;
}

.stats-export-button {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-height: 76px;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 8px;
  background: rgba(7, 33, 53, .62);
  color: var(--text);
  padding: 12px;
  text-align: left;
}

.stats-export-button svg {
  width: 22px;
  height: 22px;
  color: var(--cyan);
}

.stats-export-button span,
.stats-export-button b,
.stats-export-button small {
  display: block;
  min-width: 0;
}

.stats-export-button b {
  color: #f1fdff;
  white-space: nowrap;
}

.stats-export-button small {
  margin-top: 3px;
  color: var(--muted);
  line-height: 1.4;
}

.stats-export-button:hover {
  border-color: rgba(125, 249, 255, .38);
  background: rgba(14, 64, 88, .62);
}

.stats-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.stats-list-card,
.stats-graph-card {
  padding: 18px 20px;
}

.stats-member-row,
.stats-library-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.stats-member-row > strong,
.stats-library-row > strong {
  color: var(--cyan);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.stats-graph-card header {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: center;
}

.stats-graph-card header strong,
.stats-graph-card header small {
  display: block;
}

.stats-graph-empty {
  min-height: 112px;
  display: grid;
  place-items: center;
  border: 1px dashed rgba(125, 249, 255, .18);
  border-radius: 8px;
  color: var(--muted);
  text-align: center;
}

.team-toolbar,
.team-material-detail {
  padding: 18px 20px;
}

.team-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.team-title-metrics {
  display: flex;
  align-items: center;
  gap: 16px;
}

.team-fund-mini {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 218px;
  padding: 10px 12px;
  border: 1px solid rgba(125, 249, 255, .2);
  border-radius: 8px;
  background: rgba(7, 33, 53, .58);
  color: var(--text);
  text-align: left;
}

.team-fund-mini svg {
  color: var(--cyan);
}

.team-fund-mini span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.team-fund-mini small,
.team-fund-mini strong,
.team-fund-mini b {
  display: block;
}

.team-fund-mini small {
  color: var(--muted);
  font-size: 11px;
}

.team-fund-mini strong {
  color: #e7fbff;
  font-size: 13px;
}

.team-fund-mini b {
  margin-left: auto;
  color: #ffd479;
  font-size: 11px;
  white-space: nowrap;
}

.team-currency-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.team-currency-card {
  display: flex;
  align-items: center;
  gap: 15px;
  min-height: 112px;
  padding: 20px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  background: rgba(7, 25, 45, .74);
}

.team-currency-card svg {
  width: 30px;
  height: 30px;
}

.team-currency-card span {
  display: grid;
  gap: 3px;
}

.team-currency-card small,
.team-currency-card strong,
.team-currency-card b {
  display: block;
}

.team-currency-card small {
  color: var(--muted);
}

.team-currency-card strong {
  color: #f1fdff;
  font-size: 29px;
}

.team-currency-card b {
  color: var(--muted);
  font-size: 12px;
}

.team-currency-card.knowledge svg,
.currency-in {
  color: var(--mint);
}

.team-currency-card.truth svg,
.currency-out {
  color: #ffd479;
}

.currency-in,
.currency-out {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.team-material-detail {
  border: 1px solid rgba(125, 249, 255, .24);
  background: rgba(7, 25, 45, .74);
}

.team-material-detail h3 {
  margin: 8px 0 4px;
}

.clickable-row {
  cursor: pointer;
}

.clickable-row:hover {
  background: rgba(125, 249, 255, .06);
}

.row-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: flex-end;
}

.row-badge {
  color: var(--cyan);
  font-size: 11px;
  white-space: nowrap;
}

.icon-button.success {
  color: var(--mint);
}

.icon-button.danger,
.button.danger {
  color: var(--red);
}

.icon-button {
  display: inline-grid;
  place-items: center;
}

.icon-button svg {
  width: 16px;
  height: 16px;
}

.icon-button.delete-icon {
  color: var(--red);
  opacity: 0.6;
}

.icon-button.delete-icon:hover {
  opacity: 1;
}

.activity-actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.request-row,
.comment-row,
.version-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  border-top: 1px solid var(--outline);
  padding: 12px 0;
}

.request-row span,
.comment-row span,
.version-row span {
  min-width: 0;
}

.request-row b,
.request-row small,
.comment-row b,
.comment-row small,
.version-row b,
.version-row small {
  display: block;
}

.request-row small,
.comment-row small,
.version-row small {
  margin-top: 4px;
  color: var(--muted);
  line-height: 1.5;
}

.comment-row small.resolved {
  color: var(--mint);
  text-decoration: line-through;
}

.subsection-heading {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--outline);
}

.subsection-heading small {
  color: var(--muted);
}

.inline-form {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.inline-form input {
  flex: 1;
  min-width: 0;
}

.check-grid {
  display: grid;
  gap: 7px;
  margin: 12px 0;
}

.segmented-control {
  display: flex;
  gap: 4px;
}

.segmented-control button {
  border: 1px solid var(--outline);
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  padding: 5px 8px;
}

.segmented-control button.active {
  border-color: var(--cyan);
  color: var(--cyan);
}

.button-stack {
  display: grid;
  gap: 9px;
  margin-bottom: 16px;
}

.graph-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.graph-summary span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--outline);
  border-radius: 6px;
  padding: 6px 8px;
  color: var(--muted);
  font-size: 12px;
}

.graph-summary svg {
  width: 13px;
  color: var(--cyan);
}

.team-empty-inline.compact {
  min-height: 70px;
}

@media (max-width: 1100px) {
  .team-layout {
    grid-template-columns: 1fr;
  }

  .team-sidebar {
    position: static;
    width: 100%;
    overflow: visible;
  }

  .team-module-nav {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .team-module-nav button {
    width: 100%;
  }

  .team-module-tooltip {
    display: none;
  }

  .team-three-col {
    grid-template-columns: 1fr;
  }

  .team-qa-grid {
    grid-template-columns: 1fr;
  }

  .stats-export-heading,
  .stats-card-grid {
    grid-template-columns: 1fr;
  }

  .stats-export-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .team-toolbar {
    display: grid;
  }

  .team-form-grid {
    grid-template-columns: 1fr;
  }

  .team-module-nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .qa-filter-bar {
    display: grid;
  }

  .stats-export-actions,
  .stats-export-metrics {
    grid-template-columns: 1fr;
  }

  .stats-graph-card header {
    display: grid;
  }

  .knowledge-action-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Knowledge action bar */
.knowledge-action-bar {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 22px;
}

.knowledge-action-btn {
  display: flex !important;
  align-items: center;
  gap: 10px;
  min-height: 72px;
  padding: 12px 16px !important;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 10px;
  background: rgba(7, 33, 53, .62);
  color: var(--text);
  text-align: left;
  font-weight: 500;
  transition: border-color .18s, background .18s, box-shadow .18s, transform .18s;
}

.knowledge-action-btn svg {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  color: var(--cyan);
}

.knowledge-action-btn span {
  display: grid;
  gap: 2px;
  min-width: 0;
  line-height: 1.35;
}

.knowledge-action-btn span small {
  display: block;
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
}

.knowledge-action-btn:hover {
  border-color: rgba(125, 249, 255, .42);
  background: rgba(14, 64, 88, .68);
  box-shadow: 0 4px 18px rgba(0, 160, 220, .12);
  transform: translateY(-1px);
}

.knowledge-action-btn:active {
  transform: translateY(0);
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--outline);
}

@media (max-width: 900px) {
  .knowledge-action-bar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .knowledge-action-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Library edit modal - deep blue tech style */
.library-edit-form label {
  display: block;
  margin-top: 18px;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #8ad4f0;
  letter-spacing: 0.3px;
}

.library-edit-form label:first-child {
  margin-top: 0;
}

.tech-input {
  width: 100%;
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 8px;
  background: rgba(5, 18, 33, .72);
  color: #e2f4ff;
  font-size: 15px;
  line-height: 1.5;
  transition: border-color .2s, box-shadow .2s, background .2s;
  outline: none;
}

.tech-input::placeholder {
  color: rgba(140, 190, 220, .4);
}

.tech-input:focus {
  border-color: rgba(0, 220, 255, .55);
  box-shadow: 0 0 0 3px rgba(0, 200, 255, .08), 0 0 16px rgba(0, 160, 240, .06);
  background: rgba(7, 28, 48, .82);
}

textarea.tech-input {
  min-height: 110px;
  resize: vertical;
}

.confirm-message {
  color: #d0e4f4;
  font-size: 15px;
  line-height: 1.6;
  margin: 0 0 4px;
}

.tech-context {
  margin: 0;
  padding: 10px 14px;
  border: 1px solid rgba(125, 249, 255, .12);
  border-radius: 8px;
  background: rgba(7, 28, 48, .48);
  color: #8ad4f0;
  font-size: 13px;
  line-height: 1.5;
}
</style>
