<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from 'lucide-vue-next'

const router = useRouter()
const heroFrame = ref(null)
const displayed = ref('')
const typingDone = ref(false)
const isDesktop = ref(typeof window === 'undefined' ? true : window.innerWidth >= 1024)

const headline = '让知识\n持续进化'
const description = '从素材采集、智能问答到知识进化与游戏化学习，\n知衍把零散信息沉淀为可理解、可复习、可持续成长的知识体系。'
const frameCount = 97
const frameRate = 24
const framePaths = Array.from({ length: frameCount }, (_, index) => `/media/hero-frames-dark-v3/frame-${String(index).padStart(3, '0')}.webp`)

let targetFrame = 0
let previousX = null
let typingDelay = null
let typingTimer = null
let scrubFrame = null
let mobilePlaybackFrame = null
let mobileFrame = 0
let mobileLastFrameAt = 0
let preloadTimer = null
let pointerEventName = 'pointermove'
const frameImages = []

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function handlePointerMove(event) {
  if (!isDesktop.value) return

  const samples = typeof event.getCoalescedEvents === 'function' ? event.getCoalescedEvents() : []
  const sample = samples.length > 0 ? samples[samples.length - 1] : event
  if (previousX === null) {
    previousX = sample.clientX
    return
  }

  const delta = sample.clientX - previousX
  previousX = sample.clientX
  targetFrame = clamp(
    targetFrame + Math.round((delta / Math.max(window.innerWidth, 1)) * 0.8 * frameCount),
    0,
    frameCount - 1,
  )
  queueScrub()
}

function queueScrub() {
  if (scrubFrame !== null) return
  scrubFrame = window.requestAnimationFrame(commitLatestFrame)
}

function commitLatestFrame() {
  scrubFrame = null
  showFrame(targetFrame)
}

function preloadFrame(index) {
  if (frameImages[index]) return frameImages[index]
  const image = new Image()
  image.decoding = 'async'
  image.loading = 'eager'
  image.src = framePaths[index]
  frameImages[index] = image
  return image
}

function preloadFrames() {
  framePaths.forEach((_, index) => preloadFrame(index))
}

function showFrame(index) {
  const image = preloadFrame(clamp(Math.round(index), 0, frameCount - 1))
  const render = () => {
    if (heroFrame.value && image.naturalWidth > 0) heroFrame.value.src = image.src
  }

  if (image.complete && image.naturalWidth > 0) render()
  else image.addEventListener('load', render, { once: true })
}

function animateMobile(timestamp) {
  if (isDesktop.value) {
    mobilePlaybackFrame = null
    return
  }

  if (timestamp - mobileLastFrameAt >= 1000 / frameRate) {
    mobileFrame = (mobileFrame + 1) % frameCount
    showFrame(mobileFrame)
    mobileLastFrameAt = timestamp
  }
  mobilePlaybackFrame = window.requestAnimationFrame(animateMobile)
}

function startMobilePlayback() {
  if (mobilePlaybackFrame === null) mobilePlaybackFrame = window.requestAnimationFrame(animateMobile)
}

function stopMobilePlayback() {
  if (mobilePlaybackFrame !== null) {
    window.cancelAnimationFrame(mobilePlaybackFrame)
    mobilePlaybackFrame = null
  }
}

function syncViewport() {
  const nextIsDesktop = window.innerWidth >= 1024
  if (nextIsDesktop === isDesktop.value) return
  isDesktop.value = nextIsDesktop
  previousX = null
  targetFrame = 0
  mobileFrame = 0
  showFrame(0)
  nextTick(() => {
    if (isDesktop.value) stopMobilePlayback()
    else startMobilePlayback()
  })
}

function startTyping() {
  let index = 0
  typingDelay = window.setTimeout(() => {
    typingTimer = window.setInterval(() => {
      index += 1
      displayed.value = headline.slice(0, index)
      if (index >= headline.length) {
        window.clearInterval(typingTimer)
        typingDone.value = true
      }
    }, 38)
  }, 600)
}

onMounted(() => {
  startTyping()
  showFrame(0)
  preloadTimer = window.setTimeout(preloadFrames, 0)
  pointerEventName = 'onpointerrawupdate' in window ? 'pointerrawupdate' : 'pointermove'
  window.addEventListener(pointerEventName, handlePointerMove, { passive: true })
  window.addEventListener('resize', syncViewport, { passive: true })
  if (!isDesktop.value) startMobilePlayback()
})

onBeforeUnmount(() => {
  window.removeEventListener(pointerEventName, handlePointerMove)
  window.removeEventListener('resize', syncViewport)
  if (scrubFrame !== null) window.cancelAnimationFrame(scrubFrame)
  stopMobilePlayback()
  if (preloadTimer !== null) window.clearTimeout(preloadTimer)
  window.clearTimeout(typingDelay)
  window.clearInterval(typingTimer)
})
</script>

<template>
  <div class="mainframe-page">
    <div class="video-stage" aria-hidden="true">
      <img
        ref="heroFrame"
        class="hero-video hero-frame"
        :src="framePaths[0]"
        alt=""
        draggable="false"
      />
    </div>
    <header class="site-header">
      <a class="brand" href="#spade-hero" aria-label="知衍首页">
        <span>知衍</span>
        <small>AI 知识进化工坊</small>
      </a>
    </header>

    <div class="content-layer">
      <main id="spade-hero" class="hero-main">
        <div class="hero-copy">
          <p class="hero-kicker intro-block">AI 知识进化工坊 / V3.7</p>
          <div class="intro-block intro-headline">
            <h1>{{ displayed }}<span v-if="!typingDone" class="typing-cursor" aria-hidden="true"></span></h1>
          </div>

          <div class="intro-block intro-description">
            <p class="description">{{ description }}</p>
          </div>

          <div class="intro-block intro-cta">
            <button class="start-button" type="button" @click="router.push('/login')">
              <span>开始使用</span>
              <ArrowRight aria-hidden="true" />
            </button>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.mainframe-page {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100svh;
  overflow-x: hidden;
  background: var(--cover-gradient, var(--cover-bg, #091e30));
  color: var(--page-ink, #dff8ff);
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  -webkit-font-smoothing: antialiased;
  isolation: isolate;
}

.mainframe-page::selection,
.mainframe-page *::selection {
  background: rgba(125, 249, 255, .24);
  color: #eefbff;
}

.video-stage {
  position: relative;
  order: 2;
  width: 100%;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  pointer-events: none;
  background: var(--cover-gradient, var(--cover-bg, #091e30));
}

.hero-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: right center;
  backface-visibility: hidden;
  transform: translateZ(0);
  will-change: contents;
}

.site-header {
  position: fixed;
  z-index: 20;
  inset: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: transparent;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #eefbff;
  font-size: 21px;
  font-weight: 500;
  line-height: 1;
  text-decoration: none;
  user-select: none;
}

.brand small {
  margin-top: 2px;
  color: #8fcaff;
  font-size: 11px;
  font-weight: 400;
  white-space: nowrap;
}

.content-layer {
  position: relative;
  z-index: 10;
  order: 1;
  display: flex;
  width: 100%;
  flex-direction: column;
  flex: 1;
  padding-bottom: 32px;
  background: var(--cover-gradient, var(--cover-bg, #091e30));
}

.hero-main {
  display: flex;
  width: 100%;
  max-width: 1280px;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  margin: 0 auto;
  padding: 112px 24px 48px;
}

.hero-copy {
  width: 100%;
}

.intro-block {
  opacity: 0;
  animation: drop-in 600ms ease forwards;
}

.intro-description {
  animation-delay: 100ms;
}

.intro-cta {
  animation-delay: 180ms;
}

.hero-kicker {
  margin: 0 0 22px;
  color: #7df9ff;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

h1 {
  width: 100%;
  min-height: 2.16em;
  margin: 0 0 32px;
  color: #eefbff;
  font-size: 48px;
  font-weight: 400;
  line-height: 1.08;
  white-space: pre-wrap;
  user-select: none;
}

.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 1.1em;
  margin-left: 2px;
  background: #7df9ff;
  vertical-align: middle;
  animation: blink 1s step-end infinite;
}

.description {
  max-width: 672px;
  margin: 0 0 36px;
  color: #aac4d3;
  font-size: 18px;
  font-weight: 400;
  line-height: 1.625;
  white-space: pre-line;
}

.start-button {
  display: inline-flex;
  min-height: 52px;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px 20px 12px 22px;
  border: 1px solid #7df9ff;
  border-radius: 2px;
  background: #7df9ff;
  color: #06101f;
  font: inherit;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: background 180ms ease, color 180ms ease, transform 180ms ease;
}

.start-button:hover {
  background: #a2ffd6;
  border-color: #a2ffd6;
  transform: translateY(-1px);
}

.start-button svg {
  width: 17px;
  height: 17px;
  transform: translateX(3px);
  transition: transform 180ms ease;
}

.start-button:focus-visible,
a:focus-visible {
  outline: 2px solid #7df9ff;
  outline-offset: 4px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

@keyframes drop-in {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (min-width: 640px) {
  .site-header {
    padding: 20px 32px;
  }

  .brand {
    font-size: 26px;
  }

  .brand small {
    font-size: 12px;
  }
}

@media (min-width: 768px) {
  .video-stage {
    aspect-ratio: 16 / 9;
  }

  h1 {
    font-size: 60px;
  }

  .description {
    font-size: 20px;
  }
}

@media (min-width: 1024px) {
  .mainframe-page {
    display: block;
    min-height: 100svh;
  }

  .video-stage {
    position: absolute;
    z-index: 0;
    inset: 0;
    width: 100%;
    height: 100%;
    aspect-ratio: auto;
    background: transparent;
  }

  .hero-video {
    object-position: right bottom;
  }

  .content-layer {
    min-height: 100svh;
    padding-bottom: 0;
    background: transparent;
  }

  .hero-main {
    min-height: 100svh;
    padding: 96px 24px 48px;
  }

  .hero-copy {
    max-width: 720px;
  }

  h1 {
    font-size: 76px;
  }
}

@media (max-height: 820px) and (min-width: 1024px) {
  .hero-main {
    justify-content: flex-start;
    padding-top: 92px;
  }

  h1 {
    margin-bottom: 20px;
    font-size: 62px;
  }

  .description {
    margin-bottom: 32px;
    font-size: 17px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .intro-block,
  .typing-cursor {
    animation: none;
    opacity: 1;
  }

  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
