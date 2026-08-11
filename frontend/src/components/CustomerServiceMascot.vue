<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const mascotRef = ref(null)
const dragging = ref(false)
const moved = ref(false)
const position = ref(null)
const dragState = ref(null)

const positionStyle = computed(() => {
  if (!position.value) return {}
  return {
    top: `${position.value.top}px`,
    left: `${position.value.left}px`,
    right: 'auto',
    bottom: 'auto',
  }
})

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function startDrag(event) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const element = mascotRef.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  dragState.value = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startLeft: rect.left,
    startTop: rect.top,
  }
  moved.value = false
  dragging.value = true
  element.setPointerCapture?.(event.pointerId)
  event.preventDefault()
}

function moveDrag(event) {
  if (!dragging.value || !dragState.value) return
  const dx = event.clientX - dragState.value.startX
  const dy = event.clientY - dragState.value.startY
  if (Math.abs(dx) > 5 || Math.abs(dy) > 5) moved.value = true
  const element = mascotRef.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  position.value = {
    left: clamp(dragState.value.startLeft + dx, 10, window.innerWidth - rect.width - 10),
    top: clamp(dragState.value.startTop + dy, 66, window.innerHeight - rect.height - 10),
  }
}

function endDrag(event) {
  if (!dragging.value) return
  const wasMoved = moved.value
  dragging.value = false
  dragState.value = null
  mascotRef.value?.releasePointerCapture?.(event.pointerId)
  if (!wasMoved) router.push('/customer-service')
}

function openService(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    router.push('/customer-service')
  }
}

function clearDrag() {
  dragging.value = false
  dragState.value = null
}

onBeforeUnmount(clearDrag)
</script>

<template>
  <div
    ref="mascotRef"
    class="customer-service-mascot"
    :class="{ 'is-dragging': dragging }"
    :style="positionStyle"
    role="button"
    tabindex="0"
    aria-label="打开客服中心"
    title="点击打开客服中心，按住可拖动"
    @pointerdown="startDrag"
    @pointermove="moveDrag"
    @pointerup="endDrag"
    @pointercancel="clearDrag"
    @keydown="openService"
  >
    <span class="mascot-bubble">
      <strong>{{ dragging ? '移动中' : '小知客服' }}</strong>
      <small>{{ dragging ? '放到顺手的位置' : '点击咨询项目操作' }}</small>
    </span>
    <span class="mascot-spark spark-one"></span>
    <span class="mascot-spark spark-two"></span>
    <span class="mascot-spark spark-three"></span>
    <span class="mascot-shadow"></span>
    <span class="mascot-figure" aria-hidden="true">
      <span class="mascot-hair-back"></span>
      <span class="mascot-head">
        <span class="mascot-hair"></span>
        <span class="mascot-ear ear-left"></span>
        <span class="mascot-ear ear-right"></span>
        <span class="mascot-eye eye-left"></span>
        <span class="mascot-eye eye-right"></span>
        <span class="mascot-mouth"></span>
        <span class="mascot-cheek cheek-left"></span>
        <span class="mascot-cheek cheek-right"></span>
      </span>
      <span class="mascot-neck"></span>
      <span class="mascot-body">
        <span class="mascot-collar"></span>
        <span class="mascot-screen">?</span>
      </span>
      <span class="mascot-arm arm-left"></span>
      <span class="mascot-arm arm-right"></span>
      <span class="mascot-hand hand-left"></span>
      <span class="mascot-hand hand-right"></span>
    </span>
    <span class="mascot-status"><i></i> 在线</span>
  </div>
</template>

<style scoped>
.customer-service-mascot {
  position: fixed;
  right: 24px;
  bottom: 84px;
  z-index: 60;
  width: 96px;
  height: 138px;
  cursor: grab;
  user-select: none;
  touch-action: none;
  outline: none;
}

.customer-service-mascot:active {
  cursor: grabbing;
}

.customer-service-mascot:focus-visible {
  border-radius: 24px;
  box-shadow: 0 0 0 3px rgba(125, 249, 255, .35);
}

.mascot-bubble {
  position: absolute;
  top: -7px;
  right: -30px;
  z-index: 5;
  display: grid;
  gap: 3px;
  min-width: 112px;
  padding: 8px 10px;
  border: 1px solid rgba(125, 249, 255, .35);
  border-radius: 10px 10px 3px 10px;
  background: rgba(5, 19, 36, .94);
  box-shadow: 0 10px 24px rgba(0, 0, 0, .26), 0 0 18px rgba(125, 249, 255, .12);
  color: #ecfbff;
  opacity: 0;
  pointer-events: none;
  transform: translateY(5px);
  transition: opacity .2s ease, transform .2s ease;
}

.customer-service-mascot:hover .mascot-bubble,
.customer-service-mascot:focus-visible .mascot-bubble,
.customer-service-mascot.is-dragging .mascot-bubble {
  opacity: 1;
  transform: translateY(0);
}

.mascot-bubble strong {
  font-size: 11px;
  font-weight: 700;
}

.mascot-bubble small {
  color: #9db7c9;
  font-size: 9px;
  white-space: nowrap;
}

.mascot-figure {
  position: absolute;
  right: 12px;
  bottom: 18px;
  width: 68px;
  height: 98px;
  display: block;
  filter: drop-shadow(0 9px 10px rgba(0, 0, 0, .28));
  transform-origin: 50% 90%;
  animation: mascot-float 3.4s ease-in-out infinite;
}

.customer-service-mascot.is-dragging .mascot-figure {
  animation: mascot-drag .5s ease-in-out infinite;
}

.mascot-shadow {
  position: absolute;
  right: 13px;
  bottom: 12px;
  width: 67px;
  height: 10px;
  border-radius: 50%;
  background: rgba(0, 0, 0, .35);
  filter: blur(4px);
  transition: transform .2s ease, opacity .2s ease;
}

.customer-service-mascot.is-dragging .mascot-shadow {
  opacity: .55;
  transform: scale(.78);
}

.mascot-hair-back {
  position: absolute;
  top: 5px;
  left: 8px;
  width: 52px;
  height: 53px;
  border-radius: 54% 50% 42% 46%;
  background: #182f58;
  box-shadow: 7px 7px 0 #0d1b38, -4px 7px 0 #244476;
}

.mascot-head {
  position: absolute;
  top: 8px;
  left: 14px;
  z-index: 2;
  width: 43px;
  height: 48px;
  border: 2px solid #0f2340;
  border-radius: 48% 48% 44% 45%;
  background: #ffd8c4;
  box-shadow: inset -5px -3px 0 rgba(228, 146, 132, .15);
}

.mascot-hair {
  position: absolute;
  top: -5px;
  left: -2px;
  width: 45px;
  height: 22px;
  border-radius: 52% 58% 25% 20%;
  background: #54dbe5;
  transform: rotate(-3deg);
  box-shadow: 10px 12px 0 -6px #3198bb, -5px 11px 0 -5px #3198bb;
}

.mascot-ear {
  position: absolute;
  top: 21px;
  width: 6px;
  height: 10px;
  border: 1px solid #e1a697;
  border-radius: 50%;
  background: #ffd8c4;
}

.ear-left {
  left: -6px;
}

.ear-right {
  right: -6px;
}

.mascot-eye {
  position: absolute;
  top: 27px;
  width: 5px;
  height: 7px;
  border-radius: 50%;
  background: #132747;
  animation: mascot-blink 5s ease-in-out infinite;
}

.eye-left {
  left: 12px;
}

.eye-right {
  right: 12px;
  animation-delay: 1.2s;
}

.mascot-mouth {
  position: absolute;
  left: 19px;
  top: 37px;
  width: 7px;
  height: 4px;
  border-bottom: 1px solid #bc6373;
  border-radius: 0 0 50% 50%;
}

.mascot-cheek {
  position: absolute;
  top: 35px;
  width: 7px;
  height: 3px;
  border-radius: 50%;
  background: rgba(241, 122, 137, .42);
}

.cheek-left {
  left: 5px;
}

.cheek-right {
  right: 5px;
}

.mascot-neck {
  position: absolute;
  top: 52px;
  left: 29px;
  z-index: 1;
  width: 11px;
  height: 9px;
  background: #ffc1ae;
}

.mascot-body {
  position: absolute;
  top: 57px;
  left: 8px;
  z-index: 2;
  width: 54px;
  height: 42px;
  border: 2px solid #0f2340;
  border-radius: 20px 20px 13px 13px;
  background: linear-gradient(145deg, #6ef2dc, #2487ba 70%);
  box-shadow: inset -6px -5px 0 rgba(11, 49, 91, .18);
}

.mascot-collar {
  position: absolute;
  left: 18px;
  top: -2px;
  width: 17px;
  height: 11px;
  border: 2px solid #0f2340;
  border-top: 0;
  border-radius: 0 0 12px 12px;
  background: #f7c55d;
}

.mascot-screen {
  position: absolute;
  left: 20px;
  top: 17px;
  display: grid;
  place-items: center;
  width: 15px;
  height: 12px;
  border: 1px solid rgba(239, 255, 255, .75);
  border-radius: 4px;
  background: rgba(8, 44, 70, .52);
  color: #eaffff;
  font-family: "JetBrains Mono", monospace;
  font-size: 9px;
  font-weight: 700;
}

.mascot-arm {
  position: absolute;
  top: 65px;
  z-index: 1;
  width: 11px;
  height: 31px;
  border: 2px solid #0f2340;
  border-radius: 10px;
  background: #42c4d5;
  transform-origin: 50% 5px;
}

.arm-left {
  left: 1px;
  transform: rotate(23deg);
}

.arm-right {
  right: 0;
  transform: rotate(-25deg);
}

.mascot-hand {
  position: absolute;
  top: 91px;
  z-index: 3;
  width: 12px;
  height: 12px;
  border: 2px solid #0f2340;
  border-radius: 50%;
  background: #ffd8c4;
}

.hand-left {
  left: -2px;
}

.hand-right {
  right: -2px;
}

.customer-service-mascot.is-dragging .arm-left {
  animation: mascot-wave-left .45s ease-in-out infinite alternate;
}

.customer-service-mascot.is-dragging .arm-right {
  animation: mascot-wave-right .45s ease-in-out infinite alternate;
}

.mascot-spark {
  position: absolute;
  z-index: 4;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #a2ffd6;
  box-shadow: 0 0 9px #a2ffd6;
  animation: mascot-spark 2.6s ease-in-out infinite;
}

.spark-one {
  top: 45px;
  left: 7px;
}

.spark-two {
  top: 78px;
  right: 1px;
  width: 4px;
  height: 4px;
  animation-delay: .9s;
}

.spark-three {
  top: 22px;
  right: 12px;
  width: 3px;
  height: 3px;
  animation-delay: 1.7s;
}

.mascot-status {
  position: absolute;
  right: 8px;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border: 1px solid rgba(162, 255, 214, .28);
  border-radius: 20px;
  background: rgba(6, 28, 43, .92);
  color: #a2ffd6;
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
}

.mascot-status i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #a2ffd6;
  box-shadow: 0 0 7px #a2ffd6;
}

@keyframes mascot-float {
  0%, 100% { transform: translateY(0) rotate(-2deg); }
  50% { transform: translateY(-6px) rotate(2deg); }
}

@keyframes mascot-drag {
  0%, 100% { transform: rotate(-6deg) translateY(0); }
  50% { transform: rotate(7deg) translateY(-5px); }
}

@keyframes mascot-blink {
  0%, 43%, 48%, 100% { transform: scaleY(1); }
  45%, 46% { transform: scaleY(.12); }
}

@keyframes mascot-wave-left {
  from { transform: rotate(23deg); }
  to { transform: rotate(-20deg); }
}

@keyframes mascot-wave-right {
  from { transform: rotate(-25deg); }
  to { transform: rotate(18deg); }
}

@keyframes mascot-spark {
  0%, 100% { opacity: .35; transform: scale(.7); }
  50% { opacity: 1; transform: scale(1.35); }
}

@media (max-width: 640px) {
  .customer-service-mascot {
    right: 12px;
    bottom: 72px;
    transform: scale(.86);
    transform-origin: bottom right;
  }

  .customer-service-mascot.is-dragging {
    transform: scale(.92);
  }
}

@media (prefers-reduced-motion: reduce) {
  .mascot-figure,
  .mascot-eye,
  .mascot-spark,
  .customer-service-mascot.is-dragging .arm-left,
  .customer-service-mascot.is-dragging .arm-right {
    animation: none;
  }
}
</style>
