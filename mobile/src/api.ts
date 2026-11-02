// TerraSat API client, settings and the offline report queue.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { File } from 'expo-file-system';

export type Lang = 'en' | 'sw';
export type Settings = { apiUrl: string; lang: Lang; deviceId: string };

export type Report = {
  id: number; created_at: string; status: string; issue_type: string | null; place: string | null;
  urgency: string | null; summary_en: string | null; summary_sw: string | null; transcript: string | null;
  photo_path: string | null;
};
export type Question = { id: string; text: string; options: { id: string; label: string }[] };
export type ChatTurn = { role: 'user' | 'assistant'; text: string };
export type AskReply = {
  reply: string; use_case: string; use_case_name: string | null;
  place: { name: string; matched?: string; lat: number; lon: number; source: 'gps' | 'pin' | 'named' } | null;
  audit: { audit_id: string; files: { overlay: string; mosaic: string; geojson: string }; summary: Record<string, unknown> } | null;
  highlights: { label: string; value: string | number }[];
  ask: Question | null; sources: { url: string; title?: string }[];
  competitors: { source: string; count: number; may_be_more: boolean;
                 nearest: { place_id: string; name: string; distance_m: number; rating: number | null; reviews: number }[] } | null;
};
// A report recorded on the phone that the server hasn't confirmed yet.
export type QueuedReport = {
  clientId: string; createdAt: string; audioUri: string; photoUri?: string;
  lat?: number; lon?: number; accuracy?: number | null;
};

const SETTINGS_KEY = 'terrasat.settings';
const QUEUE_KEY = 'terrasat.queue';

export const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export async function loadSettings(): Promise<Settings> {
  const saved = JSON.parse((await AsyncStorage.getItem(SETTINGS_KEY)) ?? '{}');
  const s: Settings = { apiUrl: process.env.EXPO_PUBLIC_API_URL ?? '', lang: 'en', deviceId: newId(), ...saved };
  await saveSettings(s); // keeps the same deviceId from now on
  return s;
}

export const saveSettings = (s: Settings) => AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(s));

let base = '';
export const setApiUrl = (url: string) => { base = url.trim().replace(/\/+$/, ''); };
export const mediaUrl = (name: string) => `${base}/media/${name}`;
export const fileUrl = (path: string) => base + path; // e.g. /outputs/api/<id>/overlay.jpg

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  if (!base) throw new ApiError(0, 'Set the server address in Settings');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(base + path, { ...init, signal: ctrl.signal });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

// Expo's fetch uploads files as expo-file-system File objects (not React Native's { uri, name, type }).
const file = (uri: string) => new File(uri.includes('://') ? uri : `file://${uri}`);

const json = (body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const api = {
  health: () => request<{ status: string }>('/health', {}, 8000),
  ask: (body: { message: string; lang: Lang; lat?: number; lon?: number; on_site: boolean; device_id: string;
                history: ChatTurn[] }) => request<AskReply>('/ask', json(body), 150000), // a fresh audit takes ~1 min
  observe: (body: { question_id: string; answer: string; lat: number; lon: number; device_id: string; lang: Lang }) =>
    request<{ next: Question | null }>('/observations', json(body)),
  myReports: (deviceId: string) => request<Report[]>(`/reports?device_id=${encodeURIComponent(deviceId)}`),
};

// Report type labels come from the server (the audit profiles decide what can be reported).
let typeLabels: Record<string, { en: string; sw: string }> = {};
export async function loadReportTypes() {
  try { typeLabels = await request('/report-types', {}, 10000); } catch { /* keep the raw type names */ }
}
export const typeLabel = (type: string | null, lang: Lang) =>
  (type && typeLabels[type]?.[lang]) || (type ?? 'other').replace(/_/g, ' ');

function sendReport(r: QueuedReport, deviceId: string) {
  const form = new FormData();
  form.append('audio', file(r.audioUri));
  if (r.photoUri) form.append('photo', file(r.photoUri));
  if (r.lat != null && r.lon != null) {
    form.append('lat', String(r.lat));
    form.append('lon', String(r.lon));
    if (r.accuracy != null) form.append('accuracy_m', String(r.accuracy));
  }
  form.append('device_id', deviceId);
  form.append('client_id', r.clientId); // the server ignores repeats, so retrying is safe
  return request<Report>('/reports', { method: 'POST', body: form }, 120000); // transcription takes a while
}

// ------------------------------------------------------------- offline queue
export const getQueue = async (): Promise<QueuedReport[]> =>
  JSON.parse((await AsyncStorage.getItem(QUEUE_KEY)) ?? '[]');
const setQueue = (q: QueuedReport[]) => AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(q));

export async function enqueue(r: QueuedReport) {
  await setQueue([...(await getQueue()), r]);
}

let flushing = false;

/** Send queued reports, oldest first. Stops at the first network failure and keeps the rest
 *  for next time; drops a report the server rejects (it would never succeed). */
export async function flushQueue(deviceId: string): Promise<{ sent: number; rejected: string[]; error?: string }> {
  const result: { sent: number; rejected: string[]; error?: string } = { sent: 0, rejected: [] };
  if (flushing || !base) return result;
  flushing = true;
  try {
    for (const r of await getQueue()) {
      try {
        await sendReport(r, deviceId);
        result.sent++;
      } catch (e) {
        if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) { // offline or server down
          result.error = (e as Error).message;
          break;
        }
        result.rejected.push(e.message);
      }
      await setQueue((await getQueue()).filter((q) => q.clientId !== r.clientId));
    }
  } finally {
    flushing = false;
  }
  return result;
}
