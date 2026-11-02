// Ask TerraSat about a place (named, or where you are). Muse Spark picks the analysis, TerraSat runs it on
// the satellite picture there, and each answer comes back as a site report: verdict, numbers, picture.
// People on the spot also get quick tap-to-answer questions.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Image, Linking, Modal, Pressable, ScrollView, ScrollViewInstance, StyleSheet, Text,
  TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { api, AskReply, ChatTurn, fileUrl, newId, Question, Settings } from './api';
import { lift, Markdown, Palette, Strings, t, TILE_ICONS, USE_CASES, useTheme } from './ui';

type Msg = {
  id: string; role: 'user' | 'assistant'; text: string; reply?: AskReply; ask?: Question | null;
  at?: { lat: number; lon: number }; answered?: string; error?: boolean;
};

async function getPosition() {
  const { granted } = await Location.requestForegroundPermissionsAsync();
  if (!granted) return null;
  const fix = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }).catch(() => null);
  return fix ? { lat: fix.coords.latitude, lon: fix.coords.longitude } : null;
}

export default function Chat({ settings }: { settings: Settings }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const s = t(settings.lang);
  const li = settings.lang === 'en' ? 0 : 1;
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState<AskReply | null>(null);
  const scroll = useRef<ScrollViewInstance>(null);
  const tops = useRef<Record<string, number>>({}); // where each message starts, to show a new report from its top

  const add = (m: Msg) => setMsgs((prev) => [...prev, m]);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput('');
    add({ id: newId(), role: 'user', text });
    setBusy(true);
    try {
      const pos = await getPosition(); // used when the question names no place
      if (!pos) add({ id: newId(), role: 'assistant', text: s.noLocation });
      const history: ChatTurn[] = msgs.slice(-6).map(({ role, text }) => ({ role, text }));
      const r = await api.ask({ message: text, lang: settings.lang, device_id: settings.deviceId, history,
                                on_site: !!pos, ...(pos ?? {}) });
      add({ id: newId(), role: 'assistant', text: r.reply, reply: r, ask: r.ask,
            at: r.place ? { lat: r.place.lat, lon: r.place.lon } : undefined });
    } catch (e) {
      add({ id: newId(), role: 'assistant', text: `${s.error}: ${(e as Error).message}`, error: true });
    } finally {
      setBusy(false);
    }
  }

  async function answer(m: Msg, optionId: string, label: string) {
    if (!m.ask || !m.at || m.answered) return;
    setMsgs((prev) => prev.map((x) => (x.id === m.id ? { ...x, answered: optionId } : x)));
    add({ id: newId(), role: 'user', text: label });
    try {
      const r = await api.observe({ question_id: m.ask.id, answer: optionId, ...m.at, device_id: settings.deviceId,
                                    lang: settings.lang });
      add({ id: newId(), role: 'assistant', text: s.thanks, ask: r.next, at: m.at });
    } catch (e) {
      add({ id: newId(), role: 'assistant', text: `${s.error}: ${(e as Error).message}`, error: true });
    }
  }

  return (
    <View style={{ flex: 1 }}>
      <ScrollView ref={scroll} style={st.screen} contentContainerStyle={st.body} keyboardShouldPersistTaps="handled"
        onContentSizeChange={() => { if (!msgs[msgs.length - 1]?.reply) scroll.current?.scrollToEnd({ animated: true }); }}>
        {msgs.length === 0 && (
          <View style={{ gap: 10 }}>
            <Text style={st.h2}>{s.chatWelcome}</Text>
            {s.examples.map((ex) => (
              <Pressable key={ex} onPress={() => send(ex)} style={l.example}>
                <Text style={st.text}>{ex}</Text>
                <Ionicons name="arrow-forward" size={18} color={c.brand} />
              </Pressable>
            ))}
          </View>
        )}
        {msgs.map((m) => m.reply ? (
          <View key={m.id} onLayout={(e) => { // a new report: show it from the top, not the bottom
            const y = e.nativeEvent.layout.y;
            if (tops.current[m.id] === undefined && m.id === msgs[msgs.length - 1].id) {
              scroll.current?.scrollTo({ y: Math.max(0, y - 8), animated: true });
            }
            tops.current[m.id] = y;
          }}>
            <ReportCard r={m.reply} s={s} li={li} onPicture={() => setViewer(m.reply!)} />
          </View>
        ) : (
          <View key={m.id} style={[l.bubble, m.role === 'user' ? l.user : l.bot, m.error && l.err]}>
            <Text style={[st.text, m.role === 'user' && { color: c.onBrand }]}>{m.text}</Text>
          </View>
        )).flatMap((el, i) => {
          const m = msgs[i];
          return m.ask ? [el, (
            <View key={`${m.id}-ask`} style={[l.bubble, l.bot, { gap: 8 }]}>
              <Text style={[st.text, { fontWeight: '700' }]}>{m.ask.text}</Text>
              <View style={st.row}>
                {m.ask.options.map((o) => (
                  <Pressable key={o.id} onPress={() => answer(m, o.id, o.label)} disabled={!!m.answered}
                    style={[l.option, m.answered === o.id && l.optionOn, !!m.answered && m.answered !== o.id && { opacity: 0.4 }]}>
                    <Text style={[l.optionText, m.answered === o.id && { color: c.onBrand }]}>{o.label}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          )] : [el];
        })}
        {busy && <Steps s={s} />}
      </ScrollView>

      <View style={l.composer}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}
          keyboardShouldPersistTaps="handled">
          {Object.entries(USE_CASES).map(([id, u]) => (
            <Pressable key={id} onPress={() => setInput(u.ask[li])} style={l.uchip}>
              <Ionicons name={u.icon} size={15} color={ucLift ? lift(u.color, ucLift) : u.color} />
              <Text style={l.uchipText}>{u.label[li]}</Text>
            </Pressable>
          ))}
        </ScrollView>
        <View style={l.bar}>
          <Pressable onPress={() => send(s.checkHereMsg)} disabled={busy} style={l.iconBtn} accessibilityLabel={s.checkHereMsg}>
            <Ionicons name="navigate-outline" size={22} color={c.brand} />
          </Pressable>
          <TextInput style={[st.input, { flex: 1 }]} value={input} onChangeText={setInput} placeholder={s.chatPlaceholder}
            onSubmitEditing={() => send(input)} returnKeyType="send" editable={!busy} />
          <Pressable onPress={() => send(input)} disabled={busy || !input.trim()} accessibilityLabel="Send"
            style={[l.send, (busy || !input.trim()) && { opacity: 0.45 }]}>
            <Ionicons name="send" size={18} color={c.onBrand} />
          </Pressable>
        </View>
      </View>

      <PictureViewer reply={viewer} s={s} onClose={() => setViewer(null)} />
    </View>
  );
}

function ReportCard({ r, s, li, onPicture }: { r: AskReply; s: Strings; li: number; onPicture: () => void }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const uc = USE_CASES[r.use_case];
  const color = uc ? (ucLift ? lift(uc.color, ucLift) : uc.color) : c.brand;
  const place = r.place?.matched?.split(',').slice(0, 2).join(',') ?? (r.place ? `${r.place.lat.toFixed(4)}, ${r.place.lon.toFixed(4)}` : '');
  return (
    <View style={[st.card, { gap: 12 }]}>
      <View style={{ gap: 6 }}>
        {uc && (
          <View style={[l.badge, { backgroundColor: `${uc.color}${ucLift ? '40' : '1F'}` }]}>
            <Ionicons name={uc.icon} size={13} color={color} />
            <Text style={[l.badgeText, { color }]}>{uc.label[li]}</Text>
          </View>
        )}
        {!!place && (
          <View style={[st.row, { flexWrap: 'nowrap' }]}>
            <Ionicons name="location-outline" size={16} color={c.muted} />
            <Text style={[st.text, { fontWeight: '800', flexShrink: 1 }]} numberOfLines={2}>{place}</Text>
          </View>
        )}
        {r.verdict && (
          <Text style={[l.verdict, { color: tone[r.verdict.tone][0], backgroundColor: tone[r.verdict.tone][1] }]}>
            {r.verdict.label}
          </Text>
        )}
      </View>
      {r.audit && (
        <Pressable onPress={onPicture} accessibilityLabel="Open the picture">
          <Image source={{ uri: fileUrl(r.audit.files.overlay) }} style={l.picture} resizeMode="cover" />
          <View style={l.expand}><Ionicons name="expand-outline" size={16} color="#fff" /></View>
        </Pressable>
      )}
      {r.highlights.length > 0 && (
        <View style={l.tiles}>
          {r.highlights.map((h) => (
            <View key={h.label} style={l.tile}>
              <Ionicons name={TILE_ICONS[h.icon] ?? 'ellipse-outline'} size={16} color={color} />
              <Text style={l.tileValue}>{String(h.value)}</Text>
              <Text style={l.tileLabel}>{h.label}</Text>
            </View>
          ))}
        </View>
      )}
      <Markdown text={r.reply} accent={color} />
      {!!r.competitors?.nearest.length && (
        <View style={{ gap: 3 }}>
          <Text style={[st.text, { fontWeight: '700' }]}>{s.competitors}</Text>
          {r.competitors.nearest.slice(0, 5).map((c) => (
            <Text key={c.place_id} style={st.muted} numberOfLines={1}
              onPress={() => Linking.openURL(`https://www.google.com/maps/place/?q=place_id:${c.place_id}`)}>
              • {c.name} · {c.distance_m} m{c.rating ? ` · ${c.rating}★ (${c.reviews})` : ''}
            </Text>
          ))}
          <Text style={[st.muted, { fontWeight: '700' }]}>Google Maps</Text>
        </View>
      )}
      {r.sources.slice(0, 3).map((src) => (
        <Text key={src.url} style={l.link} onPress={() => Linking.openURL(src.url)} numberOfLines={1}>
          ↗ {src.title || src.url}
        </Text>
      ))}
    </View>
  );
}

function Steps({ s }: { s: Strings }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSecs((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const at = [0, 3, 9, 24, 40];
  const current = at.filter((x) => secs >= x).length - 1;
  return (
    <View style={[st.card, { gap: 8 }]}>
      {s.steps.map((label, i) => (
        <View key={label} style={[st.row, { flexWrap: 'nowrap' }]}>
          {i < current ? <Ionicons name="checkmark-circle" size={18} color={tone.good[0]} />
            : i === current ? <ActivityIndicator size="small" color={c.brand} />
            : <Ionicons name="ellipse-outline" size={18} color={c.faint} />}
          <Text style={[st.text, i > current && { color: c.faint }, i === current && { fontWeight: '700' }]}>{label}</Text>
        </View>
      ))}
      <Text style={st.muted}>{s.repeatFast}</Text>
    </View>
  );
}

function PictureViewer({ reply, s, onClose }: { reply: AskReply | null; s: Strings; onClose: () => void }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const [raw, setRaw] = useState(false);
  if (!reply?.audit) return null;
  return (
    <Modal visible animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <View style={l.viewer}>
        <Image source={{ uri: fileUrl(raw ? reply.audit.files.mosaic : reply.audit.files.overlay) }}
          style={{ width: '100%', aspectRatio: 1 }} resizeMode="contain" />
        <View style={[st.row, { justifyContent: 'center' }]}>
          {[false, true].map((isRaw) => (
            <Pressable key={String(isRaw)} onPress={() => setRaw(isRaw)} style={[l.toggle, raw === isRaw && l.toggleOn]}>
              <Text style={{ color: raw === isRaw ? '#0F1F29' : '#fff', fontWeight: '700' }}>{isRaw ? s.satellite : s.analysis}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable onPress={onClose} style={l.close} accessibilityLabel="Close">
          <Ionicons name="close" size={26} color="#fff" />
        </Pressable>
      </View>
    </Modal>
  );
}

const makeLocal = (c: Palette) => StyleSheet.create({
  example: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, backgroundColor: c.card,
             borderWidth: 1, borderColor: c.line, borderRadius: 14, padding: 14 },
  bubble: { borderRadius: 16, padding: 12, maxWidth: '88%' },
  user: { backgroundColor: c.brand, alignSelf: 'flex-end' },
  bot: { backgroundColor: c.card, borderWidth: 1, borderColor: c.line, alignSelf: 'flex-start' },
  err: { borderColor: c.danger },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start', borderRadius: 99, paddingHorizontal: 10, paddingVertical: 3 },
  badgeText: { fontSize: 12, fontWeight: '800' },
  verdict: { alignSelf: 'flex-start', fontWeight: '800', fontSize: 15, paddingHorizontal: 12, paddingVertical: 5, borderRadius: 10, overflow: 'hidden' },
  picture: { width: '100%', aspectRatio: 1, borderRadius: 12, backgroundColor: c.line },
  expand: { position: 'absolute', right: 8, bottom: 8, backgroundColor: 'rgba(15,31,41,0.6)', borderRadius: 99, padding: 6 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tile: { backgroundColor: c.bg, borderRadius: 12, padding: 10, width: '48%', flexGrow: 1, gap: 2 },
  tileValue: { fontSize: 16, fontWeight: '800', color: c.ink },
  tileLabel: { fontSize: 12, color: c.muted },
  link: { color: c.brand, fontSize: 13 },
  option: { borderWidth: 1.5, borderColor: c.brand, borderRadius: 99, paddingHorizontal: 12, paddingVertical: 7 },
  optionOn: { backgroundColor: c.brand },
  optionText: { color: c.brand, fontWeight: '700' },
  composer: { gap: 8, paddingHorizontal: 10, paddingTop: 8, paddingBottom: 10, borderTopWidth: 1, borderColor: c.line, backgroundColor: c.card },
  uchip: { flexDirection: 'row', alignItems: 'center', gap: 5, borderWidth: 1, borderColor: c.line, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 6 },
  uchipText: { fontSize: 13, fontWeight: '600', color: c.ink },
  bar: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  iconBtn: { padding: 6 },
  send: { backgroundColor: c.brand, width: 46, height: 46, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  viewer: { flex: 1, backgroundColor: '#000', justifyContent: 'center', gap: 16 },
  toggle: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: '#fff' },
  toggleOn: { backgroundColor: '#fff' },
  close: { position: 'absolute', top: 48, right: 16, padding: 6 },
});
