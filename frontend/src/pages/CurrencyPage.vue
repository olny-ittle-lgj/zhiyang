<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CalendarCheck2,
  CircleDollarSign,
  Gem,
  PackageOpen,
  ReceiptText,
  RefreshCw,
  ShoppingBag,
} from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import { api } from '../api'

const wallet = ref(null)
const transactions = ref([])
const storeItems = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const activeTab = ref('ledger')
const checkedIn = ref(false)
const purchaseQuantity = ref({})

const knowledge = computed(() => wallet.value?.knowledge_balance || 0)
const truth = computed(() => wallet.value?.truth_balance || 0)
const checkin = computed(() => wallet.value?.last_checkin || null)
const today = computed(() => wallet.value?.today || { usage: {}, quotas: {} })

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function currencyLabel(value) {
  return value === 'truth' ? '真知晶' : '学识币'
}

function toast(message) {
  notice.value = message
  window.setTimeout(() => {
    if (notice.value === message) notice.value = ''
  }, 2800)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [walletPayload, transactionPayload, storePayload] = await Promise.all([
      api('/currency/wallet'),
      api('/currency/transactions?limit=120'),
      api('/currency/store'),
    ])
    wallet.value = walletPayload
    transactions.value = transactionPayload.items || []
    storeItems.value = storePayload.items || []
    checkedIn.value = walletPayload.last_checkin?.day === new Date().toISOString().slice(0, 10)
  } catch (err) {
    error.value = err?.message || '货币中心加载失败'
  } finally {
    loading.value = false
  }
}

async function checkIn() {
  saving.value = true
  try {
    const result = await api('/currency/check-in', { method: 'POST' })
    wallet.value = result.wallet
    checkedIn.value = true
    await refreshLedger()
    toast(result.claimed ? `签到成功，连续第 ${result.checkin.streak} 天` : '今天已经签到过了')
  } catch (err) {
    error.value = err?.message || '签到失败'
  } finally {
    saving.value = false
  }
}

async function refreshLedger() {
  const [walletPayload, transactionPayload] = await Promise.all([
    api('/currency/wallet'),
    api('/currency/transactions?limit=120'),
  ])
  wallet.value = walletPayload
  transactions.value = transactionPayload.items || []
}

async function purchase(item) {
  const quantity = Math.max(1, Number(purchaseQuantity.value[item.item_id] || 1))
  saving.value = true
  try {
    const result = await api('/currency/store/purchase', {
      method: 'POST',
      body: {
        item_id: item.item_id,
        quantity,
        idempotency_key: `store:${item.item_id}:${Date.now()}`,
      },
    })
    wallet.value = result.wallet
    await refreshLedger()
    toast(`已兑换 ${item.name} x${quantity}`)
  } catch (err) {
    error.value = err?.message || '兑换失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell search-placeholder="搜索货币流水...">
    <div class="page-wrap currency-page">
      <header class="currency-heading">
        <div>
          <span class="eyebrow"><CircleDollarSign /> 个人货币中心</span>
          <h1>学识币与真知晶</h1>
          <p>个人钱包独立于团队公共资金池，所有获取、消耗和额度变化都会保留流水。</p>
        </div>
        <div class="currency-heading-actions">
          <button class="button ghost" type="button" :disabled="loading" @click="load"><RefreshCw />刷新</button>
          <button class="button primary" type="button" :disabled="saving || checkedIn" @click="checkIn"><CalendarCheck2 />{{ checkedIn ? '今日已签到' : '每日签到' }}</button>
        </div>
      </header>

      <p v-if="error" class="currency-alert error">{{ error }}</p>
      <p v-if="notice" class="currency-alert">{{ notice }}</p>
      <div v-if="loading" class="panel currency-loading">正在同步个人钱包...</div>

      <template v-else>
        <section class="currency-balance-grid">
          <article class="panel currency-balance-card knowledge">
            <span class="currency-balance-icon"><CircleDollarSign /></span>
            <div><small>个人通用余额</small><strong>{{ knowledge.toLocaleString() }}</strong><b>学识币</b></div>
            <p>学习、问答、素材和游戏行为使用</p>
          </article>
          <article class="panel currency-balance-card truth">
            <span class="currency-balance-icon"><Gem /></span>
            <div><small>个人稀缺余额</small><strong>{{ truth.toLocaleString() }}</strong><b>真知晶</b></div>
            <p>进化、永久分享和高价值能力使用</p>
          </article>
        </section>

        <section class="currency-checkin-strip panel">
          <div><CalendarCheck2 /><span><strong>连续签到 {{ checkin?.streak || 0 }} 天</strong><small>今日奖励：{{ checkin?.knowledge_amount || 0 }} 学识币<span v-if="checkin?.truth_amount"> + {{ checkin.truth_amount }} 真知晶</span></small></span></div>
          <span class="currency-isolation-note">个人钱包与团队资金池完全隔离</span>
        </section>

        <section class="currency-quota-grid">
          <article v-for="(config, action) in today.quotas" :key="action" class="panel currency-quota-item">
            <span><strong>{{ config.label }}</strong><small>每日免费 {{ config.free }} 次，超出 {{ config.cost }} {{ currencyLabel(config.currency) }}/次</small></span>
            <b>{{ today.usage[action]?.free_used || 0 }} / {{ config.free }}</b>
          </article>
        </section>

        <section class="panel currency-workbench">
          <header class="currency-tabs">
            <button type="button" :class="{ active: activeTab === 'ledger' }" @click="activeTab = 'ledger'"><ReceiptText />收支流水</button>
            <button type="button" :class="{ active: activeTab === 'store' }" @click="activeTab = 'store'"><ShoppingBag />个人商店</button>
          </header>

          <div v-if="activeTab === 'ledger'" class="currency-ledger">
            <article v-for="item in transactions" :key="item.id" class="currency-ledger-row">
              <span class="currency-ledger-icon" :class="{ income: item.amount > 0, expense: item.amount < 0 }">
                <ArrowDownToLine v-if="item.amount > 0" />
                <ArrowUpFromLine v-else />
              </span>
              <span class="currency-ledger-main"><strong>{{ item.reason || item.reason_code }}</strong><small>{{ currencyLabel(item.currency) }} · {{ formatTime(item.created_at) }} · {{ item.reference_type || '系统操作' }}</small></span>
              <b :class="item.amount > 0 ? 'currency-income' : 'currency-expense'">{{ item.amount > 0 ? '+' : '' }}{{ item.amount }}</b>
              <small class="currency-after">余额 {{ item.balance_after }}</small>
            </article>
            <div v-if="!transactions.length" class="currency-empty"><ReceiptText />暂无收支记录</div>
          </div>

          <div v-else class="currency-store">
            <article v-for="item in storeItems" :key="item.item_id" class="currency-store-row">
              <span class="currency-store-icon"><PackageOpen /></span>
              <div><strong>{{ item.name }}</strong><p>{{ item.description }}</p><small>{{ item.price }} {{ currencyLabel(item.currency) }} · 已拥有 {{ item.owned || 0 }}</small></div>
              <div class="currency-store-buy">
                <input v-model.number="purchaseQuantity[item.item_id]" type="number" min="1" max="99" aria-label="购买数量" />
                <button class="button secondary" type="button" :disabled="saving" @click="purchase(item)"><ShoppingBag />兑换</button>
              </div>
            </article>
            <div v-if="!storeItems.length" class="currency-empty"><ShoppingBag />商店暂未开放</div>
          </div>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.currency-page {
  padding-top: 30px;
  padding-bottom: 48px;
}

.currency-heading,
.currency-heading-actions,
.currency-checkin-strip,
.currency-checkin-strip > div,
.currency-tabs,
.currency-ledger-row,
.currency-store-row,
.currency-store-buy {
  display: flex;
  align-items: center;
}

.currency-heading {
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
}

.currency-heading h1 {
  margin: 9px 0 6px;
  font-size: 34px;
}

.currency-heading p,
.currency-balance-card p,
.currency-store-row p {
  color: var(--muted);
  line-height: 1.7;
}

.currency-heading-actions {
  gap: 10px;
}

.currency-alert {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0 0 14px;
  color: var(--mint);
}

.currency-alert.error {
  color: var(--red);
}

.currency-loading,
.currency-empty {
  display: grid;
  place-items: center;
  min-height: 180px;
  color: var(--muted);
}

.currency-balance-grid,
.currency-quota-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.currency-balance-card {
  position: relative;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 15px;
  min-height: 154px;
  padding: 22px;
  overflow: hidden;
}

.currency-balance-card::after {
  position: absolute;
  right: 18px;
  bottom: -26px;
  width: 128px;
  height: 128px;
  border: 1px solid currentColor;
  border-radius: 50%;
  opacity: .12;
  content: '';
}

.currency-balance-card.knowledge {
  color: var(--cyan);
}

.currency-balance-card.truth {
  color: #ffd479;
}

.currency-balance-icon {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
}

.currency-balance-icon svg {
  width: 24px;
  height: 24px;
}

.currency-balance-card div {
  display: grid;
  gap: 3px;
}

.currency-balance-card small,
.currency-balance-card strong,
.currency-balance-card b {
  display: block;
}

.currency-balance-card small,
.currency-balance-card p {
  color: var(--muted);
}

.currency-balance-card strong {
  color: #f1fdff;
  font-size: 34px;
}

.currency-balance-card b {
  font-size: 12px;
}

.currency-balance-card p {
  grid-column: 2;
  margin: 0;
}

.currency-checkin-strip {
  justify-content: space-between;
  gap: 15px;
  margin-top: 18px;
  padding: 16px 18px;
}

.currency-checkin-strip > div {
  gap: 10px;
}

.currency-checkin-strip svg {
  color: var(--mint);
}

.currency-checkin-strip span {
  display: grid;
  gap: 3px;
}

.currency-checkin-strip small {
  color: var(--muted);
}

.currency-isolation-note {
  color: var(--muted);
  font-size: 12px;
}

.currency-quota-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 18px;
}

.currency-quota-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 15px;
}

.currency-quota-item span {
  display: grid;
  gap: 4px;
}

.currency-quota-item small {
  color: var(--muted);
  line-height: 1.4;
}

.currency-quota-item > b {
  color: var(--cyan);
  white-space: nowrap;
}

.currency-workbench {
  margin-top: 18px;
  overflow: hidden;
}

.currency-tabs {
  gap: 4px;
  padding: 9px;
  border-bottom: 1px solid var(--outline);
}

.currency-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 13px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
}

.currency-tabs button.active,
.currency-tabs button:hover {
  border-color: rgba(125, 249, 255, .25);
  background: rgba(125, 249, 255, .08);
  color: var(--cyan);
}

.currency-ledger,
.currency-store {
  padding: 0 18px 14px;
}

.currency-ledger-row,
.currency-store-row {
  gap: 12px;
  min-height: 66px;
  border-bottom: 1px solid var(--outline);
}

.currency-ledger-icon,
.currency-store-icon {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border-radius: 8px;
  background: rgba(125, 249, 255, .08);
}

.currency-ledger-icon.income {
  color: var(--mint);
}

.currency-ledger-icon.expense {
  color: #ffd479;
}

.currency-ledger-main,
.currency-store-row > div:nth-child(2) {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.currency-ledger-main small,
.currency-store-row small,
.currency-after {
  color: var(--muted);
}

.currency-income,
.currency-expense {
  margin-left: auto;
  white-space: nowrap;
}

.currency-income {
  color: var(--mint);
}

.currency-expense {
  color: #ffd479;
}

.currency-after {
  width: 80px;
  text-align: right;
}

.currency-store-row {
  min-height: 86px;
}

.currency-store-icon {
  color: var(--cyan);
}

.currency-store-row p {
  margin: 0;
  font-size: 13px;
}

.currency-store-buy {
  gap: 8px;
  margin-left: auto;
}

.currency-store-buy input {
  width: 58px;
}

@media (max-width: 760px) {
  .currency-heading,
  .currency-checkin-strip {
    align-items: flex-start;
    flex-direction: column;
  }

  .currency-heading-actions,
  .currency-heading-actions .button {
    width: 100%;
  }

  .currency-balance-grid,
  .currency-quota-grid {
    grid-template-columns: 1fr;
  }

  .currency-store-row {
    align-items: flex-start;
    flex-wrap: wrap;
    padding: 14px 0;
  }

  .currency-store-buy {
    width: 100%;
    margin-left: 44px;
  }

  .currency-after {
    display: none;
  }
}
</style>
