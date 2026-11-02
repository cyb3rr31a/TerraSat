// TerraSat API client for the web app.
export const API = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')

export type Lang = 'en' | 'sw'
export type Turn = { role: 'user' | 'assistant'; text: string }
export type Bounds = { west: number; south: number; east: number; north: number }
export type AskReply = {
  reply: string
  use_case: string
  use_case_name: string | null
  place: { name: string; matched?: string; lat: number; lon: number; source: 'gps' | 'pin' | 'named' } | null
  audit: { audit_id: string; bounds: Bounds; files: { overlay: string; mosaic: string; geojson: string } } | null
  highlights: { label: string; value: string | number }[]
  competitors: {
    count: number; may_be_more: boolean; avg_rating: number | null
    nearest: { place_id: string; name: string; distance_m: number; rating: number | null; reviews: number }[]
  } | null
  sources: { url: string; title?: string }[]
}
export type Memo = { lang: Lang; markdown: string; sources: { url: string; title?: string }[] }
export type Feature = { geometry: { type: string; coordinates: number[] }; properties: Record<string, unknown> }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

const post = (body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const api = {
  ask: (body: { message: string; lang: Lang; lat?: number; lon?: number; history: Turn[] }) =>
    call<AskReply>('/ask', post(body)),
  memo: (auditId: string, lang: Lang) => call<Memo>(`/audit/${auditId}/memo?lang=${lang}`, { method: 'POST' }),
  // only the points (competitors, anchors, choke points, past floods): the picture already shows the rest
  points: async (geojsonPath: string) =>
    (await call<{ features: Feature[] }>(geojsonPath)).features.filter((f) => f.geometry.type === 'Point'),
}
