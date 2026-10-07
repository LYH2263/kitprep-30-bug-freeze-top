export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) throw new Error(await res.text() || res.statusText)
  if (res.status === 204) return undefined as T
  return res.json()
}

/** 从 Error(api 抛出的 FastAPI 错误体) 中提取 detail 文案。 */
export function errDetail(e: unknown, fallback = '请求失败'): string {
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message)
      if (parsed && typeof parsed.detail === 'string') return parsed.detail
    } catch { /* 非 JSON 错误体 */ }
    return e.message
  }
  return fallback
}
