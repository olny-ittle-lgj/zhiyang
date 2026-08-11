<script setup>
import { ArrowLeft, Building2, LockKeyhole, Smartphone, UserRound } from 'lucide-vue-next'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const activePortal = ref('personal') // 'personal' | 'team'

function goAuth(space, method = 'account') {
  router.push({ path: method === 'phone' ? '/login/phone' : '/login/account', query: { space } })
}
</script>

<template>
  <div class="public-page auth-page login-shell">
    <div class="login-scene" aria-hidden="true">
      <div class="login-grid"></div>
      <div class="login-visual">
        <div class="login-orbit orbit-outer"></div>
        <div class="login-orbit orbit-middle"></div>
        <div class="login-orbit orbit-inner"></div>
        <div class="login-core">
          <img src="/zhiyan_logo/screen.png" alt="" />
          <span class="core-pulse"></span>
        </div>
        <i class="login-node node-one"></i>
        <i class="login-node node-two"></i>
        <i class="login-node node-three"></i>
        <i class="login-node node-four"></i>
      </div>

      <div class="login-terminal">
        <div class="terminal-heading">
          <span><i></i> KNOWLEDGE CORE</span>
          <b>ONLINE</b>
        </div>
        <p>&gt; 正在连接个人知识空间...</p>
        <p>&gt; RAGFlow 多路召回已就绪</p>
        <p>&gt; 等待身份验证以继续进化</p>
        <div class="terminal-progress"><i></i></div>
        <div class="terminal-tags"><b>RAGFLOW</b><b>MILVUS</b><b>AGENTS</b></div>
      </div>
    </div>

    <button class="auth-back login-back" type="button" @click="router.push('/')">
      <ArrowLeft :size="20" /> 返回首页
    </button>

    <main class="auth-main login-main">
      <section class="auth-card login-card" aria-labelledby="auth-title">
        <div class="login-card-topline"><span>ZHIYAN / AUTH GATE</span><span>SECURE ACCESS</span></div>
        <div class="auth-mark login-mark" aria-hidden="true"><img src="/zhiyan_logo/screen.png" alt="" /></div>
        <h1 id="auth-title">进入知衍</h1>
        <p class="auth-intro">选择个人端或团队端，进入不同的数据空间与工作流</p>

        <!-- Portal Tabs -->
        <div class="login-portal-tabs">
          <button
            :class="{ active: activePortal === 'personal' }"
            @click="activePortal = 'personal'"
          >
            <UserRound :size="16" /> 个人端
          </button>
          <button
            :class="{ active: activePortal === 'team' }"
            @click="activePortal = 'team'"
          >
            <Building2 :size="16" /> 团队端
          </button>
        </div>

        <!-- ===== 个人端面板 ===== -->
        <div v-if="activePortal === 'personal'" class="login-form-panel">
          <div class="login-dual-actions">
            <button class="login-action-btn primary-action" @click="goAuth('personal', 'account')">
              <LockKeyhole :size="16" /> 账号进入
            </button>
            <button class="login-action-btn secondary-action" @click="goAuth('personal', 'phone')">
              <Smartphone :size="16" /> 手机进入
            </button>
          </div>
        </div>

        <!-- ===== 团队端面板 ===== -->
        <div v-if="activePortal === 'team'" class="login-form-panel">
          <div class="login-dual-actions">
            <button class="login-action-btn primary-action" @click="goAuth('team', 'account')">
              <LockKeyhole :size="16" /> 账号进入
            </button>
            <button class="login-action-btn secondary-action" @click="goAuth('team', 'phone')">
              <Smartphone :size="16" /> 手机进入
            </button>
          </div>
        </div>

        <div class="login-status"><span></span>知识进化引擎在线 <b>V3.7</b></div>
        <p class="auth-agreement">继续即表示您同意服务条款与隐私政策</p>
      </section>
    </main>
  </div>
</template>

<style scoped>
/* ===== Portal Tabs ===== */
.login-portal-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin-top: 24px;
  padding: 4px;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 10px;
  background: rgba(7, 25, 45, .6);
}

.login-portal-tabs button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 42px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #8fb4c9;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all .2s;
}

.login-portal-tabs button:hover {
  color: #c2e7f5;
  background: rgba(125, 249, 255, .06);
}

.login-portal-tabs button.active {
  border-color: rgba(125, 249, 255, .28);
  background: rgba(8, 58, 80, .7);
  color: #7df9ff;
  font-weight: 600;
  box-shadow: 0 0 12px rgba(0, 213, 255, .1);
}

/* ===== Form Panel ===== */
.login-form-panel {
  margin-top: 22px;
}

/* ===== Dual Action Buttons ===== */
.login-dual-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.login-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 42px;
  border: 1px solid rgba(125, 249, 255, .16);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all .18s;
}

.primary-action {
  background: rgba(8, 58, 80, .56);
  color: #c8eaf5;
  border-color: rgba(125, 249, 255, .24);
}

.primary-action:hover {
  background: rgba(12, 72, 98, .7);
  border-color: rgba(125, 249, 255, .5);
  color: #e7fbff;
  box-shadow: 0 0 16px rgba(0, 213, 255, .1);
}

.secondary-action {
  background: rgba(16, 67, 66, .38);
  color: #8cc7b8;
  border-color: rgba(162, 255, 214, .18);
}

.secondary-action:hover {
  background: rgba(20, 80, 78, .56);
  border-color: rgba(162, 255, 214, .4);
  color: #a2ffd6;
  box-shadow: 0 0 14px rgba(162, 255, 214, .08);
}

/* ===== Responsive ===== */
@media (max-width: 640px) {
  .login-card {
    padding: 24px 20px 20px !important;
  }

  .login-card h1 {
    font-size: 28px;
  }
}
</style>
