<script setup>
import { ref } from 'vue'

defineProps({
  caption: { type: String, default: '' },
  rotateAmplitude: { type: Number, default: 10 },
  scaleOnHover: { type: Number, default: 1.03 },
})

const x = ref(0)
const y = ref(0)

function move(event, rotateAmplitude) {
  const rect = event.currentTarget.getBoundingClientRect()
  const px = (event.clientX - rect.left) / rect.width - .5
  const py = (event.clientY - rect.top) / rect.height - .5
  x.value = px * rotateAmplitude
  y.value = -py * rotateAmplitude
}

function reset() {
  x.value = 0
  y.value = 0
}
</script>

<template>
  <figure
    class="tilted-card"
    :style="{
      '--tilt-x': `${y}deg`,
      '--tilt-y': `${x}deg`,
      '--tilt-scale': scaleOnHover,
    }"
    @mousemove="move($event, rotateAmplitude)"
    @mouseleave="reset"
  >
    <div class="tilted-card-inner">
      <slot />
    </div>
    <figcaption v-if="caption">{{ caption }}</figcaption>
  </figure>
</template>

<style scoped>
.tilted-card {
  position: relative;
  margin: 0;
  perspective: 900px;
}

.tilted-card-inner {
  height: 100%;
  transform: rotateX(var(--tilt-x)) rotateY(var(--tilt-y)) scale(1);
  transform-style: preserve-3d;
  transition: transform .22s ease, filter .22s ease;
}

.tilted-card:hover .tilted-card-inner {
  transform: rotateX(var(--tilt-x)) rotateY(var(--tilt-y)) scale(var(--tilt-scale));
  filter: drop-shadow(0 24px 42px rgba(0, 213, 255, .22));
}

figcaption {
  position: absolute;
  left: 16px;
  top: 14px;
  z-index: 4;
  padding: 6px 11px;
  border: 1px solid rgba(151, 232, 255, .25);
  border-radius: 6px;
  background: rgba(8, 22, 36, .68);
  color: #dff8ff;
  font-size: 11px;
  opacity: 0;
  transform: translateY(-5px);
  pointer-events: none;
  transition: opacity .2s ease, transform .2s ease;
  backdrop-filter: blur(12px);
}

.tilted-card:hover figcaption {
  opacity: 1;
  transform: translateY(0);
}

@media (max-width: 640px) {
  .tilted-card-inner,
  .tilted-card:hover .tilted-card-inner {
    transform: none;
  }

  figcaption {
    display: none;
  }
}
</style>
