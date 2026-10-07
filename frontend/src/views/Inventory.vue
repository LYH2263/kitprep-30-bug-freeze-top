<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errDetail } from '../api'
import type { InventoryPayload, Setting, StorageType } from '../types'

const items = ref<InventoryPayload | null>(null)
const setting = ref<Setting | null>(null)
const drafts = ref<Record<string, StorageType>>({})
const switchDraft = ref<boolean>(false)
const savingMarkers = ref(false)
const savingSwitch = ref(false)
const loading = ref(true)
const message = ref('')
const error = ref('')

const dirtyCount = computed(
  () => Object.keys(drafts.value).filter((code) => {
    const row = items.value?.items.find((r) => r.code === code)
    return row && row.storage_type !== drafts.value[code]
  }).length,
)
const switchDirty = computed(
  () => setting.value !== null && setting.value.allow_frozen_substitute !== switchDraft.value,
)

async function load() {
  loading.value = true
  try {
    const [inv, st] = await Promise.all([
      api<InventoryPayload>('/inventory'),
      api<Setting>('/settings'),
    ])
    items.value = inv
    setting.value = st
    drafts.value = Object.fromEntries(inv.items.map((r) => [r.code, r.storage_type]))
    switchDraft.value = st.allow_frozen_substitute
    error.value = ''
  } catch (e) {
    error.value = errDetail(e, '加载失败')
  } finally {
    loading.value = false
  }
}

async function saveMarkers() {
  if (!items.value) return
  const markers = items.value.items
    .filter((r) => drafts.value[r.code] !== r.storage_type)
    .map((r) => ({ code: r.code, storage_type: drafts.value[r.code] }))
  savingMarkers.value = true
  message.value = ''
  error.value = ''
  try {
    const res = await api<InventoryPayload & { updated: number }>('/inventory/markers', {
      method: 'PUT',
      body: JSON.stringify({ markers }),
    })
    items.value = res
    drafts.value = Object.fromEntries(res.items.map((r) => [r.code, r.storage_type]))
    message.value = `已保存 ${res.updated} 项标记`
  } catch (e) {
    error.value = errDetail(e, '保存标记失败')
  } finally {
    savingMarkers.value = false
  }
}

async function saveSwitch() {
  savingSwitch.value = true
  message.value = ''
  error.value = ''
  try {
    setting.value = await api<Setting>('/settings', {
      method: 'PUT',
      body: JSON.stringify({ allow_frozen_substitute: switchDraft.value }),
    })
    message.value = switchDraft.value ? '已切换为允许冻顶鲜' : '已切换为禁替（鲜缺只跟鲜仓）'
  } catch (e) {
    error.value = errDetail(e, '保存开关失败')
    if (setting.value) switchDraft.value = setting.value.allow_frozen_substitute
  } finally {
    savingSwitch.value = false
  }
}

onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 鲜仓 / 冻仓分套记账</p>

  <div class="card" style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center">
    <div>
      <div class="muted" style="font-size:0.75rem">鲜仓账面合计</div>
      <div class="stat" style="color:var(--kp-ok)">{{ items?.fresh_stock_total ?? '—' }}</div>
    </div>
    <div>
      <div class="muted" style="font-size:0.75rem">冻仓账面合计</div>
      <div class="stat" style="color:var(--kp-accent)">{{ items?.frozen_stock_total ?? '—' }}</div>
    </div>
    <div style="flex:1;min-width:220px">
      <label style="display:flex;gap:0.5rem;align-items:center;font-weight:700;font-size:0.9rem">
        <input type="checkbox" v-model="switchDraft" :disabled="savingSwitch || !setting"
               style="width:1.1rem;height:1.1rem">
        允许冻顶鲜
      </label>
      <div class="muted" style="font-size:0.72rem;margin-top:0.2rem">
        当前已保存：<b>{{ setting?.allow_frozen_substitute ? '允许冻顶鲜' : '禁替' }}</b>
        <span v-if="switchDirty" class="badge badge-warn" style="margin-left:0.3rem">有未保存改动，不影响出单</span>
      </div>
    </div>
    <button class="btn" :disabled="savingSwitch || !switchDirty" @click="saveSwitch">保存开关</button>
  </div>

  <p class="muted" style="font-size:0.78rem">生成备料单只读数，不扣减库存；库存结存在生成前后保持不变。</p>

  <div v-if="message" class="badge badge-ok" style="margin-bottom:0.5rem">{{ message }}</div>
  <div v-if="error" class="badge badge-bad" style="margin-bottom:0.5rem;white-space:pre-wrap">{{ error }}</div>

  <div class="card" v-if="!loading && items">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem">
      <strong>原料标记</strong>
      <button class="btn" :disabled="savingMarkers || dirtyCount === 0" @click="saveMarkers">
        保存标记<span v-if="dirtyCount">（{{ dirtyCount }} 项未保存）</span>
      </button>
    </div>
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>单位</th><th>仓别</th></tr></thead>
      <tbody>
        <tr v-for="r in items.items" :key="r.id">
          <td>{{ r.code }}</td>
          <td>{{ r.name }}</td>
          <td>{{ r.stock_qty }}</td>
          <td>{{ r.unit }}</td>
          <td>
            <select v-model="drafts[r.code]" style="padding:0.2rem">
              <option :value="null">未标记</option>
              <option value="fresh">鲜品</option>
              <option value="frozen">冻品</option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
