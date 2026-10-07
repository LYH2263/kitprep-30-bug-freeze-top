export type StorageType = 'fresh' | 'frozen' | null
export type PrepMode = 'forbidden' | 'allowed_frozen' | null

export interface InventoryRow {
  id: number
  code: string
  name: string
  unit: string
  stock_qty: number
  storage_type: StorageType
}

export interface InventoryPayload {
  items: InventoryRow[]
  fresh_stock_total: number
  frozen_stock_total: number
}

export interface Setting {
  allow_frozen_substitute: boolean
  updated_at: string | null
}

export interface MarkerInput {
  code: string
  storage_type: StorageType
}

export interface PrepLine {
  ingredient_id: number
  ingredient_code: string
  ingredient_name: string
  unit: string
  storage_type: StorageType
  need_qty: number
  stock_qty: number
  gross_shortage: number
  covered_qty: number
  shortage: number
}

export interface PrepStats {
  ingredient_count: number
  shortage_count: number
  total_shortage_qty: number
  fresh_gross_total?: number
  fresh_net_total?: number
  frozen_pool?: number
  covered_by_frozen?: number
}

export interface PrepResult {
  id: number
  created_at?: string
  schema?: number
  mode: PrepMode
  order?: { id: number; code: string; outlet: string }
  prep_lines: PrepLine[]
  shortages: PrepLine[]
  stats: PrepStats
}

export interface ShortagesPayload {
  run_id: number
  mode: PrepMode
  order?: { id: number; code: string; outlet: string }
  shortages: PrepLine[]
  stats: PrepStats
}

export function storageLabel(t: StorageType): string {
  if (t === 'fresh') return '鲜品'
  if (t === 'frozen') return '冻品'
  return '未标记'
}
