// Resident mode: record a voice report (GPS + optional photo), queue it offline, follow its status.
import { useCallback, useEffect, useState } from 'react';
import { Alert, Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import {
  RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioPlayer, useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { api, enqueue, flushQueue, getQueue, mediaUrl, newId, QueuedReport, Report, Settings, typeLabel } from './api';
import { Button, Card, colors, StatusChip, styles, t } from './ui';

const MAX_SECONDS = 60;

async function currentPosition() {
  const { granted } = await Location.requestForegroundPermissionsAsync();
  if (!granted) return null;
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 10000));
  const fix = await Promise.race([Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }), timeout])
    .catch(() => null);
  return fix ?? (await Location.getLastKnownPositionAsync({ maxAge: 10 * 60 * 1000 }));
}

export default function Resident({ settings }: { settings: Settings }) {
  const s = t(settings.lang);
  // 'document' keeps recordings safe until the queue has sent them
  const recorder = useAudioRecorder({ ...RecordingPresets.HIGH_QUALITY, directory: 'document' });
  const recState = useAudioRecorderState(recorder);
  const [audioUri, setAudioUri] = useState<string | null>(null);
  const [photoUri, setPhotoUri] = useState<string | undefined>();
  const player = useAudioPlayer(audioUri);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState('');
  const [reports, setReports] = useState<Report[]>([]);
  const [queue, setQueue] = useState<QueuedReport[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [lastError, setLastError] = useState(''); // why the queue couldn't send, shown on the queue card

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
    const poll = setInterval(refresh, 10000); // see status changes from the dashboard
    return () => { stop(); clearInterval(poll); };
  }, [refresh, flush]);

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
      const sent = await flush();
      setMessage((sent ? s.sent : s.savedOffline) + (pos ? '' : `\n${s.noGps}`));
      await refresh();
    } finally {
      setSending(false);
    }
  }

  const seconds = Math.round(recState.durationMillis / 1000);
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.body}
      refreshControl={<RefreshControl refreshing={refreshing}
        onRefresh={async () => { setRefreshing(true); await flush(); await refresh(); setRefreshing(false); }} />}>
      <Card>
        <Pressable onPress={recState.isRecording ? stopRecording : startRecording} accessibilityRole="button"
          accessibilityLabel={recState.isRecording ? s.tapToStop : s.tapToRecord}
          style={[local.mic, recState.isRecording && local.micOn]}>
          <Text style={local.micIcon}>{recState.isRecording ? '■' : '●'}</Text>
          <Text style={local.micText}>
            {recState.isRecording ? `${s.tapToStop}  ${seconds}s / ${MAX_SECONDS}s` : s.tapToRecord}
          </Text>
        </Pressable>
        <Text style={styles.muted}>{s.recordHint}</Text>

        {audioUri && !recState.isRecording && (
          <View style={{ gap: 10 }}>
            <View style={styles.row}>
              <Button kind="secondary" title={`▶ ${s.play}`} onPress={() => { player.seekTo(0); player.play(); }} />
              <Button kind="secondary" title={photoUri ? s.retakePhoto : s.addPhoto} onPress={takePhoto} />
            </View>
            {photoUri && <Image source={{ uri: photoUri }} style={styles.photo} />}
            <Button title={s.send} onPress={send} busy={sending} />
            <Button kind="secondary" title={s.discard} onPress={() => { setAudioUri(null); setPhotoUri(undefined); }} />
          </View>
        )}
        {!!message && <Text style={[styles.text, { color: colors.accent, fontWeight: '700' }]}>{message}</Text>}
      </Card>

      <Text style={styles.h2}>{s.myReports}</Text>
      {queue.length > 0 && (
        <Card>
          <StatusChip status="queued" lang={settings.lang} />
          <Text style={styles.text}>{queue.length} {s.waiting}</Text>
          {!!lastError && <Text style={styles.muted}>{lastError}</Text>}
          <Button kind="secondary" title={s.sendNow} onPress={flush} />
        </Card>
      )}
      {reports.length === 0 && queue.length === 0 && <Text style={styles.muted}>{s.noReports}</Text>}
      {reports.map((r) => (
        <Card key={r.id}>
          <View style={[styles.row, { justifyContent: 'space-between' }]}>
            <Text style={[styles.text, { fontWeight: '700' }]}>
              {typeLabel(r.issue_type, settings.lang)}{r.place ? ` · ${r.place}` : ''}
            </Text>
            <StatusChip status={r.status} lang={settings.lang} />
          </View>
          <Text style={styles.text}>{(settings.lang === 'sw' ? r.summary_sw : r.summary_en) ?? r.transcript}</Text>
          <Text style={styles.muted}>{new Date(r.created_at).toLocaleString()}</Text>
          {r.photo_path && <Image source={{ uri: mediaUrl(r.photo_path) }} style={styles.photo} />}
        </Card>
      ))}
    </ScrollView>
  );
}

const local = StyleSheet.create({
  mic: { backgroundColor: colors.accent, borderRadius: 16, paddingVertical: 28, alignItems: 'center', gap: 6 },
  micOn: { backgroundColor: colors.record },
  micIcon: { color: '#fff', fontSize: 40, lineHeight: 44 },
  micText: { color: '#fff', fontSize: 17, fontWeight: '700' },
});
