<script setup>defineProps({ message: String, type: { type: String, default: 'success' } })</script>
<template><Transition name="toast"><div v-if="message" class="toast-message" :class="type">{{ message }}</div></Transition></template>
