// TerraSat web: ask about any place in Nairobi. Chat on the left, map on the right; each answer
// puts the satellite picture with the findings on the map, with the key numbers beside it.
import { useEffect, useRef, useState } from 'react'
import { CircleMarker, ImageOverlay, LayersControl, MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { API, api, type AskReply, type Feature, type Lang, type Memo, type Turn } from './api'

const NAIROBI: [number, number] = [-1.286, 36.817]
const EXAMPLES = [
  'Is this a good spot for a pharmacy?',
  'Can I put solar panels on this roof?',
  'How built-up is Kilimani, and is there room to build?',
  'Does South C flood?',
]
const POINT_COLORS: Record<string, string> = {
  competitor: '#E53935', anchor: '#1E88E5', choke_point: '#FB8C00', past_flood: '#8E24AA',
}
// Leaflet's default marker images don't survive bundling; a small CSS dot is enough for the pin
const pinIcon = L.divIcon({ className: 'pin', iconSize: [18, 18] })

type Msg = { id: number; role: 'user' | 'assistant'; text: string; reply?: AskReply; error?: boolean }

export default function App() {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [lang, setLang] = useState<Lang>('en')
  const [pin, setPin] = useState<{ lat: number; lon: number } | null>(null)
  const [active, setActive] = useState<AskReply | null>(null)
  const [points, setPoints] = useState<Feature[]>([])
  const [memo, setMemo] = useState<Memo | null>(null)
  const [memoBusy, setMemoBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy]) // braces: newer browsers return a Promise here

  useEffect(() => { // the clickable points of the answer shown on the map
    setPoints([])
    if (active?.audit) api.points(active.audit.files.geojson).then(setPoints).catch(() => setPoints([]))
  }, [active])

  async function send(text: string) {
    if (!text.trim() || busy) return
    setInput('')
    const history: Turn[] = msgs.slice(-6).map(({ role, text }) => ({ role, text }))
    setMsgs((m) => [...m, { id: Date.now(), role: 'user', text }])
    setBusy(true)
    try {
      const r = await api.ask({ message: text, lang, history, ...(pin ?? {}) })
      setMsgs((m) => [...m, { id: Date.now(), role: 'assistant', text: r.reply, reply: r }])
      if (r.place) {
        setActive(r)
        if (r.place.source === 'named') setPin({ lat: r.place.lat, lon: r.place.lon }) // follow-ups stay here
      }
    } catch (e) {
      setMsgs((m) => [...m, { id: Date.now(), role: 'assistant', text: (e as Error).message, error: true }])
    } finally {
      setBusy(false)
    }
  }

  async function openMemo(r: AskReply) {
    if (!r.audit) return
    setMemoBusy(true)
    try {
      setMemo(await api.memo(r.audit.audit_id, lang))
    } catch (e) {
      alert((e as Error).message)
    } finally {
      setMemoBusy(false)
    }
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo" aria-hidden>◎</span>
          <div>
            <h1>TerraSat</h1>
            <p>Know a place before you build, buy or invest</p>
          </div>
        </div>
        <div className="lang" role="group" aria-label="Answer language">
          {(['en', 'sw'] as const).map((l) => (
            <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l === 'en' ? 'English' : 'Kiswahili'}</button>
          ))}
        </div>
      </header>

      <main>
        <section className="chat" aria-label="Conversation">
          <div className="messages">
            {msgs.length === 0 && (
              <div className="welcome">
                <h2>Ask about any place in Nairobi</h2>
                <p>Name a place in your question, or click the map to drop a pin. TerraSat picks the right analysis,
                  runs it on the satellite picture and answers with a verdict and the numbers behind it.</p>
                <div className="examples">
                  {EXAMPLES.map((ex) => <button key={ex} onClick={() => send(ex)}>{ex}</button>)}
                </div>
                <p className="hint">Tip: drop a pin first for "this spot" questions.</p>
              </div>
            )}
            {msgs.map((m) => (
              <div key={m.id} className={`msg ${m.role}${m.error ? ' error' : ''}`}>
                {m.reply?.use_case_name && <span className="tag">{m.reply.use_case_name}</span>}
                <p className="text">{m.text}</p>
                {m.reply && <ReplyDetails r={m.reply} onShow={() => setActive(m.reply!)} onMemo={() => openMemo(m.reply!)}
                  memoBusy={memoBusy} showing={active === m.reply} />}
              </div>
            ))}
            {busy && <div className="msg assistant thinking">Looking at the satellite picture and the data… the first time
              in a new area takes up to a minute.</div>}
            <div ref={endRef} />
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input) }}>
            {pin && (
              <span className="pinchip">📍 {pin.lat.toFixed(4)}, {pin.lon.toFixed(4)}
                <button type="button" onClick={() => setPin(null)} aria-label="Remove pin">×</button></span>
            )}
            <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy}
              placeholder={pin ? 'Ask about the pinned spot…' : 'Ask about a place, e.g. "Is Westlands good for a gym?"'} />
            <button type="submit" disabled={busy || !input.trim()}>Ask</button>
          </form>
        </section>

        <section className="map" aria-label="Map">
          <MapContainer center={NAIROBI} zoom={12} style={{ height: '100%', width: '100%' }}>
            <LayersControl position="topright">
              <LayersControl.BaseLayer checked name="Satellite">
                <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                  attribution="Tiles © Esri — Esri, Maxar, Earthstar Geographics" maxZoom={19} />
              </LayersControl.BaseLayer>
              <LayersControl.BaseLayer name="Streets">
                <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap contributors" maxZoom={19} />
              </LayersControl.BaseLayer>
              {active?.audit && (
                <LayersControl.Overlay checked name="TerraSat analysis">
                  <ImageOverlay url={API + active.audit.files.overlay} opacity={0.92}
                    bounds={[[active.audit.bounds.south, active.audit.bounds.west], [active.audit.bounds.north, active.audit.bounds.east]]} />
                </LayersControl.Overlay>
              )}
            </LayersControl>
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
            <ClickToPin onPin={setPin} />
            <FlyTo reply={active} />
          </MapContainer>
          {active?.audit && <Legend useCase={active.use_case} />}
        </section>
      </main>

      {memo && (
        <div className="modal" role="dialog" aria-modal="true" onClick={() => setMemo(null)}>
          <article onClick={(e) => e.stopPropagation()}>
            <button className="close" onClick={() => setMemo(null)} aria-label="Close">×</button>
            <div dangerouslySetInnerHTML={{ __html: markdown(memo.markdown) }} />
            {memo.sources.length > 0 && (
              <><h3>Sources</h3><ul>{memo.sources.map((s) => (
                <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>))}</ul></>
            )}
          </article>
        </div>
      )}
    </div>
  )
}

function ReplyDetails({ r, onShow, onMemo, memoBusy, showing }: {
  r: AskReply; onShow: () => void; onMemo: () => void; memoBusy: boolean; showing: boolean
}) {
  return (
    <div className="details">
      {r.highlights.length > 0 && (
        <div className="cards">
          {r.highlights.map((h) => <div key={h.label} className="card"><span>{h.label}</span><b>{String(h.value)}</b></div>)}
        </div>
      )}
      {r.competitors && r.competitors.nearest.length > 0 && (
        <div className="competitors">
          <ol>{r.competitors.nearest.slice(0, 6).map((c) => (
            <li key={c.place_id}>
              <a href={`https://www.google.com/maps/place/?q=place_id:${c.place_id}`} target="_blank" rel="noreferrer">{c.name}</a>
              <span> · {c.distance_m} m{c.rating ? ` · ${c.rating}★ (${c.reviews})` : ''}</span>
            </li>))}
          </ol>
          <span className="credit">Google Maps</span>
        </div>
      )}
      {r.place?.matched && <p className="where">📍 {r.place.matched}</p>}
      {r.sources.length > 0 && (
        <ul className="sources">{r.sources.slice(0, 4).map((s) => (
          <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>))}</ul>
      )}
      {r.audit && (
        <div className="actions">
          <button onClick={onShow} disabled={showing}>{showing ? 'On the map' : 'Show on map'}</button>
          <button onClick={onMemo} disabled={memoBusy}>{memoBusy ? 'Writing memo…' : 'Write a memo'}</button>
          <a href={API + r.audit.files.geojson} download>GeoJSON</a>
          <a href={API + r.audit.files.overlay} target="_blank" rel="noreferrer">Picture</a>
        </div>
      )}
    </div>
  )
}

function Legend({ useCase }: { useCase: string }) {
  const items: Record<string, [string, string][]> = {
    flood: [['#FF1744', 'High flood risk'], ['#FF9100', 'Medium'], ['#00E5FF', 'Low'], ['#2979FF', 'Watercourse'],
            ['#FB8C00', 'Drainage choke point']],
    business_site: [['#E53935', 'Competitor (OpenStreetMap)'], ['#1E88E5', 'Anchor: school, clinic, market, stop'],
                    ['#00E5FF', 'Homes within 500 m']],
    densification: [['#00E5FF', 'Building'], ['#E040FB', 'New since footprint data']],
    solar_minigrid: [['#00E5FF', 'Roof'], ['#00E676', 'Solar panels']],
  }
  return (
    <div className="legend">
      {(items[useCase] ?? []).map(([c, l]) => <div key={l}><i style={{ background: c }} />{l}</div>)}
    </div>
  )
}

function ClickToPin({ onPin }: { onPin: (p: { lat: number; lon: number }) => void }) {
  useMapEvents({ click: (e) => onPin({ lat: e.latlng.lat, lon: e.latlng.lng }) })
  return null
}

function FlyTo({ reply }: { reply: AskReply | null }) {
  const map = useMap()
  useEffect(() => {
    if (reply?.audit) {
      const b = reply.audit.bounds
      map.flyToBounds([[b.south, b.west], [b.north, b.east]], { duration: 1.2 })
    } else if (reply?.place) map.flyTo([reply.place.lat, reply.place.lon], 16)
  }, [reply, map])
  return null
}

function pointLabel(f: Feature) {
  const p = f.properties
  const name = (p.name as string) || (p.place as string) || ''
  const kind = { competitor: 'Competitor', anchor: `Anchor (${p.kind})`, choke_point: 'Drainage choke point',
                 past_flood: `Past flood${p.date ? `, ${p.date}` : ''}` }[String(p.class)]
  return `${kind}${name ? `: ${name}` : ''}${p.distance_m != null ? ` · ${p.distance_m} m` : ''}`
}

// Just enough Markdown for memos: headings, bullets, bold, links. Text is escaped first.
function markdown(md: string) {
  const esc = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  let html = '', inList = false
  for (const line of esc.split('\n')) {
    const item = line.match(/^\s*[-*] (.*)/)
    if (item && !inList) { html += '<ul>'; inList = true }
    if (!item && inList) { html += '</ul>'; inList = false }
    if (item) html += `<li>${inline(item[1])}</li>`
    else if (/^#{1,6} /.test(line)) html += `<h3>${inline(line.replace(/^#+ /, ''))}</h3>`
    else if (line.trim()) html += `<p>${inline(line)}</p>`
  }
  return html + (inList ? '</ul>' : '')
}
