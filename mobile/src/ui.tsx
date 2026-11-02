// Shared look, small components and the English / Kiswahili UI text.
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import type { ReactNode } from 'react';
import type { Lang } from './api';

export const colors = {
  bg: '#F3F6F7', card: '#FFFFFF', ink: '#10202A', muted: '#586A74', line: '#D9E2E6',
  accent: '#0A7684', accentSoft: '#E1F1F3', danger: '#C62828', record: '#D84315',
};

const STATUS_COLORS: Record<string, string> = {
  queued: '#8D6E63', received: '#586A74', unconfirmed: '#B26A00', corroborated: '#1565C0',
  resolved: '#1E7F4F', dismissed: '#586A74',
};

export function StatusChip({ status, lang }: { status: string; lang: Lang }) {
  const color = STATUS_COLORS[status] ?? colors.muted;
  return (
    <View style={[styles.chip, { borderColor: color }]}>
      <Text style={[styles.chipText, { color }]}>{t(lang).status[status] ?? status}</Text>
    </View>
  );
}

export function Button({ title, onPress, kind = 'primary', busy = false, disabled = false }: {
  title: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'danger'; busy?: boolean; disabled?: boolean;
}) {
  const bg = kind === 'primary' ? colors.accent : kind === 'danger' ? colors.danger : colors.card;
  const fg = kind === 'secondary' ? colors.ink : '#fff';
  return (
    <Pressable onPress={onPress} disabled={disabled || busy} accessibilityRole="button"
      style={({ pressed }) => [styles.button, { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.8 : 1 },
        kind === 'secondary' && { borderWidth: 1, borderColor: colors.line }]}>
      {busy ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export const Card = ({ children }: { children: ReactNode }) => <View style={styles.card}>{children}</View>;

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { padding: 16, gap: 12 },
  h1: { fontSize: 24, fontWeight: '800', color: colors.ink },
  h2: { fontSize: 18, fontWeight: '700', color: colors.ink, marginTop: 8 },
  text: { fontSize: 15, color: colors.ink, lineHeight: 21 },
  muted: { fontSize: 13, color: colors.muted },
  row: { flexDirection: 'row', gap: 8, flexWrap: 'wrap', alignItems: 'center' },
  card: { backgroundColor: colors.card, borderRadius: 12, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 8 },
  chip: { borderWidth: 1.5, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 3, alignSelf: 'flex-start' },
  chipText: { fontSize: 12, fontWeight: '700' },
  button: { borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', minHeight: 46 },
  buttonText: { fontSize: 15, fontWeight: '700' },
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 10, padding: 12, fontSize: 15, backgroundColor: '#fff', color: colors.ink },
  photo: { width: 96, height: 96, borderRadius: 8, backgroundColor: colors.line },
});


const en = {
  appTagline: 'Know a place before you build, buy or invest',
  settings: 'Settings', serverUrl: 'Server address', test: 'Test connection', connected: 'Connected',
  done: 'Done',
  tabAsk: 'Ask', tabReport: 'Report',
  chatWelcome: 'Hi! Ask me about any place in Nairobi: Is it a good spot for my business? Can I put solar on this roof? How built-up is it? Does it flood? Name a place, or ask about where you are.',
  chatPlaceholder: 'Ask about a place…', checkHere: '📍 Ask about where I am', checkHereMsg: 'Tell me about this place: is it good to build here?',
  examples: ['Is this a good spot for a pharmacy?', 'Can I put solar panels on this roof?', 'How built-up is Kilimani?', 'Does South C flood?'], thinking: 'Looking at the satellite picture and the data… (up to a minute the first time)',
  thanks: 'Thanks! Your answer helps everyone who lives, builds or buys here.', noLocation: 'Location is off, so I can only check places you name.',
  tapToRecord: 'Tap and say what you see', tapToStop: 'Tap to stop', recordHint: 'Say what is wrong and where, in any language (up to 60 s).',
  play: 'Play back', addPhoto: 'Add photo', retakePhoto: 'Retake photo', send: 'Send report', discard: 'Discard',
  sending: 'Sending…', sent: 'Report sent. Thank you!', savedOffline: 'Saved on your phone. It will send when you are online.',
  rejected: 'The server could not accept a report', micDenied: 'TerraSat needs the microphone to record your report.',
  noGps: 'No GPS fix: the place you mention will be used.',
  myReports: 'My reports', noReports: 'No reports yet.', sendNow: 'Send now', waiting: 'waiting to send',
  error: 'Something went wrong',
  status: {
    queued: 'Waiting for connection', received: 'Received', corroborated: 'Matches flood maps',
    unconfirmed: 'Awaiting review',
    resolved: 'Fixed', dismissed: 'Closed',
  } as Record<string, string>,
};

const sw: typeof en = {
  appTagline: 'Jua eneo kabla ya kujenga, kununua au kuwekeza',
  settings: 'Mipangilio', serverUrl: 'Anwani ya seva', test: 'Jaribu muunganisho', connected: 'Imeunganishwa',
  done: 'Sawa',
  tabAsk: 'Uliza', tabReport: 'Ripoti',
  chatWelcome: 'Habari! Niulize kuhusu eneo lolote Nairobi: Je, ni mahali pazuri kwa biashara yangu? Naweza kuweka sola kwenye paa hili? Pamejengwa kiasi gani? Hufurika? Taja mahali, au uliza kuhusu ulipo.',
  chatPlaceholder: 'Uliza kuhusu eneo…', checkHere: '📍 Uliza kuhusu nilipo', checkHereMsg: 'Niambie kuhusu eneo hili: ni pazuri kujenga hapa?',
  examples: ['Je, hapa ni pazuri kwa duka la dawa?', 'Naweza kuweka sola kwenye paa hili?', 'Kilimani pamejengwa kiasi gani?', 'Je, South C hufurika?'], thinking: 'Ninaangalia picha ya setilaiti na data… (hadi dakika moja mara ya kwanza)',
  thanks: 'Asante! Jibu lako linasaidia kila anayeishi, kujenga au kununua hapa.', noLocation: 'Mahali pako pamezimwa, kwa hiyo naweza kukagua tu maeneo unayotaja.',
  tapToRecord: 'Gusa na useme unachoona', tapToStop: 'Gusa kusimamisha', recordHint: 'Sema tatizo ni nini na liko wapi, kwa lugha yoyote (hadi sekunde 60).',
  play: 'Sikiliza', addPhoto: 'Ongeza picha', retakePhoto: 'Piga picha tena', send: 'Tuma ripoti', discard: 'Futa',
  sending: 'Inatuma…', sent: 'Ripoti imetumwa. Asante!', savedOffline: 'Imehifadhiwa kwenye simu. Itatumwa ukipata mtandao.',
  rejected: 'Seva haikuweza kupokea ripoti', micDenied: 'TerraSat inahitaji maikrofoni kurekodi ripoti yako.',
  noGps: 'Hakuna GPS: mahali utakapotaja patatumika.',
  myReports: 'Ripoti zangu', noReports: 'Bado hakuna ripoti.', sendNow: 'Tuma sasa', waiting: 'zinasubiri kutumwa',
  error: 'Hitilafu imetokea',
  status: {
    queued: 'Inasubiri mtandao', received: 'Imepokelewa', corroborated: 'Inalingana na ramani za mafuriko',
    unconfirmed: 'Inasubiri ukaguzi',
    resolved: 'Imerekebishwa', dismissed: 'Imefungwa',
  },
};

export const strings = { en, sw };
export type Strings = typeof en;
export const t = (lang: Lang): Strings => strings[lang];
