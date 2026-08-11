<script setup>
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, Database, Link2, LockKeyhole, LogOut, MapPin, Medal, Rocket, Share2, Sparkles, Star, Trash2, Trophy } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue';import ModalDialog from '../components/ModalDialog.vue';import ToastMessage from '../components/ToastMessage.vue';import { api, clearToken } from '../api'
const router=useRouter();const data=ref(null);const modal=ref(false);const logoutConfirm=ref(false);const toast=ref('');const form=ref({name:'我的知识作品集',description:'持续进化的公开知识空间',scope:'all',expires_days:30,password:null})
const iconMap={
  first_material:Sparkles,
  material_collector:Database,
  archive_library:Database,
  material_marathon:Medal,
  ready_library:CheckCircle2,
  ready_archive:CheckCircle2,
  evolution_start:Rocket,
  evolution_master:Medal,
  knowledge_sharer:Share2,
}
async function load(){data.value=await api('/profile')}onMounted(load)
async function create(){await api('/shares',{method:'POST',body:form.value});modal.value=false;await load();notify('分享链接已创建')}
async function revoke(id){await api(`/shares/${id}`,{method:'DELETE'});await load();notify('分享已撤销')}
function copy(id){
  const url = `${location.origin}/share/${id}`
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(() => notify('链接已复制')).catch(() => fallbackCopy(url))
  } else {
    fallbackCopy(url)
  }
}
function fallbackCopy(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'; ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.focus(); ta.select()
  try { document.execCommand('copy'); notify('链接已复制') } catch { notify('复制失败，请手动复制链接') }
  document.body.removeChild(ta)
}
function notify(t){toast.value=t;setTimeout(()=>toast.value='',2500)}
function logout(){clearToken();logoutConfirm.value=false;router.replace('/login')}
const pct=computed(()=>data.value?data.value.xp/data.value.next_xp*100:0)
const visibleBadges=computed(()=>data.value?.achievement_items?.slice(0,6)||[])
</script>
<template><AppShell search-placeholder="搜索架构、勋章或链接..."><div v-if="!data" class="page-loader">正在加载个人档案...</div><div v-else class="page-wrap profile-page"><section class="profile-hero"><div class="profile-photo"><img src="/zhiyan_logo/screen.png" :alt="data.nickname + ' 的头像'" /></div><div class="profile-copy"><h1>{{data.nickname}}</h1><p class="profile-meta"><b>{{data.title}}</b><span><MapPin/> {{data.location}}</span></p><p>{{data.bio}}</p></div><div class="profile-buttons"><button class="button secondary">编辑资料</button><button class="button primary" @click="modal=true"><Share2/> 分享作品集</button><button class="button outline logout-button" @click="logoutConfirm=true"><LogOut/> 退出登录</button></div></section>
  <section class="profile-stats"><article class="panel"><span>进化等级</span><strong class="mint">{{data.level}}</strong><small>{{data.xp > 0 ? '持续进化中' : '刚起步'}}</small><i><b :style="{width:pct+'%'}"></b></i><em>{{data.xp.toLocaleString()}} / {{data.next_xp.toLocaleString()}} XP</em></article><article class="panel"><span>知识总量</span><strong>{{data.knowledge_total.toLocaleString()}} <small v-if="data.knowledge_total>0">持续积累</small></strong><p>已验证神经节点</p><div class="mini-nodes">▣ ◉ ◇ +{{Math.max(0,data.knowledge_total-3)}}</div></article><article class="panel achievement-summary"><span>成就勋章</span><strong>已解锁 {{data.achievements}} / {{data.total_achievements}} 枚</strong><p>{{data.achievements>=5?'成就斐然！':'继续收集更多勋章吧'}}</p><div>✦　ϟ　◈　♜　♙　+{{Math.max(0,data.total_achievements-5)}}</div></article></section>
   <div class="section-row"><h2>成就墙</h2><a>查看全部勋章</a></div><section class="achievement-wall"><article v-for="badge in visibleBadges" :key="badge.id" :class="{locked:!badge.unlocked}"><span><component :is="badge.unlocked?(iconMap[badge.id]||Trophy):LockKeyhole"/></span><strong>{{badge.title}}</strong><p>{{badge.description}}</p></article></section>
  <div class="section-row shares-title"><h2>我的分享链接</h2><button class="button outline" @click="modal=true">创建分享</button></div><section class="share-list"><article v-for="share in data.shares" :class="{inactive:share.status!=='active'}"><span class="share-icon"><Link2/></span><div><strong>{{share.name}}</strong><small>zhiyan.ai/share/{{share.id}} · {{share.scope==='all'?'全部知识':'筛选范围'}}</small></div><span class="share-status">{{share.status==='active'?'活跃':'已撤销'}}<small>{{share.expires_at?'限时有效':'永不过期'}}</small></span><button title="复制" @click="copy(share.id)"><Share2/></button><button title="撤销" @click="revoke(share.id)"><Trash2/></button></article><div v-if="!data.shares.length" class="empty-state">还没有分享链接，创建一个只读知识空间吧。</div></section>
  <ModalDialog v-if="modal" title="创建知识分享" @close="modal=false"><form class="stack-form" @submit.prevent="create"><label>分享名称<input v-model="form.name"/></label><label>简介<textarea v-model="form.description" rows="3"></textarea></label><label>有效期<select v-model="form.expires_days"><option :value="7">7 天</option><option :value="30">30 天</option><option :value="3650">永久</option></select></label><label>访问密码（可选）<input v-model="form.password" minlength="4" maxlength="8" placeholder="4-8 位"/></label><button class="button primary">生成分享链接</button></form></ModalDialog><ModalDialog v-if="logoutConfirm" title="确认退出登录" @close="logoutConfirm=false"><div class="logout-confirm"><p>退出后需要重新登录才能访问个人知识库。</p><div class="url-actions"><button class="button ghost" type="button" @click="logoutConfirm=false">取消</button><button class="button logout-danger" type="button" @click="logout">确认退出</button></div></div></ModalDialog><ToastMessage :message="toast"/></div></AppShell></template>
