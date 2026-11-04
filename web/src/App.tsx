// TerraSat web: ask about any place in Nairobi. The map fills the screen; a floating panel holds the
// place search, the question box and a site report for every answer.
import { useEffect, useRef, useState } from 'react'
import { CircleMarker, ImageOverlay, LayersControl, MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents, ZoomControl } from 'react-leaflet'
import L from 'leaflet'
import { ChevronDown, ChevronUp, History, MapPin, Monitor, Moon, Search, Send, Sun, X } from 'lucide-react'
import { API, api, type AskReply, type Feature, type Lang, type Memo, type PlaceHit, type Turn } from './api'
import { MemoModal, Progress, SiteReport, USE_CASES } from './Report'

const NAIROBI: [number, number] = [-1.286, 36.817]
const POINT_COLORS: Record<string, string> = {
  competitor: '#E53935', anchor: '#1E88E5', choke_point: '#FB8C00', past_flood: '#8E24AA',
}
const LEGENDS: Record<string, [string, string][]> = {
  flood: [['#FF1744', 'High flood risk'], ['#FF9100', 'Medium'], ['#00E5FF', 'Low'], ['#2979FF', 'Watercourse'],
          ['#FB8C00', 'Drainage choke point']],
  business_site: [['#E53935', 'Competitor (OpenStreetMap)'], ['#1E88E5', 'School, clinic, market or stop'],
                  ['#00E5FF', 'Homes within 500 m']],
  densification: [['#00E5FF', 'Building'], ['#E040FB', 'New since footprint data']],
  solar_minigrid: [['#00E5FF', 'Roof'], ['#00E676', 'Solar panels']],
}
const pinIcon = L.divIcon({ className: 'pin', html: '<span></span>', iconSize: [22, 22] })
const RECENT_KEY = 'terrasat.recent'
const THEME_KEY = 'terrasat.theme'
type Theme = 'system' | 'light' | 'dark'

type Entry = { id: number; question: string; reply?: AskReply; error?: string; at?: { lat: number; lon: number } }
type Recent = { q: string; lat?: number; lon?: number }
type Pin = { lat: number; lon: number; label?: string; fly?: boolean }

const MAX_RECENT = 3
// Answers follow the device's language: Swahili if it's set to Swahili, English otherwise.
const lang: Lang = (navigator.language ?? 'en').toLowerCase().startsWith('sw') ? 'sw' : 'en'
const loadRecent = (): Recent[] => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]').slice(0, MAX_RECENT) } catch { return [] } }
const saveRecent = (r: Recent[]) => { try { localStorage.setItem(RECENT_KEY, JSON.stringify(r)) } catch { /* private mode */ } }
const loadTheme = (): Theme => { try { return (localStorage.getItem(THEME_KEY) as Theme) || 'system' } catch { return 'system' } }

export default function App() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [pin, setPin] = useState<Pin | null>(null)
  const [active, setActive] = useState<AskReply | null>(null)
  const [points, setPoints] = useState<Feature[]>([])
  const [opacity, setOpacity] = useState(0.9)
  const [memo, setMemo] = useState<Memo | null>(null)
  const [memoBusy, setMemoBusy] = useState(false)
  const [recent, setRecent] = useState<Recent[]>(loadRecent)
  const [expanded, setExpanded] = useState(false) // bottom sheet on small screens
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const lastRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // show the newest report from its top (braces: scrollIntoView may return a Promise, which React would call)
  useEffect(() => { lastRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [entries])

  useEffect(() => { // 'system' follows the device; the stylesheet reads data-theme
    if (theme === 'system') delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = theme
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* private mode */ }
  }, [theme])

  useEffect(() => {
    setPoints([])
    if (active?.audit) api.points(active.audit.files.geojson).then(setPoints).catch(() => setPoints([]))
  }, [active])

  useEffect(() => { // shared links: ?q=...&lat=...&lon=...
    const u = new URLSearchParams(location.search)
    const q = u.get('q'), lat = Number(u.get('lat')), lon = Number(u.get('lon'))
    if (q) send(q, u.get('lat') ? { lat, lon } : null)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function send(text: string, at: Pin | null = pin) {
    if (!text.trim() || busy) return
    setInput('')
    setExpanded(true)
    const id = Date.now()
    const history: Turn[] = entries.filter((e) => e.reply).slice(-3)
      .flatMap((e) => [{ role: 'user' as const, text: e.question }, { role: 'assistant' as const, text: e.reply!.reply }])
    setEntries((es) => [...es, { id, question: text, at: at ?? undefined }])
    setBusy(true)
    try {
      const r = await api.ask({ message: text, lang, history, ...(at ? { lat: at.lat, lon: at.lon } : {}) })
      setEntries((es) => es.map((e) => (e.id === id ? { ...e, reply: r } : e)))
      if (r.place) {
        setActive(r)
        setPin({ lat: r.place.lat, lon: r.place.lon, label: r.place.matched?.split(',')[0] ?? at?.label }) // follow-ups stay here
      }
      const next = [{ q: text, ...(at ?? {}) }, ...recent.filter((x) => x.q !== text)].slice(0, MAX_RECENT)
      setRecent(next)
      saveRecent(next)
    } catch (e) {
      setEntries((es) => es.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)))
    } finally {
      setBusy(false)
    }
  }

  async function openMemo(r: AskReply) {
    if (!r.audit) return
    setMemoBusy(true)
    try { setMemo(await api.memo(r.audit.audit_id, lang)) } catch (e) { alert((e as Error).message) } finally { setMemoBusy(false) }
  }

  const share = (e: Entry) => {
    const u = new URL(location.origin + location.pathname)
    u.searchParams.set('q', e.question)
    if (e.reply?.place) { u.searchParams.set('lat', e.reply.place.lat.toFixed(5)); u.searchParams.set('lon', e.reply.place.lon.toFixed(5)) }
    return u.toString()
  }

  const useCase = (id: string) => {
    const tmpl = { business_site: 'Is this a good spot for a pharmacy?', solar_minigrid: 'Can I put solar panels on this roof?',
                   densification: 'How built-up is this area, and is there room to build?', flood: 'Does this area flood?' }[id]!
    setInput(tmpl)
    inputRef.current?.focus()
  }

  return (
    <div className="app">
      <MapContainer center={NAIROBI} zoom={12} className="map" zoomControl={false}>
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Satellite">
            <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="Tiles © Esri — Esri, Maxar, Earthstar Geographics" maxZoom={19} />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Streets">
            <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap contributors" maxZoom={19} />
          </LayersControl.BaseLayer>
        </LayersControl>
        {active?.audit && (
          <ImageOverlay url={API + active.audit.files.overlay} opacity={opacity}
            bounds={[[active.audit.bounds.south, active.audit.bounds.west], [active.audit.bounds.north, active.audit.bounds.east]]} />
        )}
        {points.map((f, i) => {
          const cls = String(f.properties.class)
          const [lon, lat] = f.geometry.coordinates
          return POINT_COLORS[cls] ? (
            <CircleMarker key={i} center={[lat, lon]} radius={cls === 'competitor' ? 7 : 5}
              pathOptions={{ color: '#fff', weight: 2, fillColor: POINT_COLORS[cls], fillOpacity: 1 }}>
              <Popup>{pointLabel(f)}</Popup>
            </CircleMarker>
          ) : null
        })}
        {pin && <Marker position={[pin.lat, pin.lon]} icon={pinIcon} />}
        <ZoomControl position="topright" />
        <ClickToPin onPin={(p) => setPin(p)} />
        <FlyTo reply={active} pin={pin} />
      </MapContainer>

      {active?.audit && (
        <div className="mapcard">
          <div className="legend">
            <b>{USE_CASES[active.use_case]?.label ?? ''} analysis</b>
            {(LEGENDS[active.use_case] ?? []).map(([c, l]) => <div key={l}><i style={{ background: c }} />{l}</div>)}
          </div>
          <label className="opacity">Analysis layer
            <input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} />
          </label>
        </div>
      )}

      <aside className={`panel${expanded ? ' expanded' : ''}`}>
        <button className="grab" onClick={() => setExpanded(!expanded)} aria-label={expanded ? 'Collapse' : 'Expand'}>
          {expanded ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
        </button>
        <header>
          <div className="brand">
            <span className="logo" aria-hidden>◎</span>
            <div><h1>TerraSat</h1><p>Know a place before you build, buy or invest</p></div>
          </div>
          <div className="tools">
            <button className="theme" onClick={() => setTheme({ system: 'light', light: 'dark', dark: 'system' }[theme] as Theme)}
              aria-label={`Theme: ${theme}`} title={`Theme: ${theme}`}>
              {theme === 'light' ? <Sun size={16} /> : theme === 'dark' ? <Moon size={16} /> : <Monitor size={16} />}
            </button>
          </div>
        </header>

        <PlaceSearch onPick={(p) => setPin({ lat: p.lat, lon: p.lon, label: p.name, fly: true })} />

        <div className="scroll">
          {entries.length === 0 ? (
            <div className="landing">
              <h2>Ask anything about a place</h2>
              <p>TerraSat picks the right analysis, runs it on the satellite picture and answers with a verdict and the
                numbers behind it. Search a place or click the map to drop a pin.</p>
              <div className="ucgrid">
                {Object.entries(USE_CASES).map(([id, u]) => (
                  <button key={id} className="uccard" style={{ ['--uc' as string]: u.color }} onClick={() => send(u.example, null)}>
                    <u.icon size={20} /><b>{u.label}</b><span>{u.blurb}</span><em>“{u.example}”</em>
                  </button>
                ))}
              </div>
              {recent.length > 0 && (
                <div className="recent">
                  <h4><History size={14} />Recent</h4>
                  {recent.map((r) => (
                    <button key={r.q} onClick={() => send(r.q, r.lat != null ? { lat: r.lat, lon: r.lon! } : null)}>{r.q}</button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            entries.map((e, i) => <div key={e.id} ref={i === entries.length - 1 ? lastRef : undefined} className="entry">{e.reply ? (
              <SiteReport r={e.reply} question={e.question} showing={active === e.reply}
                onShow={() => { setActive(e.reply!); setExpanded(false) }} onMemo={() => openMemo(e.reply!)} memoBusy={memoBusy}
                shareUrl={share(e)} />
            ) : e.error ? (
              <div className="report error"><p className="question">“{e.question}”</p><p>{e.error}</p></div>
            ) : (
              <div className="report"><p className="question">“{e.question}”</p><Progress /></div>
            )}</div>)
          )}
        </div>

        <form className="composer" onSubmit={(ev) => { ev.preventDefault(); send(input) }}>
          <div className="chips">
            {Object.entries(USE_CASES).map(([id, u]) => (
              <button type="button" key={id} style={{ ['--uc' as string]: u.color }} onClick={() => useCase(id)}>
                <u.icon size={14} />{u.label}
              </button>
            ))}
          </div>
          {pin && (
            <span className="pinchip"><MapPin size={13} />{pin.label ?? `${pin.lat.toFixed(4)}, ${pin.lon.toFixed(4)}`}
              <button type="button" onClick={() => setPin(null)} aria-label="Remove pin"><X size={13} /></button></span>
          )}
          <div className="row">
            <input ref={inputRef} value={input} onChange={(ev) => setInput(ev.target.value)} disabled={busy}
              placeholder={lang === 'sw'
                ? (pin ? 'Uliza kuhusu eneo hili… (jibu kwa Kiswahili)' : 'Uliza kuhusu eneo, k.m. "Je, Kasarani inafaa kwa gym?"')
                : (pin ? 'Ask about this spot…' : 'Ask about a place, e.g. "Is Kasarani good for a gym?"')} />
            <button type="submit" disabled={busy || !input.trim()} aria-label="Ask"><Send size={18} /></button>
          </div>
        </form>
      </aside>

      {memo && <MemoModal memo={memo} onClose={() => setMemo(null)} />}
    </div>
  )
}

function PlaceSearch({ onPick }: { onPick: (p: PlaceHit) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<PlaceHit[]>([])
  const [note, setNote] = useState('')  // "no matches" or why the search failed, instead of silence
  useEffect(() => {
    setNote('')
    if (q.trim().length < 2) { setHits([]); return }
    const t = setTimeout(() => api.places(q)
      .then((h) => { setHits(h); if (!h.length) setNote('No matching place. Try a suburb or landmark, or click the map.') })
      .catch((e: Error) => { setHits([]); setNote(e.message) }), 200)
    return () => clearTimeout(t)
  }, [q])
  const pick = (h: PlaceHit) => { onPick(h); setQ(''); setHits([]) }
  return (
    <div className="search">
      <Search size={16} />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a place: Westlands, Sarit Centre, Ruaka…"
        aria-label="Find a place" onKeyDown={(e) => { if (e.key === 'Enter' && hits[0]) pick(hits[0]) }} />
      {hits.length > 0 && (
        <ul className="hits">
          {hits.map((h) => (
            <li key={`${h.name}${h.lat}`}><button onClick={() => pick(h)}>
              <MapPin size={14} /><b>{h.name}</b><span>{h.kind.replace(/_/g, ' ')}</span>
            </button></li>
          ))}
        </ul>
      )}
      {note && <ul className="hits"><li className="hit-note">{note}</li></ul>}
    </div>
  )
}

function ClickToPin({ onPin }: { onPin: (p: { lat: number; lon: number }) => void }) {
  useMapEvents({ click: (e) => onPin({ lat: e.latlng.lat, lon: e.latlng.lng }) })
  return null
}

function FlyTo({ reply, pin }: { reply: AskReply | null; pin: Pin | null }) {
  const map = useMap()
  useEffect(() => {
    if (reply?.audit) {
      const b = reply.audit.bounds
      const wide = window.innerWidth > 900 // keep the picture clear of the side panel / bottom sheet
      map.flyToBounds([[b.south, b.west], [b.north, b.east]], wide
        ? { duration: 1.2, paddingTopLeft: [470, 20], paddingBottomRight: [20, 20] }
        : { duration: 1.2, paddingTopLeft: [10, 10], paddingBottomRight: [10, window.innerHeight * 0.45] })
    }
  }, [reply, map])
  useEffect(() => { // a place picked from search: go there
    if (pin?.fly) map.flyTo([pin.lat, pin.lon], 16, { duration: 1 })
  }, [pin, map])
  return null
}

function pointLabel(f: Feature) {
  const p = f.properties
  const name = (p.name as string) || (p.place as string) || ''
  const kind = { competitor: 'Competitor', anchor: `Nearby ${String(p.kind ?? 'place')}`, choke_point: 'Drainage choke point',
                 past_flood: `Past flood${p.date ? `, ${p.date}` : ''}` }[String(p.class)]
  return `${kind}${name ? `: ${name}` : ''}${p.distance_m != null ? ` · ${p.distance_m} m` : ''}`
}
