<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errDetail } from '../api'
import type { PrepMode, PrepResult } from '../types'

const tree = ref<any[]>([])
const data = ref<PrepResult | null>(null)
const loading = ref(true)
const running = ref(false)
const error = ref('')

function modeBadge(mode: PrepMode): { text: string; cls: string } {
  if (mode === 'forbidden') return { text: '禁替 · 鲜缺只跟鲜仓', cls: 'badge badge-warn' }
  if (mode === 'allowed_frozen') return { text: '允许冻顶鲜 · 冻仓可冲鲜缺', cls: 'badge badge-ok' }
  return { text: '旧逻辑 · 未区分鲜冻', cls: 'badge' }
}

async function run() {
  running.value = true
  error.value = ''
  try {
    data.value = await api<PrepResult>('/prep/run', { method: 'POST' })
  } catch (e) {
    error.value = errDetail(e, '生成失败')
  } finally {
    running.value = false
  }
}

async function loadLatest() {
  loading.value = true
  try {
    data.value = await api<PrepResult>('/prep/latest')
  } catch {
    data.value = null // 404：尚无备料单
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  await loadLatest()
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中当前有效单备料表 · 右缺料便利贴（生成只读数，不扣库存）</p>
  <div style="display:flex;gap:0.6rem;align-items:center;margin-bottom:0.6rem">
    <button class="btn" :disabled="running" @click="run">
      {{ running ? '生成中…' : '生成备料单' }}
    </button>
    <span v-if="data" :class="modeBadge(data.mode).cls">{{ modeBadge(data.mode).text }}</span>
    <span v-if="data?.stats" class="muted" style="font-size:0.75rem">
      鲜毛缺 {{ data.stats.fresh_gross_total ?? '—' }} ·
      冻仓池 {{ data.stats.frozen_pool ?? '—' }} ·
      净鲜缺 {{ data.stats.fresh_net_total ?? '—' }}
    </span>
  </div>
  <div v-if="error" class="badge badge-bad" style="margin-bottom:0.6rem;white-space:pre-wrap">{{ error }}</div>
  <div v-if="!loading && !data && !error" class="card">尚无备料单，点「生成备料单」按当前已保存的鲜冻标记与开关出当前有效单。</div>

  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">{{ c.ingredient }} · {{ c.qty }} {{ c.unit }}</li>
        </ul>
      </div>
    </aside>
    <section class="kp-worksheet" v-if="data">
      <h2>备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
      <table>
        <thead><tr><th>原料</th><th>仓别</th><th>需求</th><th>本行库存</th><th>毛缺</th><th>冻仓覆盖</th><th>净缺</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
            <td>{{ l.ingredient_name }}</td>
            <td>
              <span v-if="l.storage_type === 'fresh'" class="badge badge-ok">鲜</span>
              <span v-else-if="l.storage_type === 'frozen'" class="badge badge-warn">冻</span>
              <span v-else class="muted">—</span>
            </td>
            <td>{{ l.need_qty }}</td>
            <td>{{ l.stock_qty }}</td>
            <td>{{ l.gross_shortage }}</td>
            <td>{{ l.covered_qty || '' }}</td>
            <td><span :class="l.shortage > 0 ? 'badge badge-bad' : ''">{{ l.shortage }}</span></td>
            <td>{{ l.unit }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in data?.shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>
          <span v-if="r.storage_type === 'fresh'" class="badge badge-ok" style="margin-right:0.25rem">鲜</span>{{ r.ingredient_name }}
        </span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!data?.shortages?.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>
</template>
