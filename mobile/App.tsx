// TerraSat mobile: ask about any place, and report what you see on the ground.
import { useEffect, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Pressable, ScrollView, Text, TextInput, useColorScheme, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { api, loadReportTypes, loadSettings, saveSettings, setApiUrl, Settings } from './src/api';
import Chat from './src/Chat';
import { MyReports, RecordReport, useReports } from './src/Resident';
import { Button, Card, IconName, t, ThemeContext, themeFor, useTheme } from './src/ui';

type Tab = 'ask' | 'report' | 'mine';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const system = useColorScheme();
  const theme = themeFor(settings?.theme === 'light' || settings?.theme === 'dark' ? settings.theme
                         : system === 'dark' ? 'dark' : 'light');
  const { c, st } = theme;
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    loadSettings().then((s) => {
      setApiUrl(s.apiUrl);
      setSettings(s);
      loadReportTypes();
    });
  }, []);

  const update = (patch: Partial<Settings>) => {
    const next = { ...settings!, ...patch };
    setApiUrl(next.apiUrl);
    setSettings(next);
    saveSettings(next);
  };

  return (
    <ThemeContext.Provider value={theme}>
    <SafeAreaProvider>
      <SafeAreaView style={[st.screen, { backgroundColor: c.card }]} edges={['top', 'left', 'right', 'bottom']}>
        <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
        {/* "padding" on both platforms: Android draws edge to edge, so the window no longer resizes for
            the keyboard by itself and the text box would sit under it */}
        <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding">
          {!settings ? <ActivityIndicator style={{ flex: 1 }} color={c.brand} />
            : !settings.onboarded ? <Welcome settings={settings} onLang={(lang) => update({ lang })}
                onStart={() => { update({ onboarded: true }); if (!settings.apiUrl) setShowSettings(true) }} />
            : <Main settings={settings} update={update} showSettings={showSettings} setShowSettings={setShowSettings} />}
        </KeyboardAvoidingView>
      </SafeAreaView>
    </SafeAreaProvider>
    </ThemeContext.Provider>
  );
}

function Main({ settings, update, showSettings, setShowSettings }: {
  settings: Settings; update: (p: Partial<Settings>) => void; showSettings: boolean; setShowSettings: (v: boolean) => void;
}) {
  const { c, st, tone, ucLift } = useTheme();
  const s = t(settings.lang);
  const [tab, setTab] = useState<Tab>('ask');
  const store = useReports(settings); // shared by Report and My reports, and keeps the offline queue sending
  const tabs: [Tab, IconName, string][] = [
    ['ask', 'chatbubbles-outline', s.tabAsk], ['report', 'mic-outline', s.tabReport], ['mine', 'list-outline', s.tabMine]];
  return (
    <View style={{ flex: 1 }}>
      <Header settings={settings} onLang={() => update({ lang: settings.lang === 'en' ? 'sw' : 'en' })}
        onSettings={() => setShowSettings(!showSettings)} />
      {showSettings ? <SettingsPanel settings={settings} onChange={update} onClose={() => setShowSettings(false)} /> : (
        <>
          {/* all three stay mounted, so a conversation or a recording survives switching tabs */}
          <View style={{ flex: 1, display: tab === 'ask' ? 'flex' : 'none' }}><Chat settings={settings} /></View>
          <View style={{ flex: 1, display: tab === 'report' ? 'flex' : 'none' }}><RecordReport settings={settings} store={store} /></View>
          <View style={{ flex: 1, display: tab === 'mine' ? 'flex' : 'none' }}><MyReports settings={settings} store={store} /></View>
          <View style={{ flexDirection: 'row', borderTopWidth: 1, borderColor: c.line, backgroundColor: c.card }}>
            {tabs.map(([k, icon, label]) => (
              <Pressable key={k} onPress={() => setTab(k)} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}
                style={{ flex: 1, alignItems: 'center', paddingVertical: 8, gap: 2 }}>
                <Ionicons name={tab === k ? (icon.replace('-outline', '') as IconName) : icon} size={22}
                  color={tab === k ? c.brand : c.muted} />
                <Text style={{ fontSize: 12, fontWeight: tab === k ? '800' : '600', color: tab === k ? c.brand : c.muted }}>
                  {label}{k === 'mine' && store.queue.length ? ` (${store.queue.length})` : ''}
                </Text>
              </Pressable>
            ))}
          </View>
        </>
      )}
    </View>
  );
}

function Header({ settings, onLang, onSettings }: { settings: Settings; onLang: () => void; onSettings: () => void }) {
  const { c, st, tone, ucLift } = useTheme();
  const s = t(settings.lang);
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16,
                   paddingVertical: 10, backgroundColor: c.card, borderBottomWidth: 1, borderColor: c.line }}>
      <View style={[st.row, { flexWrap: 'nowrap', flexShrink: 1 }]}>
        <View style={{ width: 36, height: 36, borderRadius: 10, backgroundColor: c.brand, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="locate" size={22} color={c.onBrand} />
        </View>
        <View style={{ flexShrink: 1 }}>
          <Text style={st.h1}>TerraSat</Text>
          <Text style={st.muted} numberOfLines={1}>{s.appTagline}</Text>
        </View>
      </View>
      <View style={st.row}>
        <Pressable onPress={onLang} accessibilityRole="button" style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 99,
                                                                         backgroundColor: c.brandSoft }}>
          <Text style={{ fontWeight: '800', color: c.brand }}>{settings.lang === 'en' ? 'SW' : 'EN'}</Text>
        </Pressable>
        <Pressable onPress={onSettings} accessibilityRole="button" accessibilityLabel={s.settings} style={{ padding: 6 }}>
          <Ionicons name="settings-outline" size={22} color={c.ink} />
        </Pressable>
      </View>
    </View>
  );
}

function Welcome({ settings, onLang, onStart }: { settings: Settings; onLang: (l: 'en' | 'sw') => void; onStart: () => void }) {
  const { c, st, tone, ucLift } = useTheme();
  const s = t(settings.lang);
  return (
    <ScrollView contentContainerStyle={[st.body, { flexGrow: 1, justifyContent: 'center', gap: 18 }]}>
      <View style={{ width: 64, height: 64, borderRadius: 18, backgroundColor: c.brand, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name="locate" size={38} color={c.onBrand} />
      </View>
      <Text style={[st.h1, { fontSize: 28 }]}>TerraSat</Text>
      <Text style={[st.h2, { marginTop: 0 }]}>{s.welcomeTitle}</Text>
      {([['chatbubbles-outline', s.welcomeAsk], ['mic-outline', s.welcomeReport]] as [IconName, string][]).map(([icon, text]) => (
        <Card key={icon}>
          <View style={[st.row, { flexWrap: 'nowrap', alignItems: 'flex-start' }]}>
            <Ionicons name={icon} size={24} color={c.brand} />
            <Text style={[st.text, { flexShrink: 1 }]}>{text}</Text>
          </View>
        </Card>
      ))}
      <View style={st.row}>
        {(['en', 'sw'] as const).map((l) => (
          <Pressable key={l} onPress={() => onLang(l)} style={{ paddingHorizontal: 14, paddingVertical: 8, borderRadius: 99, borderWidth: 1,
            borderColor: settings.lang === l ? c.brand : c.line, backgroundColor: settings.lang === l ? c.brandSoft : c.card }}>
            <Text style={{ fontWeight: '700', color: settings.lang === l ? c.brand : c.ink }}>{l === 'en' ? 'English' : 'Kiswahili'}</Text>
          </Pressable>
        ))}
      </View>
      <Button title={s.getStarted} icon="arrow-forward" onPress={onStart} />
    </ScrollView>
  );
}

function SettingsPanel({ settings, onChange, onClose }: {
  settings: Settings; onChange: (p: Partial<Settings>) => void; onClose: () => void;
}) {
  const { c, st, tone, ucLift } = useTheme();
  const s = t(settings.lang);
  const [url, setUrl] = useState(settings.apiUrl);
  const [status, setStatus] = useState('');
  const [testing, setTesting] = useState(false);

  async function test() {
    onChange({ apiUrl: url });
    setTesting(true);
    try {
      await api.health();
      setStatus(`✓ ${s.connected}`);
    } catch (e) {
      setStatus(`✗ ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={st.body} keyboardShouldPersistTaps="handled">
      <Text style={st.h2}>{s.settings}</Text>
      <Card>
        <Text style={[st.text, { fontWeight: '700' }]}>{s.language}</Text>
        <View style={st.row}>
          {(['en', 'sw'] as const).map((l) => (
            <Button key={l} kind={settings.lang === l ? 'primary' : 'secondary'} title={l === 'en' ? 'English' : 'Kiswahili'}
              onPress={() => onChange({ lang: l })} />
          ))}
        </View>
      </Card>
      <Card>
        <Text style={[st.text, { fontWeight: '700' }]}>{s.theme}</Text>
        <View style={st.row}>
          {(['system', 'light', 'dark'] as const).map((th, i) => (
            <Button key={th} kind={settings.theme === th ? 'primary' : 'secondary'} title={s.themes[i]}
              icon={(['phone-portrait-outline', 'sunny-outline', 'moon-outline'] as IconName[])[i]} onPress={() => onChange({ theme: th })} />
          ))}
        </View>
      </Card>
      <Card>
        <Text style={[st.text, { fontWeight: '700' }]}>{s.advanced}</Text>
        <Text style={st.muted}>{s.serverUrl}</Text>
        <TextInput style={st.input} value={url} onChangeText={setUrl} autoCapitalize="none" autoCorrect={false}
          keyboardType="url" placeholder="http://192.168.1.20:8000" />
        <Button kind="secondary" icon="pulse-outline" title={s.test} onPress={test} busy={testing} />
        {!!status && <Text style={st.text}>{status}</Text>}
      </Card>
      <Button title={s.done} onPress={() => { onChange({ apiUrl: url }); onClose(); }} />
    </ScrollView>
  );
}
