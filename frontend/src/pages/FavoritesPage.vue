<script setup>
import { onMounted, ref } from 'vue'
import { BookOpenText, Clock3, Database, Eye, Star, Trash2 } from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import ModalDialog from '../components/ModalDialog.vue'
import ToastMessage from '../components/ToastMessage.vue'
import { api, formatBytes } from '../api'
import { renderMarkdown } from '../markdown'

const items = ref([])
const loading = ref(true)
const error = ref('')
const selected = ref(null)
const toast = ref('')
const toastType = ref('success')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api('/favorites')
    items.value = data.items || []
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function notify(message, type = 'success') {
  toast.value = message
  toastType.value = type
  window.setTimeout(() => { toast.value = '' }, 2600)
}

async function removeFavorite(item) {
  try {
    await api(`/materials/${item.id}/favorite`, { method: 'DELETE' })
    items.value = items.value.filter((entry) => entry.id !== item.id)
    if (selected.value?.id === item.id) selected.value = null
    notify('已取消收藏')
  } catch (err) {
    notify(err.message, 'error')
  }
}

function formatTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <AppShell search-placeholder="搜索收藏文档...">
    <div class="page-wrap favorites-page">
      <section class="favorites-hero">
        <div>
          <span class="eyebrow"><Star /> Favorite Vault</span>
          <h1>收藏夹</h1>
          <p>沉淀高频使用的文档素材，方便再次预览、问答和进入知识进化流程。</p>
        </div>
        <aside>
          <strong>{{ items.length }}</strong>
          <span>收藏文档</span>
        </aside>
      </section>

      <div v-if="loading" class="page-loader">正在读取收藏文档...</div>
      <div v-else-if="error" class="empty-state">{{ error }}</div>
      <section v-else-if="items.length" class="favorite-list">
        <article v-for="item in items" :key="item.id" class="favorite-card">
          <div class="favorite-mark"><BookOpenText /></div>
          <div class="favorite-main">
            <span>{{ item.kind }} / {{ item.category }}</span>
            <h2>{{ item.name }}</h2>
            <p>{{ item.content || '该素材暂无可预览正文。' }}</p>
            <div class="favorite-meta">
              <small><Database /> {{ formatBytes(item.size) }}</small>
              <small><Clock3 /> {{ formatTime(item.favorite_at) }}</small>
            </div>
          </div>
          <div class="favorite-actions">
            <button class="button secondary" @click="selected = item"><Eye /> 预览</button>
            <button class="button ghost" @click="removeFavorite(item)"><Trash2 /> 取消收藏</button>
          </div>
        </article>
      </section>
      <section v-else class="favorite-empty">
        <Star />
        <h2>还没有收藏文档</h2>
        <p>前往素材管理页，点击素材操作区的星标即可加入收藏。</p>
        <button class="button primary" @click="$router.push('/materials')"><Database /> 前往素材管理</button>
      </section>
    </div>

    <ModalDialog v-if="selected" :title="selected.name" wide @close="selected = null">
      <div class="preview-content material-detail-preview">
        <span>{{ selected.kind }} / {{ selected.category }} / {{ formatBytes(selected.size) }}</span>
        <div class="preview-content-body" v-html="renderMarkdown(selected.content || '该素材暂无可预览正文。')"></div>
      </div>
    </ModalDialog>
    <ToastMessage :message="toast" :type="toastType" />
  </AppShell>
</template>
