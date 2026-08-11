<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  BrainCircuit,
  CheckCircle2,
  CircleDollarSign,
  Database,
  Gamepad2,
  LockKeyhole,
  Medal,
  Network,
  Share2,
  Sparkles,
  Star,
  Trophy,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import { api } from '../api'

const data = ref(null)
const loading = ref(true)
const error = ref('')

const iconMap = {
  first_material: Sparkles,
  material_collector: Database,
  archive_curator: Star,
  ready_library: CheckCircle2,
  evolution_start: BrainCircuit,
  evolution_master: Trophy,
  game_beginner: Gamepad2,
  game_runner: Medal,
  accurate_mind: CheckCircle2,
  coin_spark: CircleDollarSign,
  graph_builder: Network,
  knowledge_sharer: Share2,
}

const percent = computed(() => {
  if (!data.value?.total) return 0
  return Math.round(data.value.unlocked / data.value.total * 100)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api('/achievements')
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell search-placeholder="搜索成就...">
    <div class="page-wrap achievements-page">
      <section class="achievement-hero">
        <div>
          <span class="eyebrow"><Trophy /> Achievement Matrix</span>
          <h1>成就中心</h1>
          <p>记录知识采集、进化、训练、图谱和分享的成长轨迹。已解锁成就会点亮，未解锁成就显示当前进度。</p>
        </div>
        <aside>
          <strong>{{ data?.unlocked || 0 }}/{{ data?.total || 0 }}</strong>
          <span>已解锁</span>
          <i><b :style="{ width: percent + '%' }"></b></i>
          <small>{{ percent }}% 完成度</small>
        </aside>
      </section>

      <div v-if="loading" class="page-loader">正在加载成就矩阵...</div>
      <div v-else-if="error" class="empty-state">{{ error }}</div>
      <section v-else class="achievement-grid">
        <article
          v-for="item in data.items"
          :key="item.id"
          class="achievement-card"
          :class="{ unlocked: item.unlocked }"
        >
          <div class="achievement-icon">
            <component :is="item.unlocked ? (iconMap[item.id] || Trophy) : LockKeyhole" />
          </div>
          <div class="achievement-copy">
            <span>{{ item.unlocked ? '已解锁' : '待解锁' }}</span>
            <h2>{{ item.title }}</h2>
            <p>{{ item.description }}</p>
          </div>
          <div class="achievement-progress">
            <i><b :style="{ width: item.percent + '%' }"></b></i>
            <small>{{ item.progress }}/{{ item.target }}</small>
          </div>
        </article>
      </section>
    </div>
  </AppShell>
</template>
