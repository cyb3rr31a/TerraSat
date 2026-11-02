// Shared look, small components and the English / Kiswahili UI text.
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { createContext, useContext, type ComponentProps, type ReactNode } from 'react';
import { Ionicons } from '@expo/vector-icons';
import type { Lang, Tone } from './api';

export type IconName = ComponentProps<typeof Ionicons>['name'];

// Light and dark palettes. "system" follows the phone's setting.
const light = {
  bg: '#F4F7F8', card: '#FFFFFF', ink: '#0F1F29', muted: '#5B6B75', line: '#DFE6EA', faint: '#B5C1C7',
  brand: '#0A6B76', brandSoft: '#E3F2F3', record: '#D84315', danger: '#C62828', onBrand: '#FFFFFF',
};
const dark: typeof light = {
  bg: '#0E181D', card: '#15232B', ink: '#E5EEF1', muted: '#93A6AF', line: '#263943', faint: '#4F636D',
  brand: '#3FB8BF', brandSoft: '#123338', record: '#FF7043', danger: '#FF8A80', onBrand: '#062126',
};
export type Palette = typeof light;
export type Scheme = 'light' | 'dark';

const TONES: Record<Scheme, Record<Tone, [string, string]>> = {
  light: { good: ['#1B7F4B', '#E3F5EA'], mixed: ['#9A6400', '#FFF3D6'], poor: ['#C62828', '#FDE7E7'] },
  dark: { good: ['#5FD394', '#13321F'], mixed: ['#F2C55C', '#382C10'], poor: ['#FF8A80', '#3B1618'] },
};

// Mix a use-case colour towards white so it stays readable on dark backgrounds.
export function lift(hex: string, amount: number) {
  const n = parseInt(hex.slice(1), 16);
  const mix = (v: number) => Math.round(v + (255 - v) * amount);
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
}

const makeStyles = (c: Palette) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: c.bg },
  body: { padding: 16, gap: 12 },
  h1: { fontSize: 22, fontWeight: '800', color: c.ink, letterSpacing: -0.3 },
  h2: { fontSize: 18, fontWeight: '700', color: c.ink, marginTop: 4 },
  text: { fontSize: 15, color: c.ink, lineHeight: 22 },
  muted: { fontSize: 13, color: c.muted, lineHeight: 18 },
  row: { flexDirection: 'row', gap: 8, flexWrap: 'wrap', alignItems: 'center' },
  card: { backgroundColor: c.card, borderRadius: 16, borderWidth: 1, borderColor: c.line, padding: 14, gap: 10 },
  chip: { borderWidth: 1.5, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 3, alignSelf: 'flex-start' },
  chipText: { fontSize: 12, fontWeight: '700' },
  button: { borderRadius: 12, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', minHeight: 48 },
  buttonText: { fontSize: 15, fontWeight: '700' },
  input: { borderWidth: 1, borderColor: c.line, borderRadius: 12, padding: 12, fontSize: 15, backgroundColor: c.card, color: c.ink },
  photo: { width: 96, height: 96, borderRadius: 10, backgroundColor: c.line },
});

const THEMES = {
  light: { scheme: 'light' as Scheme, c: light, st: makeStyles(light), tone: TONES.light, ucLift: 0 },
  dark: { scheme: 'dark' as Scheme, c: dark, st: makeStyles(dark), tone: TONES.dark, ucLift: 0.35 },
};
export type Theme = (typeof THEMES)['light'];
export const ThemeContext = createContext<Theme>(THEMES.light);
export const themeFor = (scheme: Scheme) => THEMES[scheme];
/** Colours (c), shared styles (st), verdict tones and how much to lighten use-case colours. */
export const useTheme = () => useContext(ThemeContext);

// One colour and icon per analysis, the same as on the web app.
export const USE_CASES: Record<string, { label: [string, string]; color: string; icon: IconName; ask: [string, string] }> = {
  business_site: { label: ['Business', 'Biashara'], color: '#4F46E5', icon: 'storefront-outline',
                   ask: ['Is this a good spot for a pharmacy?', 'Je, hapa ni pazuri kwa duka la dawa?'] },
  solar_minigrid: { label: ['Solar', 'Sola'], color: '#D97706', icon: 'sunny-outline',
                    ask: ['Can I put solar panels on this roof?', 'Naweza kuweka sola kwenye paa hili?'] },
  densification: { label: ['Density', 'Msongamano'], color: '#7C3AED', icon: 'business-outline',
                   ask: ['How built-up is this area, and is there room to build?', 'Eneo hili limejengwa kiasi gani, na kuna nafasi ya kujenga?'] },
  flood: { label: ['Flood', 'Mafuriko'], color: '#2563EB', icon: 'water-outline',
           ask: ['Does this area flood?', 'Je, eneo hili hufurika?'] },
};

export const TILE_ICONS: Record<string, IconName> = {
  water: 'water-outline', height: 'trending-up-outline', reserve: 'shield-outline', flood: 'water-outline',
  history: 'time-outline', surface: 'cloudy-outline', sun: 'sunny-outline', roof: 'home-outline', energy: 'flash-outline',
  payback: 'wallet-outline', panels: 'grid-outline', power: 'flash-outline', coverage: 'map-outline',
  density: 'business-outline', new: 'sparkles-outline', floors: 'layers-outline', road: 'trail-sign-outline',
  open: 'leaf-outline', competitors: 'storefront-outline', rating: 'star-outline', people: 'people-outline',
  ratio: 'speedometer-outline', anchors: 'location-outline',
};

const STATUS_COLORS: Record<string, string> = {
  queued: '#A1887F', received: '#90A4AE', unconfirmed: '#E0A030', corroborated: '#4C8DF0',
  resolved: '#3DAA6E', dismissed: '#90A4AE',
};

export function StatusChip({ status, lang }: { status: string; lang: Lang }) {
  const { st } = useTheme();
  const color = STATUS_COLORS[status] ?? '#90A4AE';
  return (
    <View style={[st.chip, { borderColor: color }]}>
      <Text style={[st.chipText, { color }]}>{t(lang).status[status] ?? status}</Text>
    </View>
  );
}

export function Button({ title, onPress, kind = 'primary', busy = false, disabled = false, icon }: {
  title: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'danger'; busy?: boolean; disabled?: boolean;
  icon?: IconName;
}) {
  const { c, st } = useTheme();
  const bg = kind === 'primary' ? c.brand : kind === 'danger' ? c.danger : c.card;
  const fg = kind === 'secondary' ? c.ink : c.onBrand;
  return (
    <Pressable onPress={onPress} disabled={disabled || busy} accessibilityRole="button"
      style={({ pressed }) => [st.button, { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 },
        kind === 'secondary' && { borderWidth: 1, borderColor: c.line }]}>
      {busy ? <ActivityIndicator color={fg} /> : (
        <View style={st.row}>
          {icon && <Ionicons name={icon} size={18} color={fg} />}
          <Text style={[st.buttonText, { color: fg }]}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

export const Card = ({ children }: { children: ReactNode }) => <View style={useTheme().st.card}>{children}</View>;

// Bullets squeezed onto one line ("Key numbers: - Sunshine: … - Roofs: …") go back onto their own lines.
function tidy(md: string) {
  return md.split('\n').map((line) => ((line.match(/ - /g) ?? []).length < 2 ? line
    : line.replace(/:?\s+-\s+/g, (m) => (m.startsWith(':') ? ':\n- ' : '\n- ')))).join('\n');
}

/** Text with **bold** parts. */
function Inline({ text, style }: { text: string; style: object }) {
  return (
    <Text style={style}>
      {text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
        part.startsWith('**') ? <Text key={i} style={{ fontWeight: '800' }}>{part.slice(2, -2)}</Text> : part)}
    </Text>
  );
}

/** The few bits of Markdown answers use: section headings, bullets ("Label: value" gets a bold label), bold. */
export function Markdown({ text, accent }: { text: string; accent?: string }) {
  const { c, st } = useTheme();
  return (
    <View style={{ gap: 6 }}>
      {tidy(text).split('\n').map((raw, i) => {
        const line = raw.trim();
        if (!line) return null;
        const bullet = line.match(/^[-*•] (.*)/);
        if (bullet) {
          const body = /^\*\*/.test(bullet[1]) ? bullet[1] : bullet[1].replace(/^([^:(]{2,40}):\s/, '**$1:** ');
          return (
            <View key={i} style={{ flexDirection: 'row', gap: 8, backgroundColor: c.bg, borderRadius: 10, padding: 9 }}>
              <View style={{ width: 6, height: 6, borderRadius: 3, marginTop: 8, backgroundColor: accent ?? c.brand }} />
              <View style={{ flex: 1 }}><Inline text={body} style={st.text} /></View>
            </View>
          );
        }
        if (/^#{1,6} /.test(line) || /^\*\*[^*]+\*\*:?$/.test(line) || (line.endsWith(':') && line.length < 50)) {
          return (
            <Text key={i} style={{ fontSize: 12, fontWeight: '800', letterSpacing: 0.6, color: c.muted, marginTop: 6,
                                   textTransform: 'uppercase' }}>
              {line.replace(/^#+ /, '').replace(/\*\*/g, '').replace(/:$/, '')}
            </Text>
          );
        }
        return <Inline key={i} text={line} style={st.text} />;
      })}
    </View>
  );
}

const en = {
  appTagline: 'Know a place before you build, buy or invest',
  welcomeTitle: 'Know a place before you build, buy or invest',
  welcomeAsk: 'Ask about any place: a good spot for a shop? Solar on this roof? Room to build? Does it flood? TerraSat answers from the satellite picture and the map.',
  welcomeReport: 'See something on the ground? Send a voice report in any language. It helps everyone who lives, builds or buys here.',
  getStarted: 'Get started',
  settings: 'Settings', theme: 'Appearance', themes: ['System', 'Light', 'Dark'], language: 'Language', advanced: 'Advanced', serverUrl: 'Server address', test: 'Test connection',
  connected: 'Connected', done: 'Done',
  tabAsk: 'Ask', tabReport: 'Report', tabMine: 'My reports',
  chatWelcome: 'Ask me about any place in Nairobi, or about where you are standing.',
  chatPlaceholder: 'Ask about a place…', checkHereMsg: 'Tell me about this place: is it good to build here?',
  examples: ['Is Westlands a good spot for a pharmacy?', 'Is rooftop solar worth it in Syokimau?', 'How built-up is Kilimani?', 'Does South C flood?'],
  steps: ['Finding the place', 'Getting the satellite picture', 'Finding buildings with SAM 3.1', 'Running the analysis',
          'Writing the answer'],
  repeatFast: 'Repeat questions about the same place come back in seconds.',
  satellite: 'Satellite', analysis: 'Analysis', competitors: 'Nearest competitors',
  thanks: 'Thanks! Your answer helps everyone who lives, builds or buys here.',
  noLocation: 'Location is off, so I can only check places you name.',
  tapToRecord: 'Tap and say what you see', tapToStop: 'Tap to stop', secondsLeft: 's left',
  recordHint: 'Say what is wrong and where, in any language (up to 60 s).',
  play: 'Play back', addPhoto: 'Add photo', retakePhoto: 'Retake photo', send: 'Send report', discard: 'Discard',
  sent: 'Report sent. Thank you!', savedOffline: 'Saved on your phone. It will send when you are online.',
  rejected: 'The server could not accept a report', micDenied: 'TerraSat needs the microphone to record your report.',
  noGps: 'No GPS fix: the place you mention will be used.',
  noReports: 'No reports yet. Send one from the Report tab.', sendNow: 'Send now', waiting: 'waiting to send',
  timeline: ['Received', 'Checked', 'Fixed'],
  error: 'Something went wrong',
  status: {
    queued: 'Waiting for connection', received: 'Received', corroborated: 'Matches the flood maps',
    unconfirmed: 'Awaiting review', resolved: 'Fixed', dismissed: 'Closed',
  } as Record<string, string>,
};

const sw: typeof en = {
  appTagline: 'Jua eneo kabla ya kujenga, kununua au kuwekeza',
  welcomeTitle: 'Jua eneo kabla ya kujenga, kununua au kuwekeza',
  welcomeAsk: 'Uliza kuhusu eneo lolote: ni pazuri kwa duka? Sola kwenye paa hili? Kuna nafasi ya kujenga? Hufurika? TerraSat inajibu kutoka picha ya setilaiti na ramani.',
  welcomeReport: 'Umeona kitu? Tuma ripoti kwa sauti kwa lugha yoyote. Inasaidia kila anayeishi, kujenga au kununua hapa.',
  getStarted: 'Anza',
  settings: 'Mipangilio', theme: 'Mwonekano', themes: ['Kama simu', 'Mwanga', 'Giza'], language: 'Lugha', advanced: 'Kwa wataalamu', serverUrl: 'Anwani ya seva', test: 'Jaribu muunganisho',
  connected: 'Imeunganishwa', done: 'Sawa',
  tabAsk: 'Uliza', tabReport: 'Ripoti', tabMine: 'Ripoti zangu',
  chatWelcome: 'Niulize kuhusu eneo lolote Nairobi, au kuhusu mahali ulipo.',
  chatPlaceholder: 'Uliza kuhusu eneo…', checkHereMsg: 'Niambie kuhusu eneo hili: ni pazuri kujenga hapa?',
  examples: ['Je, Westlands ni pazuri kwa duka la dawa?', 'Je, sola ya paa inafaa Syokimau?', 'Kilimani pamejengwa kiasi gani?', 'Je, South C hufurika?'],
  steps: ['Kutafuta mahali', 'Kupata picha ya setilaiti', 'Kutambua majengo kwa SAM 3.1', 'Kufanya uchambuzi', 'Kuandika jibu'],
  repeatFast: 'Maswali ya mahali palepale hujibiwa kwa sekunde.',
  satellite: 'Setilaiti', analysis: 'Uchambuzi', competitors: 'Washindani wa karibu',
  thanks: 'Asante! Jibu lako linasaidia kila anayeishi, kujenga au kununua hapa.',
  noLocation: 'Mahali pako pamezimwa, kwa hiyo naweza kukagua tu maeneo unayotaja.',
  tapToRecord: 'Gusa na useme unachoona', tapToStop: 'Gusa kusimamisha', secondsLeft: 's zimebaki',
  recordHint: 'Sema tatizo ni nini na liko wapi, kwa lugha yoyote (hadi sekunde 60).',
  play: 'Sikiliza', addPhoto: 'Ongeza picha', retakePhoto: 'Piga picha tena', send: 'Tuma ripoti', discard: 'Futa',
  sent: 'Ripoti imetumwa. Asante!', savedOffline: 'Imehifadhiwa kwenye simu. Itatumwa ukipata mtandao.',
  rejected: 'Seva haikuweza kupokea ripoti', micDenied: 'TerraSat inahitaji maikrofoni kurekodi ripoti yako.',
  noGps: 'Hakuna GPS: mahali utakapotaja patatumika.',
  noReports: 'Bado hakuna ripoti. Tuma moja kutoka kichupo cha Ripoti.', sendNow: 'Tuma sasa', waiting: 'zinasubiri kutumwa',
  timeline: ['Imepokelewa', 'Imekaguliwa', 'Imerekebishwa'],
  error: 'Hitilafu imetokea',
  status: {
    queued: 'Inasubiri mtandao', received: 'Imepokelewa', corroborated: 'Inalingana na ramani za mafuriko',
    unconfirmed: 'Inasubiri ukaguzi', resolved: 'Imerekebishwa', dismissed: 'Imefungwa',
  },
};

export const strings = { en, sw };
export type Strings = typeof en;
export const t = (lang: Lang): Strings => strings[lang];
