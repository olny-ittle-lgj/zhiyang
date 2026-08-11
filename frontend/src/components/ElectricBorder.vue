<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  color: { type: String, default: '#5227FF' },
  speed: { type: Number, default: 1 },
  chaos: { type: Number, default: 0.12 },
  thickness: { type: Number, default: 2 },
  borderRadius: { type: Number, default: 24 },
})

const canvasRef = ref(null)
const containerRef = ref(null)
let animationFrame = 0
let time = 0
let lastFrameTime = 0
let resizeObserver = null
let canvasSize = { width: 0, height: 0 }
let lastDpr = 1

const rootStyle = computed(() => ({
  '--electric-border-color': props.color,
  '--electric-thickness': `${props.thickness}px`,
  borderRadius: `${props.borderRadius}px`,
}))

function random(value) {
  return (Math.sin(value * 12.9898) * 43758.5453) % 1
}

function noise2D(x, y) {
  const i = Math.floor(x)
  const j = Math.floor(y)
  const fx = x - i
  const fy = y - j
  const a = random(i + j * 57)
  const b = random(i + 1 + j * 57)
  const c = random(i + (j + 1) * 57)
  const d = random(i + 1 + (j + 1) * 57)
  const ux = fx * fx * (3 - 2 * fx)
  const uy = fy * fy * (3 - 2 * fy)
  return a * (1 - ux) * (1 - uy) + b * ux * (1 - uy) + c * (1 - ux) * uy + d * ux * uy
}

function octavedNoise(x, octaves, lacunarity, gain, baseAmplitude, baseFrequency, seed, baseFlatness) {
  let y = 0
  let amplitude = baseAmplitude
  let frequency = baseFrequency
  for (let index = 0; index < octaves; index += 1) {
    let octaveAmplitude = amplitude
    if (index === 0) octaveAmplitude *= baseFlatness
    y += octaveAmplitude * noise2D(frequency * x + seed * 100, time * frequency * 0.3)
    frequency *= lacunarity
    amplitude *= gain
  }
  return y
}

function cornerPoint(centerX, centerY, radius, startAngle, arcLength, progress) {
  const angle = startAngle + progress * arcLength
  return {
    x: centerX + radius * Math.cos(angle),
    y: centerY + radius * Math.sin(angle),
  }
}

function roundedRectPoint(t, left, top, width, height, radius) {
  const straightWidth = width - 2 * radius
  const straightHeight = height - 2 * radius
  const cornerArc = Math.PI * radius / 2
  const totalPerimeter = 2 * straightWidth + 2 * straightHeight + 4 * cornerArc
  const distance = t * totalPerimeter
  let accumulated = 0

  if (distance <= accumulated + straightWidth) {
    const progress = (distance - accumulated) / straightWidth
    return { x: left + radius + progress * straightWidth, y: top }
  }
  accumulated += straightWidth

  if (distance <= accumulated + cornerArc) {
    return cornerPoint(left + width - radius, top + radius, radius, -Math.PI / 2, Math.PI / 2, (distance - accumulated) / cornerArc)
  }
  accumulated += cornerArc

  if (distance <= accumulated + straightHeight) {
    const progress = (distance - accumulated) / straightHeight
    return { x: left + width, y: top + radius + progress * straightHeight }
  }
  accumulated += straightHeight

  if (distance <= accumulated + cornerArc) {
    return cornerPoint(left + width - radius, top + height - radius, radius, 0, Math.PI / 2, (distance - accumulated) / cornerArc)
  }
  accumulated += cornerArc

  if (distance <= accumulated + straightWidth) {
    const progress = (distance - accumulated) / straightWidth
    return { x: left + width - radius - progress * straightWidth, y: top + height }
  }
  accumulated += straightWidth

  if (distance <= accumulated + cornerArc) {
    return cornerPoint(left + radius, top + height - radius, radius, Math.PI / 2, Math.PI / 2, (distance - accumulated) / cornerArc)
  }
  accumulated += cornerArc

  if (distance <= accumulated + straightHeight) {
    const progress = (distance - accumulated) / straightHeight
    return { x: left, y: top + height - radius - progress * straightHeight }
  }
  accumulated += straightHeight

  return cornerPoint(left + radius, top + radius, radius, Math.PI, Math.PI / 2, (distance - accumulated) / cornerArc)
}

function updateSize() {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return canvasSize
  const context = canvas.getContext('2d')
  const rect = container.getBoundingClientRect()
  const borderOffset = 60
  const width = rect.width + borderOffset * 2
  const height = rect.height + borderOffset * 2
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = width * dpr
  canvas.height = height * dpr
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  context?.setTransform(dpr, 0, 0, dpr, 0, 0)
  canvasSize = { width, height }
  lastDpr = dpr
  return canvasSize
}

function draw(currentTime) {
  const canvas = canvasRef.value
  const context = canvas?.getContext('2d')
  if (!canvas || !context) return

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  if (dpr !== lastDpr) updateSize()

  const deltaTime = (currentTime - lastFrameTime) / 1000
  time += deltaTime * props.speed
  lastFrameTime = currentTime

  context.setTransform(1, 0, 0, 1, 0, 0)
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.strokeStyle = props.color
  context.lineWidth = Math.max(1, props.thickness)
  context.lineCap = 'round'
  context.lineJoin = 'round'

  const borderOffset = 60
  const left = borderOffset
  const top = borderOffset
  const borderWidth = canvasSize.width - 2 * borderOffset
  const borderHeight = canvasSize.height - 2 * borderOffset
  const radius = Math.min(props.borderRadius, Math.min(borderWidth, borderHeight) / 2)
  const approximatePerimeter = 2 * (borderWidth + borderHeight) + 2 * Math.PI * radius
  const sampleCount = Math.max(80, Math.floor(approximatePerimeter / 2))
  const displacement = 60

  context.beginPath()
  for (let index = 0; index <= sampleCount; index += 1) {
    const progress = index / sampleCount
    const point = roundedRectPoint(progress, left, top, borderWidth, borderHeight, radius)
    const xNoise = octavedNoise(progress * 8, 10, 1.6, 0.7, props.chaos, 10, 0, 0)
    const yNoise = octavedNoise(progress * 8, 10, 1.6, 0.7, props.chaos, 10, 1, 0)
    const x = point.x + xNoise * displacement
    const y = point.y + yNoise * displacement
    if (index === 0) context.moveTo(x, y)
    else context.lineTo(x, y)
  }
  context.closePath()
  context.stroke()
  animationFrame = window.requestAnimationFrame(draw)
}

function start() {
  stop()
  nextTick(() => {
    updateSize()
    lastFrameTime = performance.now()
    animationFrame = window.requestAnimationFrame(draw)
  })
}

function stop() {
  if (animationFrame) window.cancelAnimationFrame(animationFrame)
  animationFrame = 0
}

onMounted(() => {
  resizeObserver = new ResizeObserver(updateSize)
  if (containerRef.value) resizeObserver.observe(containerRef.value)
  start()
})

onBeforeUnmount(() => {
  stop()
  resizeObserver?.disconnect()
})

watch(() => [props.color, props.speed, props.chaos, props.thickness, props.borderRadius], start)
</script>

<template>
  <div ref="containerRef" class="electric-border" :style="rootStyle">
    <div class="eb-canvas-container">
      <canvas ref="canvasRef" class="eb-canvas"></canvas>
    </div>
    <div class="eb-layers">
      <div class="eb-glow-1"></div>
      <div class="eb-glow-2"></div>
      <div class="eb-background-glow"></div>
    </div>
    <div class="eb-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.electric-border {
  position: relative;
  overflow: visible;
  isolation: isolate;
}

.eb-canvas-container {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 2;
  pointer-events: none;
  transform: translate(-50%, -50%);
}

.eb-canvas {
  display: block;
}

.eb-content {
  position: relative;
  z-index: 1;
  height: 100%;
  border-radius: inherit;
}

.eb-layers {
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: inherit;
  pointer-events: none;
}

.eb-glow-1,
.eb-glow-2,
.eb-background-glow {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-sizing: border-box;
}

.eb-glow-1 {
  border: var(--electric-thickness) solid color-mix(in srgb, var(--electric-border-color) 62%, transparent);
  filter: blur(1px);
}

.eb-glow-2 {
  border: var(--electric-thickness) solid var(--electric-border-color);
  filter: blur(4px);
  opacity: .8;
}

.eb-background-glow {
  z-index: -1;
  background: linear-gradient(-30deg, var(--electric-border-color), transparent, var(--electric-border-color));
  opacity: .26;
  filter: blur(32px);
  transform: scale(1.08);
}
</style>
