<script setup>
import { onUnmounted, ref } from 'vue'
import { ArrowLeft, ShieldCheck, Smartphone } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { api, setActiveTeamId, setPortalMode, setToken } from '../api'

const router = useRouter()
const route = useRoute()
const step = ref('phone')
const phone = ref('')
const code = ref('')
const loading = ref(false)
const countdown = ref(0)
const demoCode = ref('')
const notice = ref('')
const error = ref('')
let timer = null
const isTeamPortal = route.query.space === 'team'

function startCountdown() {
  countdown.value = 60
  clearInterval(timer)
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

async function sendCode() {
  if (!/^1\d{10}$/.test(phone.value)) {
    error.value = '请输入正确的 11 位手机号码'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await api('/auth/phone/code', { method: 'POST', body: { phone: phone.value } })
    demoCode.value = data.demo_code || ''
    notice.value = data.message || '验证码已发送'
    step.value = 'code'
    startCountdown()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function verify() {
  if (!/^\d{4,6}$/.test(code.value)) {
    error.value = '请输入正确的验证码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await api('/auth/phone/login', { method: 'POST', body: { phone: phone.value, code: code.value } })
    setPortalMode(isTeamPortal ? 'team' : 'personal')
    setToken(data.access_token, data.refresh_token)
    if (isTeamPortal) router.push('/teams')
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

function editPhone() {
  step.value = 'phone'
  code.value = ''
  error.value = ''
  notice.value = ''
}

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="public-page auth-page">
    <button class="auth-back" type="button" @click="router.push('/login')">
      <ArrowLeft :size="20" /> 其他登录方式
    </button>

    <main class="auth-main">
      <form class="auth-card" @submit.prevent="step === 'phone' ? sendCode() : verify()">
        <div class="auth-mark phone" aria-hidden="true"><Smartphone :size="28" /></div>
        <h1>{{ isTeamPortal ? '团队端手机号登录' : '个人端手机号登录' }}</h1>
        <p class="auth-intro">{{ isTeamPortal ? '验证后进入独立团队控制台' : '未注册的手机号验证后将自动创建账号' }}</p>

        <template v-if="step === 'phone'">
          <label>手机号码
            <div class="input-wrap">
              <Smartphone :size="18" />
              <span class="phone-prefix">+86</span>
              <input v-model.trim="phone" type="tel" inputmode="numeric" maxlength="11" autocomplete="tel" placeholder="输入 11 位手机号" />
            </div>
          </label>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="button primary auth-submit" :disabled="loading || !phone">
            {{ loading ? '正在发送...' : '获取验证码' }}
          </button>
        </template>

        <template v-else>
          <div class="phone-sent-row">
            <span>验证码已发送至 +86 {{ phone }}</span>
            <button type="button" class="link-button" @click="editPhone">修改</button>
          </div>
          <label>短信验证码
            <div class="input-wrap"><ShieldCheck :size="18" /><input v-model.trim="code" type="text" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="输入验证码" /></div>
          </label>
          <p v-if="notice" class="form-notice">{{ notice }}<strong v-if="demoCode">，演示验证码：{{ demoCode }}</strong></p>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="button primary auth-submit" :disabled="loading || !code">
            {{ loading ? '正在验证...' : '验证并进入' }}
          </button>
          <button class="resend-button" type="button" :disabled="loading || countdown > 0" @click="sendCode">
            {{ countdown > 0 ? `${countdown} 秒后可重新发送` : '重新发送验证码' }}
          </button>
        </template>

        <p class="auth-agreement">继续即表示您同意服务条款与隐私政策</p>
      </form>
    </main>

  </div>
</template>
