<script setup>
import { computed, ref } from 'vue'
import { ArrowLeft, Eye, EyeOff, LockKeyhole, Mail, UserRound } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { api, setActiveTeamId, setPortalMode, setToken } from '../api'

const router = useRouter()
const route = useRoute()
const mode = ref('login')
const username = ref('')
const nickname = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

const isRegister = computed(() => mode.value === 'register')
const isTeamPortal = computed(() => route.query.space === 'team')
const portalName = computed(() => isTeamPortal.value ? '团队端' : '个人端')
const canSubmit = computed(() => {
  if (!username.value || !password.value) return false
  return !isRegister.value || Boolean(nickname.value && confirmPassword.value)
})

function setMode(nextMode) {
  mode.value = nextMode
  error.value = ''
}

async function submit() {
  error.value = ''
  if (isRegister.value && password.value.length < 8) {
    error.value = '密码至少需要 8 位字符'
    return
  }
  if (isRegister.value && password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    const data = await api(isRegister.value ? '/auth/register' : '/auth/login', {
      method: 'POST',
      body: isRegister.value
        ? { username: username.value, password: password.value, nickname: nickname.value }
        : { username: username.value, password: password.value },
    })
    setPortalMode(isTeamPortal.value ? 'team' : 'personal')
    setToken(data.access_token, data.refresh_token)
    if (isTeamPortal.value) router.push('/teams')
    else {
      setActiveTeamId('')
      router.push('/dashboard')
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="public-page auth-page">
    <button class="auth-back" type="button" @click="router.push('/login')">
      <ArrowLeft :size="20" /> 其他登录方式
    </button>

    <main class="auth-main">
      <form class="auth-card" @submit.prevent="submit">
        <h1>{{ isRegister ? `创建${portalName}账户` : `进入${portalName}` }}</h1>
        <p class="auth-intro">{{ isTeamPortal ? '登录后进入独立团队控制台，管理团队协作闭环' : '登录后进入个人知识空间，继续个人知识演化' }}</p>

        <div class="auth-tabs" role="tablist" aria-label="账号登录或注册">
          <button type="button" role="tab" :aria-selected="!isRegister" :class="{ active: !isRegister }" @click="setMode('login')">账号登录</button>
          <button type="button" role="tab" :aria-selected="isRegister" :class="{ active: isRegister }" @click="setMode('register')">账号注册</button>
        </div>

        <label v-if="isRegister">昵称
          <div class="input-wrap"><UserRound :size="18" /><input v-model.trim="nickname" autocomplete="nickname" placeholder="输入您的昵称" /></div>
        </label>
        <label>账号 / 邮箱
          <div class="input-wrap"><Mail :size="18" /><input v-model.trim="username" autocomplete="username" placeholder="name@example.com" /></div>
        </label>
        <label>密码
          <div class="input-wrap">
            <LockKeyhole :size="18" />
            <input v-model="password" :type="showPassword ? 'text' : 'password'" :autocomplete="isRegister ? 'new-password' : 'current-password'" :placeholder="isRegister ? '至少 8 位字符' : '输入密码'" />
            <button class="icon-button" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
              <component :is="showPassword ? EyeOff : Eye" :size="18" />
            </button>
          </div>
        </label>
        <label v-if="isRegister">确认密码
          <div class="input-wrap"><LockKeyhole :size="18" /><input v-model="confirmPassword" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="再次输入密码" /></div>
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button primary auth-submit" :disabled="loading || !canSubmit">
          {{ loading ? '正在处理...' : isRegister ? '注册并进入' : '登录' }}
        </button>
        <p class="auth-switch">
          {{ isRegister ? '已有账号？' : '还没有账号？' }}
          <button type="button" class="link-button" @click="setMode(isRegister ? 'login' : 'register')">{{ isRegister ? '直接登录' : '立即注册' }}</button>
        </p>
      </form>
    </main>

  </div>
</template>
