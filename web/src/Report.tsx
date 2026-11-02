// The site report card shown for every answer, plus the bits around it: use-case styles,
// progress steps while TerraSat works, and the memo modal.
import { useEffect, useState, type ComponentType } from 'react'
import {
  Building2, Check, CloudRain, Copy, Download, Droplets, FileText, Gauge, Grid3x3, Hammer, History, House, Image,
  LandPlot, Layers, LoaderCircle, MapPin, Mountain, Plug, Route, Ruler, Search, ShieldAlert, Sparkles, Star, Store,
  Sun, Trees, Users, Wallet, Waves, X, Zap,
} from 'lucide-react'
import { API, type AskReply, type Memo } from './api'

type Icon = ComponentType<{ size?: number; strokeWidth?: number }>

export const USE_CASES: Record<string, { label: string; color: string; icon: Icon; example: string; blurb: string }> = {
  business_site: { label: 'Business', color: '#4F46E5', icon: Store, example: 'Is Westlands a good spot for a pharmacy?',
                   blurb: 'Competitors, customers within walking distance, anchors and access' },
  solar_minigrid: { label: 'Solar', color: '#D97706', icon: Sun, example: 'Is rooftop solar worth it in Syokimau?',
                    blurb: 'Roof space, sunshine, expected output and payback' },
  densification: { label: 'Density', color: '#7C3AED', icon: Building2, example: 'How built-up is Kilimani, and is there room to build?',
                   blurb: 'Ground coverage, new construction, floors and roads' },
  flood: { label: 'Flood', color: '#2563EB', icon: Waves, example: 'Does South C flood?',
           blurb: 'Risk class, flood history, riparian reserve, what neighbours say' },
}

const TILE_ICONS: Record<string, Icon> = {
  water: Droplets, height: Mountain, reserve: ShieldAlert, flood: Waves, history: History, surface: CloudRain,
  sun: Sun, roof: House, energy: Zap, payback: Wallet, panels: Grid3x3, power: Plug,
  coverage: LandPlot, density: Building2, new: Sparkles, floors: Layers, road: Route, open: Trees,
  competitors: Store, rating: Star, people: Users, ratio: Gauge, anchors: MapPin,
}

const TONES = { good: 'good', mixed: 'mixed', poor: 'poor' } as const

export function placeLabel(r: AskReply) {
  if (!r.place) return 'No place yet'
  if (r.place.matched) return r.place.matched.split(',').slice(0, 2).join(',')
  return r.place.source === 'gps' ? 'Your location' : `Pinned spot · ${r.place.lat.toFixed(4)}, ${r.place.lon.toFixed(4)}`
}

export function SiteReport({ r, question, showing, onShow, onMemo, memoBusy, shareUrl }: {
  r: AskReply; question: string; showing: boolean; onShow: () => void; onMemo: () => void; memoBusy: boolean
  shareUrl: string
}) {
  const uc = USE_CASES[r.use_case]
  const gt = r.ground_truth
  const groundCount = (gt?.reports_nearby.length ?? 0) + Object.keys(gt?.neighbours_say ?? {}).length
  const tabs = [
    { id: 'summary', label: 'Summary' },
    ...(r.competitors?.nearest.length || r.sources.length ? [{ id: 'details', label: 'Details' }] : []),
    ...(gt ? [{ id: 'ground', label: `On the ground${groundCount ? ` (${groundCount})` : ''}` }] : []),
  ]
  const [tab, setTab] = useState('summary')
  const [copied, setCopied] = useState(false)
  const UcIcon = uc?.icon ?? Search

  return (
    <article className="report" style={{ ['--uc' as string]: uc?.color ?? '#0A7684' }}>
      <p className="question">“{question}”</p>
      <header>
        <span className="badge"><UcIcon size={14} />{uc?.label ?? 'General'}</span>
        <h3><MapPin size={16} />{placeLabel(r)}</h3>
        {r.verdict && <span className={`verdict ${TONES[r.verdict.tone]}`}>{r.verdict.label}</span>}
      </header>

      {r.audit && <BeforeAfter before={API + r.audit.files.mosaic} after={API + r.audit.files.overlay} />}

      {r.highlights.length > 0 && (
        <div className="tiles">
          {r.highlights.map((h) => {
            const I = TILE_ICONS[h.icon] ?? Ruler
            return (
              <div key={h.label} className="tile">
                <I size={16} strokeWidth={2.2} />
                <b>{String(h.value)}</b>
                <span>{h.label}</span>
              </div>
            )
          })}
        </div>
      )}

      {tabs.length > 1 && (
        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
      )}
      <div className="tabpanel">
        {tab === 'summary' && <div className="md" dangerouslySetInnerHTML={{ __html: markdown(r.reply) }} />}
        {tab === 'details' && (
          <>
            {r.competitors && r.competitors.nearest.length > 0 && (
              <div className="competitors">
                <h4>Nearest competitors</h4>
                <ol>{r.competitors.nearest.slice(0, 8).map((c) => (
                  <li key={c.place_id}>
                    <a href={`https://www.google.com/maps/place/?q=place_id:${c.place_id}`} target="_blank" rel="noreferrer">{c.name}</a>
                    <span>{c.distance_m} m{c.rating ? ` · ${c.rating}★ (${c.reviews})` : ''}</span>
                  </li>))}
                </ol>
                <span className="credit">Google Maps</span>
              </div>
            )}
            {r.sources.length > 0 && (
              <>
                <h4>Sources</h4>
                <ul className="sources">{r.sources.slice(0, 6).map((s) => (
                  <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>))}</ul>
              </>
            )}
          </>
        )}
        {tab === 'ground' && gt && (
          groundCount === 0 ? <p className="muted">No reports or answers from people here yet. Residents add them from the
            TerraSat phone app.</p> : (
            <>
              {Object.entries(gt.neighbours_say).map(([id, q]) => (
                <div key={id} className="said">
                  <h4>{q.question}</h4>
                  {Object.entries(q.answers).map(([a, n]) => <span key={a} className="answer">{a} × {n}</span>)}
                </div>
              ))}
              {gt.reports_nearby.length > 0 && <h4>Reports within 300 m</h4>}
              <ul className="reports">{gt.reports_nearby.map((x, i) => (
                <li key={i}><b>{x.issue_type.replace(/_/g, ' ')}</b>{x.place ? ` · ${x.place}` : ''}
                  <span>{new Date(x.created_at).toLocaleDateString()} · {x.status}</span></li>))}</ul>
            </>
          )
        )}
      </div>

      {r.audit && (
        <div className="actions">
          <button onClick={onShow} disabled={showing}><Layers size={15} />{showing ? 'On the map' : 'Show on map'}</button>
          <button onClick={onMemo} disabled={memoBusy}>
            {memoBusy ? <LoaderCircle size={15} className="spin" /> : <FileText size={15} />}Memo
          </button>
          <a href={API + r.audit.files.overlay} target="_blank" rel="noreferrer"><Image size={15} />Picture</a>
          <a href={API + r.audit.files.geojson} download><Download size={15} />GeoJSON</a>
          <button onClick={() => { navigator.clipboard?.writeText(shareUrl); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
            {copied ? <Check size={15} /> : <Copy size={15} />}{copied ? 'Copied' : 'Link'}
          </button>
        </div>
      )}
    </article>
  )
}

function BeforeAfter({ before, after }: { before: string; after: string }) {
  const [pos, setPos] = useState(55)
  return (
    <div className="compare" style={{ ['--pos' as string]: `${pos}%` }}>
      <img src={before} alt="Satellite picture" />
      <img src={after} alt="TerraSat analysis" className="after" />
      <span className="lbl left">Satellite</span>
      <span className="lbl right">TerraSat analysis</span>
      <div className="handle" aria-hidden />
      <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))}
        aria-label="Compare the satellite picture with the analysis" />
    </div>
  )
}

const STEPS: [string, Icon, number][] = [
  ['Understanding the question and finding the place', Search, 0],
  ['Getting the satellite picture', Image, 3],
  ['Finding buildings with SAM 3.1', Building2, 9],
  ['Running the analysis on the map data', Hammer, 24],
  ['Writing the answer with Muse Spark', Sparkles, 40],
]

export function Progress() {
  const [t, setT] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setT((x) => x + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const current = STEPS.filter(([, , at]) => t >= at).length - 1
  return (
    <div className="progress" role="status" aria-live="polite">
      {STEPS.map(([label, I], i) => (
        <div key={label} className={i < current ? 'done' : i === current ? 'now' : 'next'}>
          {i < current ? <Check size={15} /> : i === current ? <LoaderCircle size={15} className="spin" /> : <I size={15} />}
          <span>{label}</span>
        </div>
      ))}
      <p className="muted">Repeat questions about the same place come back in seconds.</p>
    </div>
  )
}

export function MemoModal({ memo, onClose }: { memo: Memo; onClose: () => void }) {
  return (
    <div className="modal" role="dialog" aria-modal="true" onClick={onClose}>
      <article onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close"><X size={20} /></button>
        <div dangerouslySetInnerHTML={{ __html: markdown(memo.markdown) }} />
        {memo.sources.length > 0 && (
          <><h3>Sources</h3><ul>{memo.sources.map((s) => (
            <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>))}</ul></>
        )}
      </article>
    </div>
  )
}

// Bullets squeezed onto one line ("Key numbers: - Sunshine: … - Roofs: …") go back onto their own lines.
export function tidy(md: string) {
  return md.split('\n').map((line) => (line.match(/ - /g) ?? []).length < 2 ? line
    : line.replace(/:?\s+-\s+/g, (m) => (m.startsWith(':') ? ':\n- ' : '\n- '))).join('\n')
}

// Just enough Markdown for answers and memos: headings, bullets, bold, links. Text is escaped first.
// In a bullet like "Sunshine: 5.8 kWh/m²/day", the label before the colon is set in bold.
export function markdown(md: string) {
  const esc = tidy(md).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  const label = (s: string) => /^\*\*/.test(s) ? s : s.replace(/^([^:(]{2,40}):\s/, '**$1:** ')
  let html = '', inList = false
  for (const line of esc.split('\n')) {
    const item = line.match(/^\s*[-*•] (.*)/)
    if (item && !inList) { html += '<ul>'; inList = true }
    if (!item && inList) { html += '</ul>'; inList = false }
    if (item) html += `<li>${inline(label(item[1]))}</li>`
    else if (/^#{1,6} /.test(line)) html += `<h3>${inline(line.replace(/^#+ /, ''))}</h3>`
    else if (/^\*\*[^*]+\*\*:?$/.test(line.trim()) || (/:$/.test(line.trim()) && line.trim().length < 50))
      html += `<h4>${line.trim().replace(/\*\*/g, '').replace(/:$/, '')}</h4>`
    else if (line.trim()) html += `<p>${inline(line)}</p>`
  }
  return html + (inList ? '</ul>' : '')
}
