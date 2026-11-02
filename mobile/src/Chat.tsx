// Ask TerraSat about a place (named, or where you are). Muse Spark picks the analysis (business site,
// solar, densification, flood…), TerraSat runs it on the satellite picture there, and answers with a
// verdict, key numbers and the picture. People on the spot get quick tap-to-answer questions.
import { useEffect, useRef, useState } from 'react';
import { Image, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, ScrollViewInstance, StyleSheet, Text,
  TextInput, View } from 'react-native';
import * as Location from 'expo-location';
import { api, AskReply, ChatTurn, fileUrl, newId, Question, Settings } from './api';
import { Button, colors, styles, t } from './ui';

type Msg = {
  id: string; role: 'user' | 'assistant'; text: string; reply?: AskReply; ask?: Question | null;
  at?: { lat: number; lon: number }; answered?: string;
};

async function getPosition() {
  const { granted } = await Location.requestForegroundPermissionsAsync();
  if (!granted) return null;
  const fix = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }).catch(() => null);
  return fix ? { lat: fix.coords.latitude, lon: fix.coords.longitude } : null;
}

export default function Chat({ settings }: { settings: Settings }) {
  const s = t(settings.lang);
  const [msgs, setMsgs] = useState<Msg[]>([{ id: 'hi', role: 'assistant', text: s.chatWelcome }]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scroll = useRef<ScrollViewInstance>(null);

  useEffect(() => { // keep the greeting in the chosen language
    setMsgs((m) => m.map((x) => (x.id === 'hi' ? { ...x, text: s.chatWelcome } : x)));
  }, [s.chatWelcome]);

  const add = (m: Msg) => setMsgs((prev) => [...prev, m]);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput('');
    add({ id: newId(), role: 'user', text });
    setBusy(true);
    try {
      const pos = await getPosition(); // used when the question names no place
      if (!pos) add({ id: newId(), role: 'assistant', text: s.noLocation });
      const history: ChatTurn[] = msgs.filter((m) => m.id !== 'hi').slice(-6).map(({ role, text }) => ({ role, text }));
      const r = await api.ask({ message: text, lang: settings.lang, device_id: settings.deviceId, history,
                                on_site: !!pos, ...(pos ?? {}) });
      add({ id: newId(), role: 'assistant', text: r.reply, reply: r, ask: r.ask,
            at: r.place ? { lat: r.place.lat, lon: r.place.lon } : undefined });
    } catch (e) {
      add({ id: newId(), role: 'assistant', text: `${s.error}: ${(e as Error).message}` });
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
      add({ id: newId(), role: 'assistant', text: `${s.error}: ${(e as Error).message}` });
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView ref={scroll} style={styles.screen} contentContainerStyle={styles.body}
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}>
        {msgs.map((m) => (
          <View key={m.id} style={[local.bubble, m.role === 'user' ? local.user : local.bot]}>
            {m.reply?.use_case_name && <Text style={local.tag}>{m.reply.use_case_name}</Text>}
            {m.reply?.audit && (
              <Image source={{ uri: fileUrl(m.reply.audit.files.overlay) }} style={local.picture} resizeMode="cover" />
            )}
            <Text style={[styles.text, m.role === 'user' && { color: '#fff' }]}>{m.text}</Text>
            {!!m.reply?.highlights.length && (
              <View style={local.grid}>
                {m.reply.highlights.map((h) => (
                  <View key={h.label} style={local.cell}>
                    <Text style={styles.muted}>{h.label}</Text>
                    <Text style={[styles.text, { fontWeight: '800' }]}>{String(h.value)}</Text>
                  </View>
                ))}
              </View>
            )}
            {!!m.reply?.competitors?.nearest.length && (
              <View style={{ gap: 2 }}>
                {m.reply.competitors.nearest.slice(0, 5).map((c) => (
                  <Text key={c.place_id} style={styles.muted} numberOfLines={1}
                    onPress={() => Linking.openURL(`https://www.google.com/maps/place/?q=place_id:${c.place_id}`)}>
                    • {c.name} · {c.distance_m} m{c.rating ? ` · ${c.rating}★ (${c.reviews})` : ''}
                  </Text>
                ))}
                <Text style={[styles.muted, { fontWeight: '700' }]}>Google Maps</Text>
              </View>
            )}
            {m.reply?.place?.matched && <Text style={styles.muted}>📍 {m.reply.place.matched}</Text>}
            {!!m.reply?.sources.length && m.reply.sources.slice(0, 3).map((src) => (
              <Text key={src.url} style={local.link} onPress={() => Linking.openURL(src.url)} numberOfLines={1}>
                ↗ {src.title || src.url}
              </Text>
            ))}
            {m.ask && (
              <View style={{ gap: 8, marginTop: 4 }}>
                <Text style={[styles.text, { fontWeight: '700' }]}>{m.ask.text}</Text>
                <View style={styles.row}>
                  {m.ask.options.map((o) => (
                    <Pressable key={o.id} onPress={() => answer(m, o.id, o.label)} disabled={!!m.answered}
                      style={[local.chip, m.answered === o.id && local.chipOn,
                        !!m.answered && m.answered !== o.id && { opacity: 0.4 }]}>
                      <Text style={[local.chipText, m.answered === o.id && { color: '#fff' }]}>{o.label}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}
          </View>
        ))}
        {busy && <Text style={styles.muted}>{s.thinking}</Text>}
        {msgs.length === 1 && (
          <View style={{ gap: 8 }}>
            {s.examples.map((ex) => <Button key={ex} kind="secondary" title={ex} onPress={() => send(ex)} />)}
          </View>
        )}
      </ScrollView>
      <View style={local.bar}>
        <Pressable onPress={() => send(s.checkHereMsg)} disabled={busy} style={local.pin} accessibilityLabel={s.checkHere}>
          <Text style={{ fontSize: 20 }}>📍</Text>
        </Pressable>
        <TextInput style={[styles.input, { flex: 1 }]} value={input} onChangeText={setInput} placeholder={s.chatPlaceholder}
          onSubmitEditing={() => send(input)} returnKeyType="send" editable={!busy} />
        <Button title="➤" onPress={() => send(input)} disabled={busy || !input.trim()} />
      </View>
    </KeyboardAvoidingView>
  );
}

const local = StyleSheet.create({
  bubble: { borderRadius: 14, padding: 12, gap: 8, maxWidth: '92%' },
  user: { backgroundColor: colors.accent, alignSelf: 'flex-end' },
  bot: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.line, alignSelf: 'flex-start', width: '92%' },
  tag: { alignSelf: 'flex-start', backgroundColor: colors.accentSoft, color: colors.accent, fontWeight: '800',
         fontSize: 12, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 3 },
  picture: { width: '100%', aspectRatio: 1, borderRadius: 10, backgroundColor: colors.line },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  cell: { backgroundColor: colors.bg, borderRadius: 8, padding: 8, minWidth: '46%', flexGrow: 1 },
  link: { color: colors.accent, fontSize: 13 },
  chip: { borderWidth: 1.5, borderColor: colors.accent, borderRadius: 99, paddingHorizontal: 12, paddingVertical: 7 },
  chipOn: { backgroundColor: colors.accent },
  chipText: { color: colors.accent, fontWeight: '700' },
  bar: { flexDirection: 'row', gap: 8, padding: 10, borderTopWidth: 1, borderColor: colors.line, backgroundColor: colors.card,
         alignItems: 'center' },
  pin: { padding: 6 },
});
