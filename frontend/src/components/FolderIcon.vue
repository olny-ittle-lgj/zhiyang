<script setup>
defineProps({
  color: { type: String, default: '#35d8ff' },
  size: { type: Number, default: 1 },
  items: { type: Array, default: () => [] },
})
</script>

<template>
  <span class="folder-icon-wrap" :style="{ '--folder-color': color, '--folder-scale': size }" aria-hidden="true">
    <span class="folder-icon">
      <span v-for="index in 3" :key="index" class="folder-paper">
        <small v-if="items[index - 1]">{{ items[index - 1] }}</small>
      </span>
      <span class="folder-back"></span>
      <span class="folder-front"></span>
    </span>
  </span>
</template>

<style scoped>
.folder-icon-wrap {
  display: inline-grid;
  place-items: center;
  width: calc(86px * var(--folder-scale));
  height: calc(72px * var(--folder-scale));
}

.folder-icon {
  position: relative;
  width: 86px;
  height: 64px;
  transform: scale(var(--folder-scale));
  transform-origin: center;
  transition: transform .25s ease;
}

.folder-icon-wrap:hover .folder-icon {
  transform: translateY(-7px) scale(var(--folder-scale));
}

.folder-back,
.folder-front,
.folder-paper {
  position: absolute;
  left: 0;
  bottom: 0;
  border-radius: 7px;
}

.folder-back {
  width: 86px;
  height: 52px;
  background: color-mix(in srgb, var(--folder-color) 78%, #06263d 22%);
  box-shadow: 0 0 22px color-mix(in srgb, var(--folder-color) 50%, transparent);
}

.folder-back::before {
  content: "";
  position: absolute;
  left: 0;
  bottom: 48px;
  width: 30px;
  height: 12px;
  border-radius: 7px 7px 0 0;
  background: color-mix(in srgb, var(--folder-color) 70%, #0b2e49 30%);
}

.folder-front {
  z-index: 5;
  width: 86px;
  height: 46px;
  background: linear-gradient(135deg, var(--folder-color), #197aa3);
  transform-origin: bottom;
  transition: transform .28s ease;
}

.folder-paper {
  z-index: 3;
  left: 12px;
  bottom: 10px;
  width: 62px;
  height: 42px;
  background: linear-gradient(180deg, #dff8ff, #7ee8ff);
  box-shadow: 0 0 12px rgba(126, 232, 255, .34);
  transition: transform .28s ease;
}

.folder-paper small {
  display: block;
  padding: 7px;
  color: #0a2436;
  font-size: 8px;
  line-height: 1.1;
}

.folder-paper:nth-child(1) { opacity: .78; }
.folder-paper:nth-child(2) { opacity: .9; width: 68px; left: 9px; }
.folder-paper:nth-child(3) { width: 72px; left: 7px; }

.folder-icon-wrap:hover .folder-front {
  transform: skew(12deg) scaleY(.68);
}

.folder-icon-wrap:hover .folder-paper:nth-child(1) {
  transform: translate(-18px, -24px) rotate(-14deg);
}

.folder-icon-wrap:hover .folder-paper:nth-child(2) {
  transform: translate(16px, -24px) rotate(12deg);
}

.folder-icon-wrap:hover .folder-paper:nth-child(3) {
  transform: translate(0, -36px) rotate(4deg);
}
</style>
