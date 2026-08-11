<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Camera,
  Check,
  Circle,
  Clock3,
  ExternalLink,
  Eye,
  FileInput,
  FileImage,
  FilePenLine,
  Globe2,
  Link2,
  LoaderCircle,
  MessageSquare,
  RefreshCw,
  Save,
  ScanText,
  Send,
  Star,
  Trash2,
  Upload,
  UploadCloud,
  Video,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import ToastMessage from '../components/ToastMessage.vue'
import { api, apiBlob, formatBytes, token, clearToken, activeTeamId } from '../api'
import { renderMarkdown } from '../markdown'

const route = useRoute()
const materials = ref([])
const active = ref('all')
const q = ref('')
const modal = ref('')
const selectedMaterial = ref(null)
const toast = ref('')
const toastType = ref('success')
const uploadBusy = ref(false)
const fileInput = ref()
const imageInput = ref()
const videoInput = ref()
const askMaterialItem = ref(null)
const askQuestion = ref('')
const askResult = ref(null)
const askLoading = ref(false)
const askError = ref('')

const newTextForm = () => ({ name: '新知识笔记', content: '', category: '未分类' })
const textForm = ref(newTextForm())
const textStep = ref('form')
const textError = ref('')
let textAbortController = null
const urlForm = ref({ name: '网页素材', url: '', category: '未分类' })
const urlStep = ref('form')
const urlPreview = ref(null)
const urlError = ref('')
let urlAbortController = null

const imageForm = ref({ name: '图片识别素材', category: '未分类' })
const imageStep = ref('form')
const imageFile = ref(null)
const imagePreview = ref(null)
const imageObjectUrl = ref('')
const imageError = ref('')
const selectedMaterialImage = ref('')
const materialImageLoading = ref(false)
let imageAbortController = null

const videoForm = ref({ name: '视频导入素材', category: '未分类' })
const videoStep = ref('form')
const videoFile = ref(null)
const videoPreview = ref(null)
const videoObjectUrl = ref('')
const videoError = ref('')
const videoDragActive = ref(false)
const selectedMaterialVideo = ref('')
const materialVideoLoading = ref(false)
const videoUploadPercent = ref(0)
const videoPhase = ref('upload')
let videoAbortController = null

const filtered = computed(() => materials.value.filter((material) => (
  (active.value === 'all' || material.status === active.value)
  && (!q.value || material.name.toLowerCase().includes(q.value.toLowerCase()))
)))
const textModalTitle = computed(() => ({
  form: '手动输入知识',
  saving: '正在保存知识',
  error: '知识保存失败',
}[textStep.value]))
const urlModalTitle = computed(() => ({
  form: '采集网页链接',
  loading: '正在抓取网页',
  preview: '确认抓取内容',
  saving: '正在保存素材',
  error: '网页抓取失败',
}[urlStep.value]))
const urlHost = computed(() => {
  try { return new URL(urlForm.value.url).hostname }
  catch { return urlForm.value.url }
})
const imageModalTitle = computed(() => ({
  form: '识别图片文字',
  loading: '正在识别图片',
  preview: '确认识别内容',
  saving: '正在保存素材',
  error: '图片识别失败',
}[imageStep.value]))
const videoModalTitle = computed(() => ({
  form: '视频导入',
  loading: '正在分析视频',
  preview: '确认视频文本',
  saving: '正在保存素材',
  error: '视频分析失败',
}[videoStep.value]))
const askMaterialPreview = computed(() => {
  const content = askMaterialItem.value?.content || ''
  return content.length > 520 ? `${content.slice(0, 520)}...` : content
})

async function load() {
  try {
    materials.value = await api('/materials')
    syncRouteSearch()
    openRouteMaterial()
  }
  catch (error) { notify(error.message, 'error') }
}

onMounted(load)
watch(() => route.query, () => {
  syncRouteSearch()
  openRouteMaterial()
})
onBeforeUnmount(() => {
  if (imageObjectUrl.value) URL.revokeObjectURL(imageObjectUrl.value)
  if (videoObjectUrl.value) URL.revokeObjectURL(videoObjectUrl.value)
  if (selectedMaterialImage.value) URL.revokeObjectURL(selectedMaterialImage.value)
  if (selectedMaterialVideo.value) URL.revokeObjectURL(selectedMaterialVideo.value)
})

function notify(message, type = 'success') {
  toast.value = message
  toastType.value = type
  window.setTimeout(() => { toast.value = '' }, 2800)
}

function syncRouteSearch() {
  if (typeof route.query.q === 'string') q.value = route.query.q
}

function openRouteMaterial() {
  const materialId = Number(route.query.material || 0)
  if (!materialId || !materials.value.length) return
  const target = materials.value.find((material) => Number(material.id) === materialId)
  if (target && selectedMaterial.value?.id !== target.id) openMaterial(target)
}

function openTextModal() {
  textForm.value = newTextForm()
  textStep.value = 'form'
  textError.value = ''
  modal.value = 'text'
}

function closeTextModal() {
  textAbortController?.abort()
  textAbortController = null
  modal.value = ''
}

function openUrlModal() {
  urlStep.value = 'form'
  urlPreview.value = null
  urlError.value = ''
  modal.value = 'url'
}

function closeUrlModal() {
  urlAbortController?.abort()
  urlAbortController = null
  modal.value = ''
}

async function fetchUrlPreview() {
  urlError.value = ''
  urlPreview.value = null
  urlStep.value = 'loading'
  const controller = new AbortController()
  urlAbortController = controller
  try {
    const preview = await api('/materials/url/preview', {
      method: 'POST',
      body: { url: urlForm.value.url },
      signal: controller.signal,
    })
    if (controller.signal.aborted) return
    urlPreview.value = preview
    if (!urlForm.value.name.trim() || urlForm.value.name === '网页素材') {
      urlForm.value.name = preview.title || '网页素材'
    }
    urlStep.value = 'preview'
  } catch (error) {
    if (controller.signal.aborted) return
    urlError.value = error.message
    urlStep.value = 'error'
  } finally {
    if (urlAbortController === controller) urlAbortController = null
  }
}

async function saveUrlMaterial() {
  if (!urlPreview.value) return
  urlError.value = ''
  urlStep.value = 'saving'
  const controller = new AbortController()
  urlAbortController = controller
  try {
    const material = await api('/materials/url', {
      method: 'POST',
      body: { ...urlForm.value, content: urlPreview.value.content },
      signal: controller.signal,
    })
    if (controller.signal.aborted) return
    modal.value = ''
    await load()
    selectedMaterial.value = material
    modal.value = 'material'
    notify('网页已确认入库')
  } catch (error) {
    if (controller.signal.aborted) return
    urlError.value = error.message
    urlStep.value = 'error'
  } finally {
    if (urlAbortController === controller) urlAbortController = null
  }
}

function recoverUrlFlow() {
  if (urlPreview.value) urlStep.value = 'preview'
  else fetchUrlPreview()
}

function editUrl() {
  urlStep.value = 'form'
  urlPreview.value = null
  urlError.value = ''
}

function clearSelectedMaterialImage() {
  if (selectedMaterialImage.value) URL.revokeObjectURL(selectedMaterialImage.value)
  selectedMaterialImage.value = ''
  materialImageLoading.value = false
}

function clearSelectedMaterialVideo() {
  if (selectedMaterialVideo.value) URL.revokeObjectURL(selectedMaterialVideo.value)
  selectedMaterialVideo.value = ''
  materialVideoLoading.value = false
}

async function openMaterial(material) {
  clearSelectedMaterialImage()
  clearSelectedMaterialVideo()
  selectedMaterial.value = material
  modal.value = 'material'
  if (material.file_path && material.kind === '图片') {
    materialImageLoading.value = true
    try {
      const blob = await apiBlob(`/materials/${material.id}/file`)
      if (selectedMaterial.value?.id === material.id) selectedMaterialImage.value = URL.createObjectURL(blob)
    } catch (error) {
      if (selectedMaterial.value?.id === material.id) notify(error.message, 'error')
    } finally {
      materialImageLoading.value = false
    }
  }
  if (material.file_path && material.kind === '视频') {
    materialVideoLoading.value = true
    try {
      const blob = await apiBlob(`/materials/${material.id}/file`)
      if (selectedMaterial.value?.id === material.id) selectedMaterialVideo.value = URL.createObjectURL(blob)
    } catch (error) {
      if (selectedMaterial.value?.id === material.id) notify(error.message, 'error')
    } finally {
      materialVideoLoading.value = false
    }
  }
}

function closeMaterial() {
  clearSelectedMaterialImage()
  clearSelectedMaterialVideo()
  selectedMaterial.value = null
  modal.value = ''
}

function openMaterialAsk(material) {
  askMaterialItem.value = material
  askQuestion.value = ''
  askResult.value = null
  askError.value = ''
  askLoading.value = false
  modal.value = 'ask'
}

function closeMaterialAsk() {
  askMaterialItem.value = null
  askQuestion.value = ''
  askResult.value = null
  askError.value = ''
  askLoading.value = false
  modal.value = ''
}

async function askMaterialQuestion() {
  const question = askQuestion.value.trim()
  if (!question || !askMaterialItem.value) return
  askLoading.value = true
  askError.value = ''
  askResult.value = null
  try {
    askResult.value = await api(`/materials/${askMaterialItem.value.id}/ask`, {
      method: 'POST',
      body: { question },
    })
  } catch (error) {
    askError.value = error.message
  } finally {
    askLoading.value = false
  }
}

function formatTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function getHost(value) {
  try { return new URL(value).hostname }
  catch { return value }
}

function clearImageObjectUrl() {
  if (imageObjectUrl.value) URL.revokeObjectURL(imageObjectUrl.value)
  imageObjectUrl.value = ''
}

function openImageModal() {
  imageStep.value = 'form'
  imageFile.value = null
  imagePreview.value = null
  imageError.value = ''
  clearImageObjectUrl()
  modal.value = 'image'
}

function closeImageModal() {
  imageAbortController?.abort()
  imageAbortController = null
  clearImageObjectUrl()
  modal.value = ''
}

async function recognizeImage(file) {
  if (!file) return
  if (!file.type.startsWith('image/')) {
    imageError.value = '请选择可读取的图片文件'
    imageStep.value = 'error'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    imageError.value = '图片不能超过 10 MB'
    imageStep.value = 'error'
    return
  }

  imageFile.value = file
  imagePreview.value = null
  imageError.value = ''
  clearImageObjectUrl()
  imageObjectUrl.value = URL.createObjectURL(file)
  if (!imageForm.value.name.trim() || imageForm.value.name === '图片识别素材') {
    imageForm.value.name = file.name.replace(/\.[^.]+$/, '') || '图片识别素材'
  }
  imageStep.value = 'loading'
  const body = new FormData()
  body.append('file', file)
  const controller = new AbortController()
  imageAbortController = controller
  try {
    const preview = await api('/materials/image/preview', {
      method: 'POST', body, signal: controller.signal,
    })
    if (controller.signal.aborted) return
    imagePreview.value = preview
    imageStep.value = 'preview'
  } catch (error) {
    if (controller.signal.aborted) return
    imageError.value = error.message
    imageStep.value = 'error'
  } finally {
    if (imageAbortController === controller) imageAbortController = null
  }
}

function selectImage(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  recognizeImage(file)
}

function dropImage(event) {
  recognizeImage(event.dataTransfer?.files?.[0])
}

async function saveImageMaterial() {
  if (!imageFile.value || !imagePreview.value) return
  imageError.value = ''
  imageStep.value = 'saving'
  const body = new FormData()
  body.append('file', imageFile.value)
  body.append('name', imageForm.value.name)
  body.append('category', imageForm.value.category)
  body.append('content', imagePreview.value.content)
  const controller = new AbortController()
  imageAbortController = controller
  try {
    const material = await api('/materials/image', {
      method: 'POST', body, signal: controller.signal,
    })
    if (controller.signal.aborted) return
    clearImageObjectUrl()
    modal.value = ''
    await load()
    await openMaterial(material)
    notify('图片文字已确认入库')
  } catch (error) {
    if (controller.signal.aborted) return
    imageError.value = error.message
    imageStep.value = 'error'
  } finally {
    if (imageAbortController === controller) imageAbortController = null
  }
}

function editImage() {
  imageStep.value = 'form'
  imageFile.value = null
  imagePreview.value = null
  imageError.value = ''
  clearImageObjectUrl()
}

function recoverImageFlow() {
  if (imagePreview.value) imageStep.value = 'preview'
  else if (imageFile.value) recognizeImage(imageFile.value)
  else imageStep.value = 'form'
}

function formatConfidence(value) {
  return `${Math.round(Number(value || 0) * 100)}%`
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value || 0)))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${minutes}:${String(remainder).padStart(2, '0')}`
}

function clearVideoObjectUrl() {
  if (videoObjectUrl.value) URL.revokeObjectURL(videoObjectUrl.value)
  videoObjectUrl.value = ''
}

function openVideoModal() {
  videoStep.value = 'form'
  videoFile.value = null
  videoPreview.value = null
  videoError.value = ''
  videoDragActive.value = false
  videoUploadPercent.value = 0
  videoPhase.value = 'upload'
  clearVideoObjectUrl()
  modal.value = 'video'
}

function closeVideoModal() {
  if (videoAbortController?.abort) videoAbortController.abort()
  videoAbortController = null
  videoDragActive.value = false
  clearVideoObjectUrl()
  modal.value = ''
}

function isSupportedVideo(file) {
  return /\.(mp4|mov|mkv|avi|webm)$/i.test(file?.name || '')
}

async function analyzeVideo(file) {
  if (!file) return
  if (!isSupportedVideo(file)) {
    videoError.value = '请选择 MP4、MOV、MKV、AVI 或 WebM 视频文件'
    videoStep.value = 'error'
    return
  }
  if (file.size > 200 * 1024 * 1024) {
    videoError.value = '视频不能超过 200 MB'
    videoStep.value = 'error'
    return
  }

  videoFile.value = file
  videoPreview.value = null
  videoError.value = ''
  clearVideoObjectUrl()
  videoObjectUrl.value = URL.createObjectURL(file)
  if (!videoForm.value.name.trim() || videoForm.value.name === '视频导入素材') {
    videoForm.value.name = file.name.replace(/\.[^.]+$/, '') || '视频导入素材'
  }
  videoStep.value = 'loading'
  videoUploadPercent.value = 0
  videoPhase.value = 'upload'

  const body = new FormData()
  body.append('file', file)

  try {
    const preview = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.timeout = 300000 // 5 分钟超时
      let settled = false

      videoAbortController = {
        abort: () => {
          if (!settled) { settled = true; xhr.abort(); reject(new Error('上传已取消')) }
        }
      }

      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          videoUploadPercent.value = Math.round((e.loaded / e.total) * 100)
        }
      })

      xhr.addEventListener('load', () => {
        if (settled) return
        settled = true
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch (e) {
            reject(new Error('服务器返回数据格式异常'))
          }
          return
        }
        let detail = '请求失败，请稍后重试'
        try { const data = JSON.parse(xhr.responseText); if (data.detail) detail = data.detail } catch {}
        if (xhr.status === 401 && token()) {
          clearToken()
          if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
            window.location.assign('/login')
          }
        }
        reject(new Error(detail))
      })

      xhr.addEventListener('error', () => {
        if (settled) return
        settled = true
        reject(new Error('网络连接失败，请检查网络后重试'))
      })
      xhr.addEventListener('abort', () => {
        if (settled) return
        settled = true
        reject(new Error('上传已取消'))
      })
      xhr.addEventListener('timeout', () => {
        if (settled) return
        settled = true
        reject(new Error('视频处理超时，请尝试更短的视频'))
      })

      xhr.open('POST', '/api/materials/video/preview')
      xhr.setRequestHeader('Authorization', `Bearer ${token()}`)
      const teamId = activeTeamId()
      if (teamId) xhr.setRequestHeader('X-Team-ID', teamId)
      xhr.send(body)
    })

    videoPhase.value = 'done'
    videoPreview.value = preview
    videoStep.value = 'preview'
  } catch (error) {
    if (videoAbortController?.aborted) return
    videoError.value = error.message
    videoStep.value = 'error'
  } finally {
    videoAbortController = null
  }
}

function selectVideo(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  analyzeVideo(file)
}

function dropVideo(event) {
  videoDragActive.value = false
  analyzeVideo(event.dataTransfer?.files?.[0])
}

function leaveVideoDropzone(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) videoDragActive.value = false
}

async function saveVideoMaterial() {
  if (!videoFile.value || !videoPreview.value) return
  videoError.value = ''
  videoStep.value = 'saving'
  const body = new FormData()
  body.append('file', videoFile.value)
  body.append('name', videoForm.value.name)
  body.append('category', videoForm.value.category)
  body.append('content', videoPreview.value.content)
  const controller = new AbortController()
  videoAbortController = controller
  try {
    const material = await api('/materials/video', {
      method: 'POST', body, signal: controller.signal,
    })
    if (controller.signal.aborted) return
    clearVideoObjectUrl()
    modal.value = ''
    await load()
    await openMaterial(material)
    notify('视频文本已确认入库')
  } catch (error) {
    if (controller.signal.aborted) return
    videoError.value = error.message
    videoStep.value = 'error'
  } finally {
    if (videoAbortController === controller) videoAbortController = null
  }
}

function editVideo() {
  videoStep.value = 'form'
  videoFile.value = null
  videoPreview.value = null
  videoError.value = ''
  videoDragActive.value = false
  clearVideoObjectUrl()
}

function recoverVideoFlow() {
  if (videoPreview.value) videoStep.value = 'preview'
  else if (videoFile.value) analyzeVideo(videoFile.value)
  else videoStep.value = 'form'
}

async function upload(event) {
  const file = event.target.files[0]
  if (!file) return
  uploadBusy.value = true
  const body = new FormData()
  body.append('file', file)
  try {
    await api('/materials/upload', { method: 'POST', body })
    await load()
    notify('素材已进入处理队列')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    uploadBusy.value = false
    event.target.value = ''
  }
}

async function saveTextMaterial() {
  const payload = {
    name: textForm.value.name.trim(),
    category: textForm.value.category.trim() || '未分类',
    content: textForm.value.content.trim(),
  }
  if (!payload.name) {
    textError.value = '请输入素材名称'
    return
  }
  if (!payload.content) {
    textError.value = '请输入需要保存的知识内容'
    return
  }

  textForm.value = payload
  textError.value = ''
  textStep.value = 'saving'
  const controller = new AbortController()
  textAbortController = controller
  try {
    const material = await api('/materials/text', {
      method: 'POST', body: payload, signal: controller.signal,
    })
    if (controller.signal.aborted) return
    modal.value = ''
    await load()
    await openMaterial(material)
    textForm.value = newTextForm()
    notify('知识已保存并入库')
  } catch (error) {
    if (controller.signal.aborted) return
    textError.value = error.message
    textStep.value = 'error'
  } finally {
    if (textAbortController === controller) textAbortController = null
  }
}

function editText() {
  textStep.value = 'form'
  textError.value = ''
}

async function remove(id) {
  if (!window.confirm('确定删除这条素材吗？')) return
  try {
    await api(`/materials/${id}`, { method: 'DELETE' })
    if (selectedMaterial.value?.id === id) closeMaterial()
    await load()
    notify('素材已删除')
  } catch (error) { notify(error.message, 'error') }
}

async function process(id) {
  try {
    await api(`/materials/${id}/process`, { method: 'POST' })
    await load()
    notify('处理完成')
  } catch (error) { notify(error.message, 'error') }
}

async function toggleFavorite(item) {
  const nextValue = !item.favorite
  item.favorite = nextValue
  try {
    await api(`/materials/${item.id}/favorite`, { method: nextValue ? 'POST' : 'DELETE' })
    notify(nextValue ? '已加入收藏' : '已取消收藏')
  } catch (error) {
    item.favorite = !nextValue
    notify(error.message, 'error')
  }
}
</script>

<template>
  <AppShell search-placeholder="搜索知识产出..." @search="q = $event" @new="openTextModal">
    <div class="page-wrap materials-page">
      <div class="page-heading">
        <h1>素材管理</h1>
        <p>集中处理多格式素材，转化为 AI 就绪的知识片段。</p>
      </div>

      <section class="panel intake-panel">
        <h3><FileInput /> 采集引擎</h3>
        <div class="intake-grid">
          <button :disabled="uploadBusy" @click="fileInput.click()">
            <Upload /><strong>{{ uploadBusy ? '上传中...' : '本地上传' }}</strong><small>PDF, DOCX, TXT</small>
          </button>
          <input ref="fileInput" hidden type="file" @change="upload" />
          <button @click="openUrlModal"><Link2 /><strong>链接抓取</strong><small>网页、维基</small></button>
          <button @click="openTextModal"><FilePenLine /><strong>手动输入</strong><small>直接编辑器</small></button>
          <button @click="openVideoModal"><Video /><strong>视频导入</strong><small>提取字幕与画面文字</small></button>
          <button @click="openImageModal"><Camera /><strong>图片识别</strong><small>提取文字</small></button>
        </div>
      </section>

      <div class="filterbar">
        <div>
          <button
            v-for="tab in [{ k: 'all', v: '全部素材' }, { k: 'processing', v: '处理中' }, { k: 'ready', v: '已就绪' }, { k: 'failed', v: '失败' }]"
            :key="tab.k"
            :class="{ active: active === tab.k }"
            @click="active = tab.k"
          >{{ tab.v }}</button>
        </div>
        <span>按日期排序</span>
      </div>

      <section class="materials-table panel">
        <div class="table-head"><span>名称</span><span>类型</span><span>大小</span><span>状态</span><span>操作</span></div>
        <div v-for="item in filtered" :key="item.id" class="table-row">
          <span class="file-name"><b>{{ item.name }}</b><small>{{ item.category }}</small></span>
          <span>{{ item.kind }}</span>
          <span>{{ formatBytes(item.size) }}</span>
          <span><b class="status-text" :class="item.status">{{ item.status === 'ready' ? '已就绪' : item.status === 'processing' ? '处理中...' : '失败' }}</b></span>
          <span class="row-actions">
            <button title="预览" @click="openMaterial(item)"><Eye /></button>
            <button title="重试" @click="process(item.id)"><RefreshCw /></button>
            <button title="AI 问答" @click="openMaterialAsk(item)"><MessageSquare /></button>
            <button class="favorite-star" :class="{ active: item.favorite }" :title="item.favorite ? '取消收藏' : '收藏'" @click="toggleFavorite(item)"><Star /></button>
            <button title="删除" @click="remove(item.id)"><Trash2 /></button>
          </span>
        </div>
        <div v-if="!filtered.length" class="empty-state">当前筛选下没有素材</div>
      </section>
    </div>

    <ModalDialog
      v-if="modal === 'text'"
      :title="textModalTitle"
      wide
      :close-disabled="textStep === 'saving'"
      @close="closeTextModal"
    >
      <form v-if="textStep === 'form'" class="manual-entry-form" @submit.prevent="saveTextMaterial">
        <div class="manual-entry-fields">
          <label>素材名称<input v-model="textForm.name" required maxlength="200" @input="textError = ''" /></label>
          <label>分类<input v-model="textForm.category" maxlength="80" @input="textError = ''" /></label>
        </div>
        <label class="manual-entry-editor">
          <span><FilePenLine /> 知识内容 <small>{{ textForm.content.length.toLocaleString() }} 字符</small></span>
          <textarea v-model="textForm.content" required maxlength="100000" spellcheck="false" placeholder="输入需要沉淀的知识内容..." @input="textError = ''"></textarea>
        </label>
        <p v-if="textError" class="manual-entry-error" role="alert">{{ textError }}</p>
        <div class="url-actions">
          <button type="button" class="button ghost" @click="closeTextModal">取消</button>
          <button class="button primary" :disabled="!textForm.name.trim() || !textForm.content.trim()"><Save /> 保存并入库</button>
        </div>
      </form>

      <section v-else-if="textStep === 'saving'" class="url-fetch-state" aria-live="polite">
        <LoaderCircle class="url-spinner" />
        <div><h3>正在写入知识库</h3><p>{{ textForm.name }}</p></div>
        <div class="url-fetch-progress">
          <span class="done"><Check /> 校验名称与正文</span>
          <span class="active"><LoaderCircle /> 保存素材记录</span>
          <span><Circle /> 更新知识索引</span>
        </div>
      </section>

      <section v-else-if="textStep === 'error'" class="url-error-state">
        <AlertTriangle />
        <h3>未能保存手动输入内容</h3>
        <p>{{ textError }}</p>
        <div class="url-actions">
          <button class="button ghost" @click="editText"><ArrowLeft /> 返回编辑</button>
          <button class="button primary" @click="saveTextMaterial"><RefreshCw /> 重新保存</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog
      v-else-if="modal === 'video'"
      :title="videoModalTitle"
      :wide="videoStep !== 'form'"
      :close-disabled="videoStep === 'saving'"
      @close="closeVideoModal"
    >
      <div v-if="videoStep === 'form'" class="video-capture-form">
        <label
          class="video-dropzone"
          :class="{ dragging: videoDragActive }"
          @dragenter.prevent="videoDragActive = true"
          @dragover.prevent="videoDragActive = true"
          @dragleave="leaveVideoDropzone"
          @drop.prevent="dropVideo"
        >
          <input ref="videoInput" hidden type="file" accept=".mp4,.mov,.mkv,.avi,.webm,video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm" @change="selectVideo" />
          <Video />
          <strong>选择视频</strong>
          <small>MP4 / MOV / MKV / AVI / WebM · 200 MB</small>
        </label>
      </div>

      <section v-else-if="videoStep === 'loading' || videoStep === 'saving'" class="url-fetch-state" aria-live="polite">
        <LoaderCircle class="url-spinner" />
        <div>
          <h3>{{ videoStep === 'saving' ? '正在写入知识库' : (videoPhase === 'upload' ? '正在上传视频' : '正在提取视频文本') }}</h3>
          <p>{{ videoForm.name }}</p>
        </div>
        <div class="url-fetch-progress">
          <span :class="{ done: videoPhase !== 'upload', active: videoPhase === 'upload' }">
            <Check v-if="videoPhase !== 'upload'" /><LoaderCircle v-else />
            上传视频{{ videoPhase === 'upload' ? ` ${videoUploadPercent}%` : '' }}
          </span>
          <span :class="{ done: videoStep === 'saving', active: videoStep === 'loading' && videoPhase !== 'upload' }">
            <Check v-if="videoStep === 'saving'" /><LoaderCircle v-else /> 提取内嵌字幕和关键帧文字
          </span>
          <span :class="{ active: videoStep === 'saving' }"><LoaderCircle v-if="videoStep === 'saving'" /><Circle v-else /> 生成素材记录</span>
        </div>
      </section>

      <div v-else-if="videoStep === 'preview' && videoPreview" class="video-preview">
        <div class="video-source-row">
          <Video />
          <span><strong>{{ videoPreview.filename }}</strong><small>{{ videoPreview.width }} × {{ videoPreview.height }} · {{ formatDuration(videoPreview.duration) }}</small></span>
        </div>
        <div class="url-preview-meta video-preview-meta">
          <span><strong>{{ formatBytes(videoPreview.size) }}</strong><small>视频大小</small></span>
          <span><strong>{{ videoPreview.subtitle_lines }}</strong><small>字幕条目</small></span>
          <span><strong>{{ videoPreview.keyframes }}</strong><small>分析关键帧</small></span>
          <span><strong>{{ formatConfidence(videoPreview.confidence) }}</strong><small>画面文字置信度</small></span>
        </div>
        <div class="url-preview-fields">
          <label>素材名称<input v-model="videoForm.name" maxlength="200" /></label>
          <label>分类<input v-model="videoForm.category" maxlength="80" /></label>
        </div>
        <div class="video-text-layout">
          <figure><video :src="videoObjectUrl" controls playsinline preload="metadata"></video></figure>
          <label>
            <span><ScanText /> 提取文本 <small>{{ videoPreview.content.length.toLocaleString() }} 字符</small></span>
            <textarea v-model="videoPreview.content" spellcheck="false"></textarea>
          </label>
        </div>
        <p class="video-extraction-note">已从内嵌字幕和关键帧画面中提取文本，可在入库前修订。</p>
        <div class="url-actions">
          <button class="button ghost" @click="editVideo"><ArrowLeft /> 更换视频</button>
          <button class="button secondary" @click="analyzeVideo(videoFile)"><RefreshCw /> 重新分析</button>
          <button class="button primary" :disabled="!videoForm.name.trim() || !videoPreview.content.trim()" @click="saveVideoMaterial"><Save /> 确认入库</button>
        </div>
      </div>

      <section v-else-if="videoStep === 'error'" class="url-error-state">
        <AlertTriangle />
        <h3>未能完成视频文本提取</h3>
        <p>{{ videoError }}</p>
        <div class="url-actions">
          <button class="button ghost" @click="editVideo"><ArrowLeft /> 更换视频</button>
          <button v-if="videoFile" class="button primary" @click="recoverVideoFlow"><RefreshCw /> {{ videoPreview ? '返回预览' : '重新分析' }}</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog
      v-else-if="modal === 'url'"
      :title="urlModalTitle"
      :wide="urlStep !== 'form'"
      :close-disabled="urlStep === 'saving'"
      @close="closeUrlModal"
    >
      <form v-if="urlStep === 'form'" class="stack-form url-capture-form" @submit.prevent="fetchUrlPreview">
        <label>网页地址<input v-model.trim="urlForm.url" type="url" required placeholder="https://" /></label>
        <div class="url-form-grid">
          <label>素材名称<input v-model="urlForm.name" required maxlength="200" /></label>
          <label>分类<input v-model="urlForm.category" maxlength="80" /></label>
        </div>
        <button class="button primary wide"><Globe2 /> 抓取并预览</button>
      </form>

      <section v-else-if="urlStep === 'loading' || urlStep === 'saving'" class="url-fetch-state" aria-live="polite">
        <LoaderCircle class="url-spinner" />
        <div>
          <h3>{{ urlStep === 'saving' ? '正在写入知识库' : '正在解析网页内容' }}</h3>
          <p>{{ urlStep === 'saving' ? urlForm.name : urlHost }}</p>
        </div>
        <div class="url-fetch-progress">
          <span class="done"><Check /> 校验网页地址</span>
          <span :class="{ done: urlStep === 'saving', active: urlStep === 'loading' }">
            <Check v-if="urlStep === 'saving'" /><LoaderCircle v-else /> 提取并清洗正文
          </span>
          <span :class="{ active: urlStep === 'saving' }"><LoaderCircle v-if="urlStep === 'saving'" /><Circle v-else /> 生成素材记录</span>
        </div>
      </section>

      <div v-else-if="urlStep === 'preview' && urlPreview" class="url-preview">
        <div class="url-source-row">
          <Globe2 />
          <span><strong>{{ urlPreview.host }}</strong><small>{{ urlPreview.url }}</small></span>
          <a :href="urlPreview.url" target="_blank" rel="noopener noreferrer" title="打开原网页"><ExternalLink /></a>
        </div>
        <div class="url-preview-meta">
          <span><strong>{{ formatBytes(urlPreview.size) }}</strong><small>正文大小</small></span>
          <span><strong>{{ urlPreview.characters.toLocaleString() }}</strong><small>字符数</small></span>
          <span><strong>{{ formatTime(urlPreview.fetched_at) }}</strong><small>抓取时间</small></span>
        </div>
        <div class="url-preview-fields">
          <label>素材名称<input v-model="urlForm.name" maxlength="200" /></label>
          <label>分类<input v-model="urlForm.category" maxlength="80" /></label>
        </div>
        <div class="url-preview-heading"><span>正文预览</span><b>{{ urlPreview.title }}</b></div>
        <div class="url-preview-body preview-content-body" v-html="renderMarkdown(urlPreview.content)"></div>
        <div class="url-actions">
          <button class="button ghost" @click="editUrl"><ArrowLeft /> 修改链接</button>
          <button class="button secondary" @click="fetchUrlPreview"><RefreshCw /> 重新抓取</button>
          <button class="button primary" :disabled="!urlForm.name.trim()" @click="saveUrlMaterial"><Save /> 确认入库</button>
        </div>
      </div>

      <section v-else-if="urlStep === 'error'" class="url-error-state">
        <AlertTriangle />
        <h3>未能完成网页抓取</h3>
        <p>{{ urlError }}</p>
        <div class="url-actions">
          <button class="button ghost" @click="editUrl"><ArrowLeft /> 返回修改</button>
          <button class="button primary" @click="recoverUrlFlow"><RefreshCw /> {{ urlPreview ? '返回预览' : '重新抓取' }}</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog
      v-else-if="modal === 'image'"
      :title="imageModalTitle"
      :wide="imageStep !== 'form'"
      :close-disabled="imageStep === 'saving'"
      @close="closeImageModal"
    >
      <div v-if="imageStep === 'form'" class="image-capture-form">
        <label class="image-dropzone" @dragover.prevent @drop.prevent="dropImage">
          <input ref="imageInput" hidden type="file" accept="image/png,image/jpeg,image/bmp,image/tiff" @change="selectImage" />
          <UploadCloud />
          <strong>选择图片</strong>
          <small>PNG / JPEG / BMP / TIFF · 10 MB</small>
        </label>
      </div>

      <section v-else-if="imageStep === 'loading' || imageStep === 'saving'" class="url-fetch-state" aria-live="polite">
        <LoaderCircle class="url-spinner" />
        <div>
          <h3>{{ imageStep === 'saving' ? '正在写入知识库' : '正在定位并识别文字' }}</h3>
          <p>{{ imageForm.name }}</p>
        </div>
        <div class="url-fetch-progress">
          <span class="done"><Check /> 读取图片与方向</span>
          <span :class="{ done: imageStep === 'saving', active: imageStep === 'loading' }">
            <Check v-if="imageStep === 'saving'" /><LoaderCircle v-else /> 定位文字区域并识别
          </span>
          <span :class="{ active: imageStep === 'saving' }"><LoaderCircle v-if="imageStep === 'saving'" /><Circle v-else /> 生成素材记录</span>
        </div>
      </section>

      <div v-else-if="imageStep === 'preview' && imagePreview" class="image-preview">
        <div class="image-source-row">
          <FileImage />
          <span><strong>{{ imagePreview.filename }}</strong><small>{{ imagePreview.width }} × {{ imagePreview.height }} · {{ imagePreview.format }}</small></span>
        </div>
        <div class="url-preview-meta">
          <span><strong>{{ formatBytes(imagePreview.size) }}</strong><small>图片大小</small></span>
          <span><strong>{{ imagePreview.lines }}</strong><small>识别行数</small></span>
          <span><strong>{{ formatConfidence(imagePreview.confidence) }}</strong><small>平均置信度</small></span>
        </div>
        <div class="url-preview-fields">
          <label>素材名称<input v-model="imageForm.name" maxlength="200" /></label>
          <label>分类<input v-model="imageForm.category" maxlength="80" /></label>
        </div>
        <div class="image-ocr-layout">
          <figure><img :src="imageObjectUrl" :alt="imagePreview.filename" /></figure>
          <label>
            <span><ScanText /> 识别文本 <small>{{ imagePreview.content.length.toLocaleString() }} 字符</small></span>
            <textarea v-model="imagePreview.content" spellcheck="false"></textarea>
          </label>
        </div>
        <div class="url-actions">
          <button class="button ghost" @click="editImage"><ArrowLeft /> 更换图片</button>
          <button class="button secondary" @click="recognizeImage(imageFile)"><RefreshCw /> 重新识别</button>
          <button class="button primary" :disabled="!imageForm.name.trim() || !imagePreview.content.trim()" @click="saveImageMaterial"><Save /> 确认入库</button>
        </div>
      </div>

      <section v-else-if="imageStep === 'error'" class="url-error-state">
        <AlertTriangle />
        <h3>未能完成图片识别</h3>
        <p>{{ imageError }}</p>
        <div class="url-actions">
          <button class="button ghost" @click="editImage"><ArrowLeft /> 更换图片</button>
          <button v-if="imageFile" class="button primary" @click="recoverImageFlow"><RefreshCw /> {{ imagePreview ? '返回预览' : '重新识别' }}</button>
        </div>
      </section>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'material' && selectedMaterial" :title="selectedMaterial.name" wide @close="closeMaterial">
      <div class="preview-content material-detail-preview">
        <div v-if="selectedMaterial.origin_url" class="url-source-row compact">
          <Globe2 />
          <span><strong>{{ getHost(selectedMaterial.origin_url) }}</strong><small>{{ selectedMaterial.origin_url }}</small></span>
          <a :href="selectedMaterial.origin_url" target="_blank" rel="noopener noreferrer" title="打开原网页"><ExternalLink /></a>
        </div>
        <div v-if="selectedMaterial.kind === '图片'" class="material-image-preview">
          <LoaderCircle v-if="materialImageLoading" class="url-spinner" />
          <img v-else-if="selectedMaterialImage" :src="selectedMaterialImage" :alt="selectedMaterial.name" />
        </div>
        <div v-if="selectedMaterial.kind === '视频'" class="material-video-preview">
          <LoaderCircle v-if="materialVideoLoading" class="url-spinner" />
          <video v-else-if="selectedMaterialVideo" :src="selectedMaterialVideo" controls playsinline preload="metadata"></video>
        </div>
        <span>{{ selectedMaterial.kind }} · {{ formatBytes(selectedMaterial.size) }} · {{ selectedMaterial.category }}</span>
        <div class="preview-content-body" v-html="renderMarkdown(selectedMaterial.content || '该素材正在处理，完成后可预览文本内容。')"></div>
      </div>
    </ModalDialog>

    <ModalDialog v-else-if="modal === 'ask' && askMaterialItem" :title="`AI 问答 · ${askMaterialItem.name}`" wide @close="closeMaterialAsk">
      <section class="material-ask-dialog">
        <div class="material-ask-preview">
          <header>
            <span><Bot /> 单素材问答 Agent</span>
            <small>{{ askMaterialItem.kind }} · {{ askMaterialItem.category }} · {{ formatBytes(askMaterialItem.size) }}</small>
          </header>
          <div class="material-ask-markdown" v-html="renderMarkdown(askMaterialPreview || '该素材暂无可预览正文。')"></div>
        </div>

        <form class="material-ask-form" @submit.prevent="askMaterialQuestion">
          <label>
            <span><MessageSquare /> 输入问题</span>
            <textarea v-model.trim="askQuestion" maxlength="2000" rows="3" placeholder="围绕当前素材提问，例如：这份文档的核心结论是什么？"></textarea>
          </label>
          <button class="button primary" :disabled="askLoading || !askQuestion.trim()">
            <LoaderCircle v-if="askLoading" class="url-spinner" />
            <Send v-else />
            {{ askLoading ? 'Agent 检索中' : '提问' }}
          </button>
        </form>

        <p v-if="askError" class="form-error material-ask-error" role="alert">{{ askError }}</p>

        <div v-if="askResult" class="material-ask-result">
          <article>
            <h3>润色解释</h3>
            <div class="material-ask-markdown" v-html="renderMarkdown(askResult.answer)"></div>
          </article>
          <footer>
            <span>{{ askResult.mode === 'deepseek-material-agent' ? 'DeepSeek Agent' : '本地素材 Agent' }}</span>
            <small>{{ askResult.agent_note }}</small>
          </footer>
        </div>
      </section>
    </ModalDialog>

    <ToastMessage :message="toast" :type="toastType" />
  </AppShell>
</template>
