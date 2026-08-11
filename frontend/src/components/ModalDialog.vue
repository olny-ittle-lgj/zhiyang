<script setup>
import { X } from 'lucide-vue-next'
const props = defineProps({ title: String, wide: Boolean, closeDisabled: Boolean })
const emit = defineEmits(['close'])
function close() {
  if (!props.closeDisabled) emit('close')
}
</script>
<template>
  <Teleport to="body"><div class="modal-backdrop" @click.self="close"><section class="modal" :class="{ wide }"><header><h2>{{ title }}</h2><button class="icon-button" :disabled="closeDisabled" title="关闭" @click="close"><X /></button></header><slot /></section></div></Teleport>
</template>
