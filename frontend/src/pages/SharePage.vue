<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { FileText, Search, Sparkles, MessageSquareText, X } from 'lucide-vue-next'
import { api } from '../api'
import { renderMarkdown } from '../markdown'

const route = useRoute()
const data = ref(null)
const error = ref('')
const q = ref('')
const question = ref('')
const qaAnswer = ref(null)
const qaLoading = ref(false)
const selectedMaterial = ref(null)
const materialModalOpen = ref(false)

const isTeamShare = computed(() => route.meta.shareType === 'team' || route.path.startsWith('/share/team/'))
const materials = computed(() => data.value?.items || data.value?.materials || [])
const ownerName = computed(() => isTeamShare.value ? data.value?.team?.name : data.value?.owner?.nickname)
const filteredMaterials = computed(() => {
  const keyword = q.value.trim()
  if (!keyword) return materials.value
  return materials.value.filter((item) => item.name?.includes(keyword) || item.content?.includes(keyword))
})

async function loadShare() {
  try {
    data.value = await api(isTeamShare.value ? `/share/team/${route.params.id}` : `/share/${route.params.id}`)
  } catch (e) {
    error.value = e.message
  }
}

async function askSharedTeam() {
  if (!question.value.trim() || !isTeamShare.value) return
  qaLoading.value = true
  error.value = ''
  try {
    qaAnswer.value = await api(`/share/team/${route.params.id}/qa`, {
      method: 'POST',
      body: { question: question.value.trim(), lib_ids: [] },
    })
    question.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    qaLoading.value = false
  }
}

function openMaterial(item) {
  selectedMaterial.value = item
  materialModalOpen.value = true
}

function closeMaterial() {
  materialModalOpen.value = false
  selectedMaterial.value = null
}

onMounted(loadShare)
</script>

<template>
  <div class="public-page share-page">
    <header class="public-nav share-nav">
      <div class="share-nav-inner">
        <span class="public-brand share-brand">
          <img src="/zhiyan_logo/screen.png" />
          <div>
            <strong>ZhiYan AI</strong>
            <small>知识进化平台</small>
          </div>
        </span>
        <span class="share-nav-badge">
          <span class="share-nav-dot"></span>
          {{ isTeamShare ? 'TEAM SHARING' : 'READ-ONLY SPACE' }}
        </span>
      </div>
    </header>
    <main>
      <div v-if="error" class="share-error"><h1>无法访问该知识空间</h1><p>{{ error }}</p></div>
      <template v-else-if="data">
        <section class="share-hero">
          <span><Sparkles /> 由 {{ ownerName }} 分享</span>
          <h1>{{ data.name }}</h1>
          <p>{{ data.description }}</p>
          <label><Search /><input v-model="q" placeholder="搜索这个知识空间..." /></label>
        </section>

        <section v-if="isTeamShare" class="share-qa">
          <form @submit.prevent="askSharedTeam">
            <MessageSquareText />
            <input v-model="question" placeholder="在分享范围内提问..." />
            <button class="button primary" :disabled="qaLoading || !question.trim()">{{ qaLoading ? '检索中...' : '提问' }}</button>
          </form>
          <article v-if="qaAnswer">
            <h2>{{ qaAnswer.question }}</h2>
            <div class="share-answer-body" v-html="renderMarkdown(qaAnswer.answer)"></div>
            <small>{{ qaAnswer.sources?.length || 0 }} 条共享来源</small>
          </article>
        </section>

        <section class="public-materials">
          <article v-for="item in filteredMaterials" :key="item.id" class="share-material-card" @click="openMaterial(item)">
            <FileText />
            <div>
              <span>{{ item.category || item.library || '团队素材' }} · {{ item.kind }}</span>
              <h2>{{ item.name }}</h2>
            </div>
          </article>
          <div v-if="!filteredMaterials.length" class="empty-state">该知识空间中暂无素材。</div>
        </section>

        <div v-if="materialModalOpen" class="share-modal-overlay" @click.self="closeMaterial">
          <div class="share-modal">
            <header class="share-modal-header">
              <div>
                <span>{{ selectedMaterial?.category || selectedMaterial?.library || '团队素材' }} · {{ selectedMaterial?.kind }}</span>
                <h2>{{ selectedMaterial?.name }}</h2>
              </div>
              <button class="share-modal-close" @click="closeMaterial"><X /></button>
            </header>
            <div class="share-material-body" v-html="renderMarkdown(selectedMaterial?.content || '暂无内容')"></div>
          </div>
        </div>
      </template>
      <div v-else class="page-loader">打开知识空间...</div>
    </main>
  </div>
</template>

<style scoped>
/* === Enhanced Tech Header === */
.share-nav {
  height: auto;
  background: linear-gradient(180deg, rgba(5, 18, 30, .98) 0%, rgba(8, 22, 36, .92) 100%);
  border-bottom: 1px solid rgba(0, 200, 255, .12);
  box-shadow: 0 1px 20px rgba(0, 180, 240, .06), inset 0 1px 0 rgba(100, 220, 255, .04);
  backdrop-filter: blur(24px);
  position: sticky;
  top: 0;
  z-index: 10;
}

.share-nav::before {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0, 245, 255, .35), rgba(100, 180, 255, .25), transparent);
}

.share-nav-inner {
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 5%;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.share-brand {
  gap: 14px;
  font-size: 0;
}

.share-brand img {
  width: 38px;
  height: 38px;
  border-radius: 6px;
  border: 1px solid rgba(0, 200, 255, .25);
  box-shadow: 0 0 14px rgba(0, 200, 255, .15);
  transition: box-shadow .3s;
}

.share-brand:hover img {
  box-shadow: 0 0 22px rgba(0, 220, 255, .28);
}

.share-brand strong {
  display: block;
  font-size: 19px;
  background: linear-gradient(135deg, var(--cyan) 0%, #7dc9ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.3px;
}

.share-brand small {
  display: block;
  font-size: 11px;
  color: rgba(150, 200, 230, .65);
  margin-top: 2px;
  letter-spacing: .5px;
}

.share-nav-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border: 1px solid rgba(0, 200, 255, .18);
  border-radius: 20px;
  background: rgba(0, 160, 220, .08);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #8ad4f0;
  letter-spacing: 1px;
  backdrop-filter: blur(8px);
}

.share-nav-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 6px var(--cyan);
  animation: share-dot-pulse 2s ease-in-out infinite;
}

@keyframes share-dot-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--cyan); }
  50% { opacity: .4; box-shadow: 0 0 12px var(--cyan); }
}

/* === QA === */
.share-qa {
  display: grid;
  gap: 14px;
  margin: 18px auto;
  max-width: 980px;
}

.share-qa form {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 8px;
  background: rgba(7, 25, 45, .72);
  padding: 12px;
}

.share-qa input {
  min-width: 0;
}

.share-qa article {
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 8px;
  background: rgba(7, 25, 45, .72);
  padding: 16px;
}

.share-qa h2 {
  margin: 0 0 10px;
  font-size: 18px;
}

.share-answer-body {
  margin: 0 0 10px;
  line-height: 1.7;
  word-break: break-word;
}

.share-answer-body :where(h1, h2, h3) {
  margin: 16px 0 8px;
}

.share-answer-body :where(ul, ol) {
  padding-left: 22px;
  margin: 8px 0;
}

.share-answer-body li {
  margin: 4px 0;
}

.share-answer-body code {
  background: rgba(125, 249, 255, .08);
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: .9em;
}

.share-answer-body pre {
  background: rgba(7, 25, 45, .9);
  border: 1px solid rgba(125, 249, 255, .12);
  border-radius: 6px;
  padding: 14px;
  overflow-x: auto;
}

.share-material-body {
  margin-top: 6px;
  line-height: 1.8;
  word-break: break-word;
}

.share-material-body :where(h1, h2, h3, h4) {
  margin: 16px 0 8px;
  color: var(--text);
}

.share-material-body :where(ul, ol) {
  padding-left: 22px;
  margin: 8px 0;
}

.share-material-body li {
  margin: 4px 0;
}

.share-material-body code {
  background: rgba(125, 249, 255, .08);
  border: 1px solid rgba(125, 249, 255, .14);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: .9em;
}

.share-material-body pre {
  background: rgba(0, 0, 0, .25);
  border: 1px solid rgba(125, 249, 255, .12);
  border-radius: 6px;
  padding: 14px;
  overflow-x: auto;
  margin: 10px 0;
}

.share-material-body blockquote {
  border-left: 3px solid var(--cyan);
  padding: 4px 0 4px 14px;
  margin: 10px 0;
  color: var(--muted);
}

/* Card style for material list */
.share-material-card {
  cursor: pointer;
  transition: background .15s, border-color .15s, transform .15s;
}

.share-material-card:hover {
  background: rgba(125, 249, 255, .06);
  border-color: rgba(125, 249, 255, .22);
  transform: translateY(-1px);
}

.share-material-card:active {
  transform: translateY(0);
}

/* Modal */
.share-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 900;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 60px 20px 40px;
  background: rgba(0, 0, 0, .55);
  backdrop-filter: blur(4px);
  overflow-y: auto;
}

.share-modal {
  width: 100%;
  max-width: 900px;
  background: var(--bg-card);
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 14px;
  padding: 32px 36px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, .5);
}

.share-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(125, 249, 255, .12);
}

.share-modal-header span {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: .5px;
}

.share-modal-header h2 {
  margin: 4px 0 0;
  font-size: 24px;
}

.share-modal-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--outline);
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: background .15s, color .15s;
}

.share-modal-close:hover {
  background: rgba(125, 249, 255, .1);
  color: var(--text);
}

@media (max-width: 720px) {
  .share-qa form {
    grid-template-columns: 1fr;
  }

  .share-modal {
    padding: 20px 16px;
    border-radius: 12px;
  }

  .share-modal-header h2 {
    font-size: 20px;
  }

  .share-modal-overlay {
    padding: 20px 10px;
  }
}
</style>
