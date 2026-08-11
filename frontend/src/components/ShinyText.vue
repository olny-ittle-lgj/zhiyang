<script setup>
defineProps({
  text: { type: String, required: true },
  speed: { type: Number, default: 2.2 },
  delay: { type: Number, default: 0 },
  color: { type: String, default: '#8fb4ce' },
  shineColor: { type: String, default: '#ecfeff' },
  spread: { type: Number, default: 120 },
  direction: { type: String, default: 'left' },
  pauseOnHover: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
</script>

<template>
  <span
    class="shiny-text"
    :class="{ paused: pauseOnHover, disabled }"
    :style="{
      '--shiny-speed': `${speed}s`,
      '--shiny-delay': `${delay}s`,
      '--shiny-color': color,
      '--shiny-shine': shineColor,
      '--shiny-spread': `${spread}deg`,
      '--shiny-direction': direction === 'right' ? 'reverse' : 'normal',
    }"
  >{{ text }}</span>
</template>

<style scoped>
.shiny-text {
  display: inline-block;
  color: var(--shiny-color);
  background-image: linear-gradient(
    var(--shiny-spread),
    var(--shiny-color) 0%,
    var(--shiny-color) 34%,
    var(--shiny-shine) 50%,
    var(--shiny-color) 66%,
    var(--shiny-color) 100%
  );
  background-size: 220% auto;
  background-position: 150% center;
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shiny-sweep var(--shiny-speed) linear var(--shiny-delay) infinite;
  animation-direction: var(--shiny-direction);
}

.shiny-text.paused:hover,
.shiny-text.disabled {
  animation-play-state: paused;
}

@keyframes shiny-sweep {
  from { background-position: 150% center; }
  to { background-position: -60% center; }
}
</style>
