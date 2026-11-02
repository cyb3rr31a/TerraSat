// Voice reports: record what you see (GPS + optional photo), keep it on the phone until it sends,
// and follow each report's status. `useReports` is shared by the Report and My reports tabs.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Animated, Easing, Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import {
  RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioPlayer, useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { api, enqueue, flushQueue, getQueue, mediaUrl, newId, QueuedReport, Report, Settings, typeLabel } from './api';
import { Button, Card, Palette, StatusChip, t, useTheme } from './ui';

const MAX_SECONDS = 60;

async function currentPosition() {
  const { granted } = await Location.requestForegroundPermissionsAsync();
  if (!granted) return null;
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 10000));
  const fix = await Promise.race([Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }), timeout])
    .catch(() => null);
  return fix ?? (await Location.getLastKnownPositionAsync({ maxAge: 10 * 60 * 1000 }));
}

/** The phone's reports and offline queue. Sends queued reports whenever the connection comes back. */
export function useReports(settings: Settings) {
  const s = t(settings.lang);
  const [reports, setReports] = useState<Report[]>([]);
  const [queue, setQueue] = useState<QueuedReport[]>([]);
  const [lastError, setLastError] = useState(''); // why the queue couldn't send

  const refresh = useCallback(async () => {
    setQueue(await getQueue());
    try {
      setReports(await api.myReports(settings.deviceId));
    } catch {
      // offline: keep showing the last list
    }
  }, [settings.deviceId]);

  const flush = useCallback(async () => {
    const { sent, rejected, error } = await flushQueue(settings.deviceId);
    setLastError(error ?? '');
    if (rejected.length) Alert.alert(s.rejected, rejected.join('\n'));
    if (sent || rejected.length) await refresh();
    return sent;
  }, [settings.deviceId, refresh, s.rejected]);

  useEffect(() => {
    refresh();
    flush();
    const stop = NetInfo.addEventListener((state) => { if (state.isConnected) flush(); });
    const poll = setInterval(refresh, 15000); // status changes made on the server
    return () => { stop(); clearInterval(poll); };
  }, [refresh, flush]);

  return { reports, queue, lastError, refresh, flush };
}
export type ReportsState = ReturnType<typeof useReports>;

export function RecordReport({ settings, store }: { settings: Settings; store: ReportsState }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const s = t(settings.lang);
  // 'document' keeps recordings safe until the queue has sent them
  const recorder = useAudioRecorder({ ...RecordingPresets.HIGH_QUALITY, directory: 'document' });
  const recState = useAudioRecorderState(recorder);
  const [audioUri, setAudioUri] = useState<string | null>(null);
  const [photoUri, setPhotoUri] = useState<string | undefined>();
  const player = useAudioPlayer(audioUri);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState('');
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => { // a ring that pulses while recording
    if (!recState.isRecording) { pulse.stopAnimation(); pulse.setValue(0); return; }
    const loop = Animated.loop(Animated.timing(pulse, { toValue: 1, duration: 1400, easing: Easing.out(Easing.ease), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [recState.isRecording, pulse]);

  useEffect(() => { // the 60 s limit stopped the recorder by itself
    if (!recState.isRecording && recorder.uri && !audioUri && recState.durationMillis > 0) setAudioUri(recorder.uri);
  }, [recState.isRecording]); // eslint-disable-line react-hooks/exhaustive-deps

  async function startRecording() {
    const { granted } = await requestRecordingPermissionsAsync();
    if (!granted) return Alert.alert(s.micDenied);
    await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
    setMessage('');
    setAudioUri(null);
    setPhotoUri(undefined);
    await recorder.prepareToRecordAsync();
    recorder.record({ forDuration: MAX_SECONDS });
  }

  async function stopRecording() {
    await recorder.stop();
    await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }); // so playback is loud
    setAudioUri(recorder.uri);
  }

  async function takePhoto() {
    const { granted } = await ImagePicker.requestCameraPermissionsAsync();
    if (!granted) return;
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.5 });
    if (!res.canceled) setPhotoUri(res.assets[0].uri);
  }

  async function send() {
    if (!audioUri) return;
    setSending(true);
    try {
      const pos = await currentPosition();
      await enqueue({
        clientId: newId(), createdAt: new Date().toISOString(), audioUri, photoUri,
        lat: pos?.coords.latitude, lon: pos?.coords.longitude, accuracy: pos?.coords.accuracy,
      });
      setAudioUri(null);
      setPhotoUri(undefined);
      const sent = await store.flush();
      setMessage((sent ? s.sent : s.savedOffline) + (pos ? '' : `\n${s.noGps}`));
      await store.refresh();
    } finally {
      setSending(false);
    }
  }

  const left = MAX_SECONDS - Math.round(recState.durationMillis / 1000);
  const ring = {
    opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] }),
    transform: [{ scale: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] }) }],
  };
  return (
    <ScrollView style={st.screen} contentContainerStyle={[st.body, { alignItems: 'stretch' }]}>
      <View style={l.stage}>
        <Animated.View style={[l.ring, ring]} />
        <Pressable onPress={recState.isRecording ? stopRecording : startRecording} accessibilityRole="button"
          accessibilityLabel={recState.isRecording ? s.tapToStop : s.tapToRecord}
          style={({ pressed }) => [l.mic, recState.isRecording && l.micOn, pressed && { transform: [{ scale: 0.96 }] }]}>
          <Ionicons name={recState.isRecording ? 'stop' : 'mic'} size={56} color={c.onBrand} />
          {recState.isRecording && <Text style={l.count}>{left}{s.secondsLeft}</Text>}
        </Pressable>
        <Text style={[st.h2, { textAlign: 'center' }]}>{recState.isRecording ? s.tapToStop : s.tapToRecord}</Text>
        <Text style={[st.muted, { textAlign: 'center' }]}>{s.recordHint}</Text>
      </View>

      {audioUri && !recState.isRecording && (
        <Card>
          <View style={st.row}>
            <Button kind="secondary" icon="play" title={s.play} onPress={() => { player.seekTo(0); player.play(); }} />
            <Button kind="secondary" icon="camera-outline" title={photoUri ? s.retakePhoto : s.addPhoto} onPress={takePhoto} />
          </View>
          {photoUri && <Image source={{ uri: photoUri }} style={st.photo} />}
          <Button icon="send" title={s.send} onPress={send} busy={sending} />
          <Button kind="secondary" title={s.discard} onPress={() => { setAudioUri(null); setPhotoUri(undefined); }} />
        </Card>
      )}
      {!!message && <Text style={[st.text, { color: c.brand, fontWeight: '700', textAlign: 'center' }]}>{message}</Text>}
    </ScrollView>
  );
}

const STEP = { received: 0, unconfirmed: 0, corroborated: 1, resolved: 2, dismissed: 1 } as Record<string, number>;

export function MyReports({ settings, store }: { settings: Settings; store: ReportsState }) {
  const { c, st, tone, ucLift } = useTheme();
  const l = useMemo(() => makeLocal(c), [c]);
  const s = t(settings.lang);
  const [refreshing, setRefreshing] = useState(false);
  return (
    <ScrollView style={st.screen} contentContainerStyle={st.body}
      refreshControl={<RefreshControl refreshing={refreshing}
        onRefresh={async () => { setRefreshing(true); await store.flush(); await store.refresh(); setRefreshing(false); }} />}>
      {store.queue.length > 0 && (
        <Card>
          <StatusChip status="queued" lang={settings.lang} />
          <Text style={st.text}>{store.queue.length} {s.waiting}</Text>
          {!!store.lastError && <Text style={st.muted}>{store.lastError}</Text>}
          <Button kind="secondary" icon="cloud-upload-outline" title={s.sendNow} onPress={store.flush} />
        </Card>
      )}
      {store.reports.length === 0 && store.queue.length === 0 && <Text style={st.muted}>{s.noReports}</Text>}
      {store.reports.map((r) => {
        const step = STEP[r.status] ?? 0;
        return (
          <Card key={r.id}>
            <View style={[st.row, { justifyContent: 'space-between', flexWrap: 'nowrap' }]}>
              <Text style={[st.text, { fontWeight: '800', flexShrink: 1 }]}>
                {typeLabel(r.issue_type, settings.lang)}{r.place ? ` · ${r.place}` : ''}
              </Text>
              <StatusChip status={r.status} lang={settings.lang} />
            </View>
            <Text style={st.text}>{(settings.lang === 'sw' ? r.summary_sw : r.summary_en) ?? r.transcript}</Text>
            <View style={l.timeline}>
              {s.timeline.map((label, i) => (
                <View key={label} style={l.tstep}>
                  <View style={[l.dot, i <= step && l.dotOn]} />
                  <Text style={[st.muted, i <= step && { color: c.ink, fontWeight: '700' }]}>{label}</Text>
                </View>
              ))}
            </View>
            <View style={[st.row, { justifyContent: 'space-between' }]}>
              <Text style={st.muted}>{new Date(r.created_at).toLocaleString()}</Text>
              {r.photo_path && <Image source={{ uri: mediaUrl(r.photo_path) }} style={{ width: 56, height: 56, borderRadius: 8 }} />}
            </View>
          </Card>
        );
      })}
    </ScrollView>
  );
}

const makeLocal = (c: Palette) => StyleSheet.create({
  stage: { alignItems: 'center', gap: 12, paddingVertical: 28 },
  ring: { position: 'absolute', top: 28, width: 168, height: 168, borderRadius: 84, backgroundColor: c.record },
  mic: { width: 168, height: 168, borderRadius: 84, backgroundColor: c.brand, alignItems: 'center', justifyContent: 'center',
         elevation: 6, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 10, shadowOffset: { width: 0, height: 4 } },
  micOn: { backgroundColor: c.record },
  count: { color: c.onBrand, fontWeight: '800', marginTop: 2 },
  timeline: { flexDirection: 'row', justifyContent: 'space-between', gap: 6 },
  tstep: { flex: 1, alignItems: 'center', gap: 4 },
  dot: { width: 12, height: 12, borderRadius: 6, backgroundColor: c.line },
  dotOn: { backgroundColor: c.brand },
});
