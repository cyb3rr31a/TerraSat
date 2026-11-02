// TerraSat mobile: ask about any place, and report what you see on the ground.
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { api, loadReportTypes, loadSettings, saveSettings, setApiUrl, Settings } from './src/api';
import Chat from './src/Chat';
import Resident from './src/Resident';
import { Button, colors, styles, t } from './src/ui';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    loadSettings().then((s) => {
      setApiUrl(s.apiUrl);
      setSettings(s);
      loadReportTypes();
      setShowSettings(!s.apiUrl);
    });
  }, []);

  const update = (patch: Partial<Settings>) => {
    const next = { ...settings!, ...patch };
    setApiUrl(next.apiUrl);
    setSettings(next);
    saveSettings(next);
  };

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.screen} edges={['top', 'left', 'right']}>
        <StatusBar style="dark" />
        {!settings ? <ActivityIndicator style={{ flex: 1 }} color={colors.accent} /> : (
          <>
            <Header settings={settings} onLang={() => update({ lang: settings.lang === 'en' ? 'sw' : 'en' })}
              onSettings={() => setShowSettings(!showSettings)} />
            {showSettings ? <SettingsPanel settings={settings} onChange={update} onClose={() => setShowSettings(false)} />
              : <Tabs settings={settings} />}
          </>
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

function Tabs({ settings }: { settings: Settings }) {
  const s = t(settings.lang);
  const [tab, setTab] = useState<'ask' | 'report'>('ask');
  return (
    <View style={{ flex: 1 }}>
      <View style={[styles.row, { padding: 8, gap: 8, backgroundColor: colors.card }]}>
        {(['ask', 'report'] as const).map((k) => (
          <Pressable key={k} onPress={() => setTab(k)} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}
            style={{ flex: 1, paddingVertical: 9, borderRadius: 99, alignItems: 'center',
                     backgroundColor: tab === k ? colors.ink : colors.bg }}>
            <Text style={{ fontWeight: '700', color: tab === k ? '#fff' : colors.ink }}>
              {k === 'ask' ? s.tabAsk : s.tabReport}
            </Text>
          </Pressable>
        ))}
      </View>
      {/* both stay mounted so a recording or a conversation survives switching tabs */}
      <View style={{ flex: 1, display: tab === 'ask' ? 'flex' : 'none' }}><Chat settings={settings} /></View>
      <View style={{ flex: 1, display: tab === 'report' ? 'flex' : 'none' }}><Resident settings={settings} /></View>
    </View>
  );
}

function Header({ settings, onLang, onSettings }: { settings: Settings; onLang: () => void; onSettings: () => void }) {
  const s = t(settings.lang);
  return (
    <View style={[styles.row, { paddingHorizontal: 16, paddingVertical: 10, justifyContent: 'space-between',
      borderBottomWidth: 1, borderColor: colors.line, backgroundColor: colors.card }]}>
      <View>
        <Text style={styles.h1}>TerraSat</Text>
        <Text style={styles.muted}>{s.appTagline}</Text>
      </View>
      <View style={styles.row}>
        <Pressable onPress={onLang} accessibilityRole="button" style={{ padding: 8 }}>
          <Text style={{ fontWeight: '800', color: colors.accent }}>{settings.lang === 'en' ? 'SW' : 'EN'}</Text>
        </Pressable>
        <Pressable onPress={onSettings} accessibilityRole="button" accessibilityLabel={s.settings} style={{ padding: 8 }}>
          <Text style={{ fontSize: 20 }}>⚙</Text>
        </Pressable>
      </View>
    </View>
  );
}

function SettingsPanel({ settings, onChange, onClose }: {
  settings: Settings; onChange: (p: Partial<Settings>) => void; onClose: () => void;
}) {
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
    <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
      <Text style={styles.h2}>{s.settings}</Text>
      <Text style={styles.muted}>{s.serverUrl}</Text>
      <TextInput style={styles.input} value={url} onChangeText={setUrl} autoCapitalize="none" autoCorrect={false}
        keyboardType="url" placeholder="http://192.168.1.20:8000" />
      <Button kind="secondary" title={s.test} onPress={test} busy={testing} />
      {!!status && <Text style={styles.text}>{status}</Text>}
      <Button title={s.done} onPress={() => { onChange({ apiUrl: url }); onClose(); }} />
    </ScrollView>
  );
}
