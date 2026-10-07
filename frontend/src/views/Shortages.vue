<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { ShortagesPayload } from '../types'

const res = ref<ShortagesPayload | null>(null)
const missing = ref(false)
onMounted(async () => {
  try {
    res.value = await api<ShortagesPayload>('/prep/shortages')
  } catch {
    missing.value = true
  }
})

function modeText(mode: ShortagesPayload['mode']): string {
  if (mode === 'forbidden') return '禁替 · 鲜缺只跟鲜仓'
  if (mode === 'allowed_frozen') return '允许冻顶鲜'
  return '旧逻辑 · 未区分鲜冻'
}
</script>
<template>
  <h1>缺料便利贴</h1>
  <p class="sub">仅净缺为正的原料上贴；鲜品行只写鲜品不足（历史单快照原样保留）</p>
  <div v-if="missing" class="card">尚无备料单，先到备料台点「生成备料单」。</div>
  <template v-else-if="res">
    <div class="kp-shortage-sticky" style="max-width:380px;transform:rotate(-1deg);margin-bottom:1rem">
      <h2>⚠ 缺料 {{ res.stats.shortage_count }} · 合计 {{ res.stats.total_shortage_qty }} · {{ modeText(res.mode) }}</h2>
      <div v-for="r in res.shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>
          <span v-if="r.storage_type === 'fresh'" class="badge badge-ok" style="margin-right:0.25rem">鲜</span>{{ r.ingredient_name }}
        </span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>原料</th><th>仓别</th><th>需求</th><th>本行库存</th><th>毛缺</th><th>冻仓覆盖</th><th>净缺</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="r in res.shortages" :key="r.ingredient_id">
            <td>{{ r.ingredient_name }}</td>
            <td>{{ r.storage_type === 'fresh' ? '鲜品' : r.storage_type === 'frozen' ? '冻品' : '—' }}</td>
            <td>{{ r.need_qty }}</td><td>{{ r.stock_qty }}</td>
            <td>{{ r.gross_shortage }}</td><td>{{ r.covered_qty || '' }}</td>
            <td><span class="badge badge-bad">{{ r.shortage }}</span></td><td>{{ r.unit }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
