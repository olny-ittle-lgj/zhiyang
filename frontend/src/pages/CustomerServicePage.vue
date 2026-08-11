<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  FileText,
  LifeBuoy,
  LoaderCircle,
  MessageCircle,
  MessageCircleQuestion,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Workflow,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import { api, apiStream } from '../api'
import { renderMarkdown } from '../markdown'

const router = useRouter()
const knowledge = ref(null)
const selectedCategory = ref('getting-started')
const selectedArticle = ref(null)
const question = ref('')
const messages = ref([
  {
    id: 'welcome',
    role: 'assistant',
    content: '你好，我是知衍客服 Agent。我可以结合项目知识库，帮你梳理页面入口、操作流程、Agent 配置和常见报错。',
  },
])
const latestResult = ref(null)
const messageList = ref(null)
const composer = ref(null)
const loading = ref(true)
const asking = ref(false)
const error = ref('')
let streamController = null

const categoryIcons = {
  'getting-started': Sparkles,
  materials: BookOpen,
  evolution: Workflow,
  games: Bot,
  graph: CircleHelp,
  account: ShieldCheck,
  policy: LifeBuoy,
}

const categories = computed(() => knowledge.value?.categories || [])
const articles = computed(() => knowledge.value?.articles || [])
const filteredArticles = computed(() => articles.value.filter((article) => article.category === selectedCategory.value))
const categoryCounts = computed(() => Object.fromEntries(
  categories.value.map((category) => [category.id, articles.value.filter((article) => article.category === category.id).length]),
))
const referenceArticle = computed(() => latestResult.value?.article || selectedArticle.value || filteredArticles.value[0] || articles.value[0] || null)
const relatedArticles = computed(() => latestResult.value?.related || [])

function categoryIcon(categoryId) {
  return categoryIcons[categoryId] || FileText
}

function scrollToLatest() {
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

async function loadKnowledge() {
  loading.value = true
  error.value = ''
  try {
    knowledge.value = await api('/customer-service/knowledge')
    selectedArticle.value = knowledge.value.articles?.[0] || null
    selectedCategory.value = selectedArticle.value?.category || 'getting-started'
  } catch (loadError) {
    error.value = loadError.message
  } finally {
    loading.value = false
  }
}

function selectCategory(categoryId) {
  selectedCategory.value = categoryId
  latestResult.value = null
  selectedArticle.value = articles.value.find((article) => article.category === categoryId) || null
}

function selectArticle(article) {
  selectedCategory.value = article.category
  selectedArticle.value = article
  latestResult.value = null
}

function buildHistory() {
  return messages.value
    .filter((message) => (message.role === 'user' || message.role === 'assistant') && message.content)
    .slice(-16)
    .map((message) => ({ role: message.role, content: message.content }))
}

function parseStreamEvent(block) {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('\n')
    .trim()
  if (!data) return null
  return JSON.parse(data)
}

function applyKnowledgeResult(result) {
  if (!result?.article) return
  selectedCategory.value = result.article.category
  selectedArticle.value = result.article
}

function handleStreamEvent(event, assistantId) {
  if (!event) return
  const assistantMessage = messages.value.find((message) => message.id === assistantId)
  if (event.type === 'context') {
    latestResult.value = { ...(latestResult.value || {}), ...event }
    applyKnowledgeResult(event)
    return
  }
  if (event.type === 'delta') {
    if (!assistantMessage) return
    assistantMessage.content += String(event.content || '')
    assistantMessage.streamStatus = '正在流式输出答案'
    scrollToLatest()
    return
  }
  if (event.type === 'done') {
    latestResult.value = event.result || latestResult.value
    applyKnowledgeResult(event.result)
    if (!assistantMessage) return
    assistantMessage.content = event.result?.answer || assistantMessage.content
    assistantMessage.source = event.result?.source || ''
    assistantMessage.agentNote = event.result?.agent_note || ''
    assistantMessage.streaming = false
    assistantMessage.streamStatus = ''
    return
  }
  if (event.type === 'error') {
    throw new Error(event.message || '客服 Agent 调用失败')
  }
}

async function ask() {
  const value = question.value.trim()
  if (!value || asking.value) return

  error.value = ''
  const history = buildHistory()
  const assistantId = `assistant-${Date.now()}`
  messages.value.push({
    id: `user-${Date.now()}`,
    role: 'user',
    content: value,
  })
  messages.value.push({
    id: assistantId,
    role: 'assistant',
    content: '',
    streaming: true,
    streamStatus: '正在调用相关知识库生成答案',
  })
  question.value = ''
  asking.value = true
  streamController = new AbortController()
  scrollToLatest()

  try {
    const response = await apiStream('/customer-service/ask/stream', {
      method: 'POST',
      body: { question: value, history },
      signal: streamController.signal,
    })
    if (!response.body) throw new Error('客服 Agent 未返回可读取的流式内容')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const consume = (chunk) => {
      buffer += chunk
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach((block) => {
        const event = parseStreamEvent(block)
        handleStreamEvent(event, assistantId)
      })
    }
    while (true) {
      const { done, value: chunk } = await reader.read()
      if (done) break
      consume(decoder.decode(chunk, { stream: true }))
    }
    consume(decoder.decode())
    if (buffer.trim()) handleStreamEvent(parseStreamEvent(buffer), assistantId)
    const assistantMessage = messages.value.find((message) => message.id === assistantId)
    if (assistantMessage?.streaming) {
      assistantMessage.streaming = false
      assistantMessage.streamStatus = ''
    }
  } catch (askError) {
    const assistantMessage = messages.value.find((message) => message.id === assistantId)
    if (assistantMessage && !assistantMessage.content) {
      messages.value = messages.value.filter((message) => message.id !== assistantId)
    } else if (assistantMessage) {
      assistantMessage.streaming = false
      assistantMessage.streamStatus = ''
    }
    error.value = askError.message
  } finally {
    streamController = null
    asking.value = false
    scrollToLatest()
  }
}

function askSuggestion(value) {
  question.value = value
  nextTick(() => {
    composer.value?.focus()
  })
  ask()
}

function handleComposerKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    ask()
  }
}

function openRoute(route) {
  if (route) router.push(route)
}

watch(() => messages.value.length, scrollToLatest)

onMounted(() => {
  loadKnowledge()
  scrollToLatest()
})
</script>

<template>
  <AppShell search-placeholder="搜索客服知识...">
    <div v-if="loading" class="page-loader">正在连接客服知识库...</div>
    <div v-else-if="error && !knowledge" class="page-loader customer-service-error">
      <LifeBuoy />
      <span>{{ error }}</span>
      <button class="button primary" type="button" @click="loadKnowledge">
        <RefreshCw />
        重新加载
      </button>
    </div>
    <div v-else class="page-wrap customer-service-page">
      <header class="customer-service-hero">
        <div>
          <span class="customer-service-eyebrow"><MessageCircleQuestion /> SERVICE AGENT / 在线客服</span>
          <h1>客服中心</h1>
          <p>直接和客服 Agent 对话，获取本项目页面操作、知识流程与 Agent 配置的具体说明。</p>
        </div>
        <div class="customer-service-status">
          <span class="service-status-dot"></span>
          <div>
            <strong>DeepSeek 客服 Agent</strong>
            <small>已接入 {{ knowledge.stats.article_count }} 篇项目知识文档 · 支持多轮对话</small>
          </div>
        </div>
      </header>

      <section class="customer-service-layout">
        <aside class="customer-service-sidebar">
          <section class="customer-sidebar-section customer-topic-section">
            <div class="customer-sidebar-heading">
              <span><Search /> KNOWLEDGE INDEX</span>
              <strong>相关知识</strong>
            </div>
            <nav class="customer-topic-list" aria-label="客服知识分类">
              <button
                v-for="category in categories"
                :key="category.id"
                type="button"
                :class="{ active: selectedCategory === category.id }"
                @click="selectCategory(category.id)"
              >
                <component :is="categoryIcon(category.id)" />
                <span><strong>{{ category.label }}</strong><small>{{ category.description }}</small></span>
                <b>{{ categoryCounts[category.id] }}</b>
              </button>
            </nav>
            <div class="customer-article-list" aria-label="主题下的知识文档">
              <button
                v-for="article in filteredArticles"
                :key="article.id"
                type="button"
                :class="{ active: selectedArticle?.id === article.id }"
                @click="selectArticle(article)"
              >
                <FileText />
                <span>{{ article.title }}</span>
                <ChevronRight />
              </button>
            </div>
          </section>

          <section class="customer-sidebar-section customer-reference-section">
            <div class="customer-sidebar-heading">
              <span><FileText /> PROJECT REFERENCE</span>
              <strong>知识详情</strong>
            </div>
            <div v-if="referenceArticle" class="customer-reference-content">
              <h2>{{ referenceArticle.title }}</h2>
              <p>{{ referenceArticle.summary }}</p>
              <ol v-if="referenceArticle.steps?.length">
                <li v-for="step in referenceArticle.steps.slice(0, 4)" :key="step">{{ step }}</li>
              </ol>
              <span class="customer-reference-source"><ShieldCheck /> {{ referenceArticle.source }}</span>
              <button
                v-if="referenceArticle.route && referenceArticle.route !== '/customer-service'"
                type="button"
                class="customer-reference-link"
                @click="openRoute(referenceArticle.route)"
              >
                {{ referenceArticle.route_label }}
                <ExternalLink />
              </button>
            </div>
            <p v-else class="customer-reference-empty">点击左侧知识文档查看具体内容。</p>
          </section>

          <section v-if="relatedArticles.length" class="customer-sidebar-section customer-related-section">
            <div class="customer-sidebar-heading">
              <span><ChevronRight /> RELATED TOPICS</span>
              <strong>相关主题</strong>
            </div>
            <button
              v-for="article in relatedArticles"
              :key="article.id"
              type="button"
              @click="selectArticle(article)"
            >
              <span><strong>{{ article.title }}</strong><small>{{ article.summary }}</small></span>
              <ChevronRight />
            </button>
          </section>
        </aside>

        <main class="customer-chat-panel">
          <header class="customer-chat-header">
            <div class="customer-chat-identity">
              <span class="customer-chat-avatar"><Bot /></span>
              <span>
                <strong>知衍客服 Agent</strong>
                <small>项目操作与使用规范</small>
              </span>
            </div>
            <span class="customer-chat-mode"><i></i> 多轮对话</span>
          </header>

          <div ref="messageList" class="customer-chat-messages" role="log" aria-live="polite">
            <article
              v-for="message in messages"
              :key="message.id"
              class="customer-chat-message"
              :class="`is-${message.role}`"
            >
              <span class="customer-message-avatar" aria-hidden="true">
                <Bot v-if="message.role === 'assistant'" />
                <MessageCircle v-else />
              </span>
              <div class="customer-message-body">
                <div class="customer-message-meta">
                  <strong>{{ message.role === 'assistant' ? '知衍客服 Agent' : '我' }}</strong>
                  <small v-if="message.role === 'assistant'">
                    {{ message.streaming ? (message.content ? '正在输出回答' : '正在调用知识库') : 'AI SUPPORT' }}
                  </small>
                </div>
                <template v-if="message.role === 'assistant'">
                  <div
                    v-if="message.content"
                    class="customer-message-bubble customer-markdown"
                    :class="{ 'is-streaming': message.streaming }"
                    v-html="renderMarkdown(message.content)"
                  ></div>
                  <div v-else-if="message.streaming" class="customer-message-bubble customer-loading-bubble">
                    <LoaderCircle />
                    {{ message.streamStatus || '正在调用相关知识库生成答案' }}
                  </div>
                </template>
                <div v-else class="customer-message-bubble">{{ message.content }}</div>
                <span v-if="message.source" class="customer-message-source">
                  <FileText />
                  知识依据：{{ message.source }}
                </span>
              </div>
            </article>
          </div>

          <div v-if="error && knowledge" class="customer-chat-error" role="alert">
            <LifeBuoy />
            <span>{{ error }}</span>
            <button type="button" title="关闭错误提示" aria-label="关闭错误提示" @click="error = ''">×</button>
          </div>

          <div v-if="knowledge?.suggested_questions?.length" class="customer-suggestions">
            <div class="customer-suggestions-heading">
              <Sparkles />
              <span>推荐提问</span>
            </div>
            <button
              v-for="suggestion in knowledge.suggested_questions"
              :key="suggestion"
              type="button"
              :disabled="asking"
              @click="askSuggestion(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>

          <form class="customer-composer" @submit.prevent="ask">
            <textarea
              ref="composer"
              v-model="question"
              rows="1"
              maxlength="2000"
              placeholder="输入你遇到的项目操作问题..."
              aria-label="输入客服问题"
              @keydown="handleComposerKeydown"
            ></textarea>
            <button
              class="customer-send-button"
              type="submit"
              title="发送消息"
              aria-label="发送消息"
              :disabled="asking || !question.trim()"
            >
              <LoaderCircle v-if="asking" class="is-spinning" />
              <Send v-else />
            </button>
          </form>
          <div class="customer-composer-note">
            <ShieldCheck />
            <span>客服 Agent 仅依据本项目知识库回答，不会索要或展示 API Key 等敏感凭据。</span>
          </div>
        </main>

      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.customer-service-page {
  min-height: calc(100vh - 118px);
  padding-bottom: 58px;
}

.customer-service-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  padding: 18px 0 24px;
  border-bottom: 1px solid rgba(125, 249, 255, .15);
}

.customer-service-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #a2ffd6;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  letter-spacing: .12em;
}

.customer-service-eyebrow svg {
  width: 16px;
  color: #7df9ff;
}

.customer-service-hero h1 {
  margin: 12px 0 8px;
  color: #f1fbff;
  font-size: 42px;
  line-height: 1;
}

.customer-service-hero p {
  max-width: 620px;
  margin: 0;
  color: #a9bfca;
  font-size: 13px;
  line-height: 1.65;
}

.customer-service-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 260px;
  padding: 12px 14px;
  border: 1px solid rgba(162, 255, 214, .24);
  border-radius: 8px;
  background: rgba(12, 48, 49, .34);
}

.service-status-dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #a2ffd6;
  box-shadow: 0 0 12px rgba(162, 255, 214, .8);
}

.customer-service-status strong,
.customer-service-status small {
  display: block;
}

.customer-service-status strong {
  color: #d7fff3;
  font-size: 12px;
}

.customer-service-status small {
  margin-top: 4px;
  color: #9cc4ba;
  font-size: 9px;
}

.customer-service-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 292px;
  gap: 18px;
  margin-top: 18px;
  align-items: start;
}

.customer-chat-panel,
.customer-sidebar-section {
  border: 1px solid rgba(125, 249, 255, .15);
  border-radius: 8px;
  background: rgba(6, 21, 39, .84);
  box-shadow: 0 18px 44px rgba(0, 0, 0, .18);
}

.customer-chat-panel {
  display: grid;
  grid-template-rows: auto minmax(390px, 1fr) auto auto auto;
  min-width: 0;
  min-height: 680px;
  overflow: hidden;
}

.customer-chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
  border-bottom: 1px solid rgba(125, 249, 255, .13);
  background: rgba(4, 15, 31, .62);
}

.customer-chat-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.customer-chat-avatar,
.customer-message-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 50%;
}

.customer-chat-avatar {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(125, 249, 255, .36);
  background: rgba(125, 249, 255, .1);
  color: #7df9ff;
}

.customer-chat-avatar svg {
  width: 19px;
}

.customer-chat-identity strong,
.customer-chat-identity small {
  display: block;
}

.customer-chat-identity strong {
  color: #effcff;
  font-size: 13px;
}

.customer-chat-identity small {
  margin-top: 3px;
  color: #819cad;
  font-size: 10px;
}

.customer-chat-mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  color: #a2ffd6;
  font-family: "JetBrains Mono", monospace;
  font-size: 9px;
  letter-spacing: .06em;
}

.customer-chat-mode i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #a2ffd6;
  box-shadow: 0 0 8px rgba(162, 255, 214, .7);
}

.customer-chat-messages {
  min-height: 0;
  overflow: auto;
  padding: 22px 22px 16px;
  background:
    linear-gradient(rgba(125, 249, 255, .025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(125, 249, 255, .025) 1px, transparent 1px);
  background-size: 28px 28px;
  scrollbar-color: rgba(125, 249, 255, .3) transparent;
}

.customer-chat-message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 820px;
  margin: 0 auto 18px;
}

.customer-chat-message.is-user {
  flex-direction: row-reverse;
}

.customer-message-avatar {
  width: 28px;
  height: 28px;
  margin-top: 2px;
  border: 1px solid rgba(125, 249, 255, .22);
  background: rgba(125, 249, 255, .07);
  color: #7df9ff;
}

.is-user .customer-message-avatar {
  border-color: rgba(255, 196, 111, .3);
  background: rgba(255, 196, 111, .08);
  color: #ffd18c;
}

.customer-message-avatar svg {
  width: 15px;
}

.customer-message-body {
  min-width: 0;
  max-width: min(78%, 720px);
}

.is-user .customer-message-body {
  text-align: right;
}

.customer-message-meta {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin: 0 4px 5px;
}

.is-user .customer-message-meta {
  justify-content: flex-end;
}

.customer-message-meta strong {
  color: #d9f4f8;
  font-size: 10px;
}

.customer-message-meta small {
  color: #6d8999;
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
}

.customer-message-bubble {
  padding: 11px 14px;
  border: 1px solid rgba(125, 249, 255, .17);
  border-radius: 3px 12px 12px 12px;
  background: rgba(7, 32, 53, .86);
  color: #d8edf2;
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  text-align: left;
}

.is-user .customer-message-bubble {
  border-color: rgba(255, 196, 111, .25);
  border-radius: 12px 3px 12px 12px;
  background: rgba(66, 51, 37, .58);
  color: #ffecd2;
}

.customer-message-source {
  display: inline-flex;
  align-items: flex-start;
  gap: 5px;
  margin: 6px 4px 0;
  color: #779aaa;
  font-size: 9px;
  line-height: 1.45;
  text-align: left;
}

.customer-message-source svg {
  width: 12px;
  flex: 0 0 auto;
  margin-top: 1px;
  color: #7df9ff;
}

.customer-loading-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #9dc8d1;
}

.customer-loading-bubble svg {
  width: 14px;
  animation: customer-spin 1s linear infinite;
}

.customer-chat-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 18px 10px;
  padding: 9px 11px;
  border: 1px solid rgba(255, 150, 119, .34);
  border-radius: 6px;
  background: rgba(82, 36, 38, .35);
  color: #ffc1ae;
  font-size: 10px;
  line-height: 1.5;
}

.customer-chat-error > svg {
  width: 15px;
  flex: 0 0 auto;
}

.customer-chat-error span {
  min-width: 0;
}

.customer-chat-error button {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  margin-left: auto;
  border: 0;
  background: transparent;
  color: #ffc1ae;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.customer-suggestions {
  display: flex;
  align-items: center;
  gap: 7px;
  overflow-x: auto;
  padding: 0 18px 10px;
  scrollbar-width: thin;
}

.customer-suggestions-heading {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  color: #9bb3c0;
  font-size: 9px;
}

.customer-suggestions-heading svg {
  width: 13px;
  color: #a2ffd6;
}

.customer-suggestions button {
  flex: 0 0 auto;
  max-width: 270px;
  overflow: hidden;
  padding: 6px 9px;
  border: 1px solid rgba(125, 249, 255, .15);
  border-radius: 5px;
  background: rgba(125, 249, 255, .045);
  color: #a8c5d0;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.customer-suggestions button:hover:not(:disabled) {
  border-color: rgba(125, 249, 255, .46);
  color: #7df9ff;
}

.customer-suggestions button:disabled {
  cursor: wait;
  opacity: .55;
}

.customer-composer {
  display: flex;
  align-items: flex-end;
  gap: 9px;
  margin: 0 18px;
  padding: 12px 0 8px;
  border-top: 1px solid rgba(125, 249, 255, .13);
}

.customer-composer textarea {
  min-height: 44px;
  max-height: 120px;
  flex: 1;
  resize: vertical;
  padding: 12px 13px;
  border: 1px solid rgba(125, 249, 255, .22);
  border-radius: 6px;
  outline: 0;
  background: rgba(3, 13, 28, .9);
  color: #ecfbff;
  font: inherit;
  font-size: 12px;
  line-height: 1.5;
}

.customer-composer textarea::placeholder {
  color: #668596;
}

.customer-composer textarea:focus {
  border-color: rgba(125, 249, 255, .72);
  box-shadow: 0 0 0 3px rgba(125, 249, 255, .08);
}

.customer-send-button {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  border: 1px solid rgba(125, 249, 255, .4);
  border-radius: 6px;
  background: #2cabb7;
  color: #031a28;
  cursor: pointer;
  transition: background .16s ease, transform .16s ease, opacity .16s ease;
}

.customer-send-button:hover:not(:disabled) {
  background: #72f0dc;
  transform: translateY(-1px);
}

.customer-send-button:disabled {
  cursor: not-allowed;
  opacity: .38;
}

.customer-send-button svg {
  width: 17px;
}

.customer-send-button .is-spinning {
  animation: customer-spin 1s linear infinite;
}

.customer-composer-note {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  padding: 0 18px 15px;
  color: #6f8d9c;
  font-size: 9px;
  line-height: 1.45;
}

.customer-composer-note svg {
  width: 13px;
  flex: 0 0 auto;
  color: #a2ffd6;
}

.customer-service-sidebar {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.customer-sidebar-section {
  overflow: hidden;
}

.customer-sidebar-heading {
  display: grid;
  gap: 5px;
  padding: 14px 15px 12px;
  border-bottom: 1px solid rgba(125, 249, 255, .12);
}

.customer-sidebar-heading span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #7df9ff;
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
  letter-spacing: .1em;
}

.customer-sidebar-heading span svg {
  width: 13px;
}

.customer-sidebar-heading strong {
  color: #e8f9fc;
  font-size: 13px;
}

.customer-topic-list {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.customer-topic-list button {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 9px 7px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: #8ca6b5;
  text-align: left;
  cursor: pointer;
  transition: background .16s ease, border-color .16s ease, transform .16s ease;
}

.customer-topic-list button:hover,
.customer-topic-list button.active {
  border-color: rgba(125, 249, 255, .2);
  background: rgba(125, 249, 255, .08);
  color: #7df9ff;
  transform: translateX(2px);
}

.customer-topic-list button > svg {
  width: 16px;
}

.customer-topic-list button span {
  min-width: 0;
}

.customer-topic-list button strong,
.customer-topic-list button small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-topic-list button strong {
  color: #d8eff6;
  font-size: 10px;
}

.customer-topic-list button small {
  margin-top: 3px;
  color: #718b9a;
  font-size: 8px;
}

.customer-topic-list button b {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(125, 249, 255, .1);
  color: #9dbdcc;
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
}

.customer-reference-content {
  padding: 14px 15px 15px;
}

.customer-reference-content h2 {
  margin: 0;
  color: #ecfbff;
  font-size: 15px;
  line-height: 1.35;
}

.customer-reference-content > p {
  margin: 7px 0 0;
  color: #9bb3bf;
  font-size: 10px;
  line-height: 1.55;
}

.customer-reference-content ol {
  display: grid;
  gap: 7px;
  margin: 13px 0 0;
  padding: 0 0 0 16px;
  color: #bdd5dd;
  font-size: 10px;
  line-height: 1.5;
}

.customer-reference-content li::marker {
  color: #7df9ff;
  font-family: "JetBrains Mono", monospace;
}

.customer-reference-source {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: 13px;
  color: #7896a4;
  font-size: 9px;
  line-height: 1.45;
}

.customer-reference-source svg {
  width: 13px;
  flex: 0 0 auto;
  color: #a2ffd6;
}

.customer-reference-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 13px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #7df9ff;
  font-size: 10px;
  cursor: pointer;
}

.customer-reference-link:hover {
  color: #a2ffd6;
}

.customer-reference-link svg {
  width: 13px;
}

.customer-reference-empty {
  margin: 0;
  padding: 15px;
  color: #829dac;
  font-size: 10px;
  line-height: 1.6;
}

.customer-related-section > button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px;
  align-items: center;
  gap: 8px;
  width: calc(100% - 20px);
  margin: 10px;
  padding: 9px 0;
  border: 0;
  border-bottom: 1px solid rgba(125, 249, 255, .1);
  background: transparent;
  color: #d7eff5;
  text-align: left;
  cursor: pointer;
}

.customer-related-section > button:last-child {
  margin-bottom: 2px;
  border-bottom: 0;
}

.customer-related-section > button:hover {
  color: #7df9ff;
}

.customer-related-section > button span {
  min-width: 0;
}

.customer-related-section > button strong,
.customer-related-section > button small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-related-section > button strong {
  font-size: 10px;
}

.customer-related-section > button small {
  margin-top: 3px;
  color: #7894a7;
  font-size: 8px;
}

.customer-related-section > button > svg {
  width: 14px;
}

.customer-service-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.customer-service-error svg {
  width: 17px;
  color: #f5c86b;
}

.customer-service-error .button svg {
  width: 14px;
}

@keyframes customer-spin {
  to { transform: rotate(360deg); }
}

@keyframes customer-caret-blink {
  50% { opacity: 0; }
}

@media (max-width: 980px) {
  .customer-service-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .customer-service-sidebar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }

  .customer-related-section {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .customer-service-page {
    padding-top: 18px;
  }

  .customer-service-hero {
    display: grid;
    align-items: start;
    gap: 16px;
  }

  .customer-service-hero h1 {
    font-size: 32px;
  }

  .customer-service-status {
    min-width: 0;
  }

  .customer-chat-panel {
    min-height: 620px;
  }

  .customer-chat-header {
    padding: 13px 14px;
  }

  .customer-chat-mode {
    font-size: 8px;
  }

  .customer-chat-messages {
    padding: 18px 12px 12px;
  }

  .customer-message-body {
    max-width: 84%;
  }

  .customer-composer {
    margin: 0 12px;
  }

  .customer-composer-note {
    padding: 0 12px 13px;
  }

  .customer-suggestions {
    padding-right: 12px;
    padding-left: 12px;
  }

  .customer-service-sidebar {
    grid-template-columns: 1fr;
  }

  .customer-related-section {
    grid-column: auto;
  }
}

/* Final layout pass: keep the knowledge rail left and the conversation dominant. */
.customer-service-page {
  max-width: 1540px !important;
  padding: 34px 40px 52px !important;
}

.customer-service-hero {
  padding: 14px 0 22px !important;
}

.customer-service-layout {
  display: grid !important;
  grid-template-columns: minmax(220px, 24%) minmax(0, 76%) !important;
  grid-template-areas: "knowledge conversation" !important;
  gap: 20px !important;
  align-items: stretch !important;
  min-height: 680px;
}

.customer-service-sidebar {
  display: flex !important;
  grid-area: knowledge !important;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.customer-chat-panel {
  grid-area: conversation !important;
  width: 100% !important;
  min-width: 0 !important;
  height: 680px;
  min-height: 680px !important;
  align-self: stretch;
}

.customer-sidebar-section {
  width: 100%;
  min-width: 0;
  background: rgba(6, 21, 39, .9) !important;
}

.customer-topic-section {
  flex: 0 0 auto;
}

.customer-reference-section {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden auto;
}

.customer-sidebar-heading {
  min-width: 0;
  padding: 15px 16px 12px !important;
}

.customer-sidebar-heading span,
.customer-sidebar-heading strong {
  min-width: 0;
}

.customer-sidebar-heading span {
  font-size: 8px !important;
}

.customer-sidebar-heading strong {
  font-size: 15px !important;
}

.customer-topic-list {
  gap: 4px !important;
  padding: 10px !important;
}

.customer-topic-list button {
  appearance: none;
  -webkit-appearance: none;
  display: grid !important;
  grid-template-columns: 19px minmax(0, 1fr) 22px !important;
  width: 100% !important;
  min-height: 48px;
  padding: 8px 7px !important;
  border: 1px solid transparent !important;
  border-radius: 6px !important;
  background: transparent !important;
  color: #9bb4c1 !important;
  box-shadow: none !important;
  text-align: left !important;
}

.customer-topic-list button:hover,
.customer-topic-list button.active {
  border-color: rgba(125, 249, 255, .3) !important;
  background: rgba(125, 249, 255, .1) !important;
  color: #7df9ff !important;
}

.customer-topic-list button strong {
  color: #e2f6fb !important;
  font-size: 11px !important;
}

.customer-topic-list button small {
  color: #7f9ba9 !important;
  font-size: 9px !important;
}

.customer-topic-list button b {
  width: 22px !important;
  height: 22px !important;
  background: rgba(125, 249, 255, .12) !important;
  color: #a2ffd6 !important;
}

.customer-article-list {
  display: grid;
  gap: 5px;
  max-height: 210px;
  overflow: auto;
  padding: 0 10px 12px;
  border-top: 1px solid rgba(125, 249, 255, .1);
}

.customer-article-list button {
  appearance: none;
  -webkit-appearance: none;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 7px;
  min-width: 0;
  width: 100%;
  padding: 8px 7px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: #8fa9b7;
  font-size: 10px;
  line-height: 1.35;
  text-align: left;
}

.customer-article-list button:hover,
.customer-article-list button.active {
  border-color: rgba(162, 255, 214, .22);
  background: rgba(162, 255, 214, .08);
  color: #d7fff3;
}

.customer-article-list button svg {
  width: 14px;
  color: #7df9ff;
}

.customer-article-list button span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-article-list button svg:last-child {
  color: #6b8b9a;
}

.customer-reference-content {
  padding: 15px 16px 18px !important;
}

.customer-reference-content h2 {
  font-size: 16px !important;
}

.customer-reference-content > p,
.customer-reference-content ol,
.customer-reference-source,
.customer-reference-link {
  font-size: 10px !important;
}

.customer-chat-header {
  min-height: 72px;
  padding: 15px 20px !important;
}

.customer-chat-messages {
  min-height: 0 !important;
  padding: 26px 28px 18px !important;
}

.customer-chat-message {
  width: min(100%, 900px);
  max-width: 900px !important;
  margin-bottom: 22px;
}

.customer-message-body {
  max-width: min(78%, 760px) !important;
}

.customer-message-bubble {
  font-size: 13px !important;
  line-height: 1.75 !important;
  white-space: normal;
}

.customer-markdown {
  overflow-wrap: anywhere;
}

.customer-markdown.is-streaming::after {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  margin-left: 4px;
  vertical-align: -0.16em;
  background: #7df9ff;
  content: "";
  animation: customer-caret-blink 1s steps(2, start) infinite;
}

.customer-markdown :deep(p) {
  margin: 0 0 10px;
}

.customer-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.customer-markdown :deep(h1),
.customer-markdown :deep(h2),
.customer-markdown :deep(h3),
.customer-markdown :deep(h4),
.customer-markdown :deep(h5),
.customer-markdown :deep(h6) {
  margin: 14px 0 7px;
  color: #effcff;
  font-weight: 700;
  line-height: 1.35;
}

.customer-markdown :deep(h1:first-child),
.customer-markdown :deep(h2:first-child),
.customer-markdown :deep(h3:first-child),
.customer-markdown :deep(h4:first-child),
.customer-markdown :deep(h5:first-child),
.customer-markdown :deep(h6:first-child) {
  margin-top: 0;
}

.customer-markdown :deep(h1) {
  font-size: 18px;
}

.customer-markdown :deep(h2) {
  font-size: 16px;
}

.customer-markdown :deep(h3) {
  font-size: 14px;
}

.customer-markdown :deep(h4),
.customer-markdown :deep(h5),
.customer-markdown :deep(h6) {
  font-size: 13px;
}

.customer-markdown :deep(ul),
.customer-markdown :deep(ol) {
  margin: 8px 0 11px;
  padding-left: 22px;
  text-align: left;
}

.customer-markdown :deep(li) {
  margin: 4px 0;
  padding-left: 2px;
}

.customer-markdown :deep(li::marker) {
  color: #7df9ff;
}

.customer-markdown :deep(strong) {
  color: #a2ffd6;
  font-weight: 700;
}

.customer-markdown :deep(em) {
  color: #c5e8ef;
}

.customer-markdown :deep(code) {
  padding: 2px 5px;
  border: 1px solid rgba(125, 249, 255, .18);
  border-radius: 4px;
  background: rgba(1, 12, 25, .68);
  color: #b9f7ff;
  font-family: "JetBrains Mono", monospace;
  font-size: .9em;
}

.customer-markdown :deep(pre) {
  max-width: 100%;
  margin: 10px 0 12px;
  padding: 11px 12px;
  overflow-x: auto;
  border: 1px solid rgba(125, 249, 255, .17);
  border-radius: 6px;
  background: rgba(1, 12, 25, .78);
  scrollbar-color: rgba(125, 249, 255, .32) transparent;
}

.customer-markdown :deep(pre code) {
  display: block;
  padding: 0;
  overflow-wrap: normal;
  border: 0;
  background: transparent;
  color: #c9f4f7;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre;
}

.customer-markdown :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 11px;
  border-left: 3px solid #7df9ff;
  background: rgba(125, 249, 255, .06);
  color: #b9d4dc;
}

.customer-markdown :deep(blockquote p:last-child) {
  margin-bottom: 0;
}

.customer-markdown :deep(a) {
  color: #7df9ff;
  text-decoration: underline;
  text-decoration-color: rgba(125, 249, 255, .52);
  text-underline-offset: 2px;
}

.customer-markdown :deep(a:hover) {
  color: #a2ffd6;
}

.customer-markdown :deep(hr) {
  margin: 12px 0;
  border: 0;
  border-top: 1px solid rgba(125, 249, 255, .2);
}

.customer-suggestions {
  flex-wrap: nowrap;
  min-height: 43px;
  padding: 0 20px 11px !important;
}

.customer-suggestions button {
  appearance: none;
  -webkit-appearance: none;
  border-radius: 999px !important;
  background: rgba(125, 249, 255, .06) !important;
  color: #b7d5df !important;
}

.customer-composer {
  margin: 0 20px !important;
  padding: 15px 0 10px !important;
}

.customer-composer textarea {
  min-height: 52px;
  padding: 14px 15px !important;
  border-radius: 8px !important;
  background: rgba(3, 13, 28, .96) !important;
  font-size: 13px !important;
}

.customer-send-button {
  width: 52px;
  height: 52px;
  border-radius: 8px !important;
}

.customer-composer-note {
  padding: 0 20px 17px !important;
  font-size: 10px !important;
}

.customer-related-section {
  flex: 0 0 auto;
}

@media (max-width: 760px) {
  .customer-service-page {
    padding: 24px 16px 42px !important;
  }

  .customer-service-layout {
    grid-template-columns: 1fr !important;
    grid-template-areas:
      "conversation"
      "knowledge" !important;
    min-height: 0;
  }

  .customer-chat-panel {
    height: 620px;
    min-height: 620px !important;
  }

  .customer-service-sidebar {
    display: grid !important;
    grid-template-columns: 1fr;
  }
}
</style>
