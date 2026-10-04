const liveDialog = document.getElementById('liveDialog');
const liveEl = (id) => document.getElementById(id);
let liveRunning = false;
let livePending = false;
function liveControls() {
  for (const id of ['liveMode', 'liveProfile', 'liveInput', 'liveOutput', 'liveRefresh']) liveEl(id).disabled = liveRunning || livePending;
  liveEl('liveStart').disabled = liveRunning || livePending || !liveEl('liveProfile').value || !liveEl('liveInput').value || !liveEl('liveOutput').value;
  liveEl('liveStop').disabled = !liveRunning;
  liveEl('liveVoiceButton').textContent = liveRunning ? '● 음성 맞춤 중' : 'Vocoflex 자동 설정';
  liveEl('liveStart').textContent = liveEl('liveMode').value === 'standalone' ? '8초 분석 후 Vocoflex에 적용' : '앱 내부 실시간 변환 시작';
}
function liveMessage(message, error = false) {
  liveEl('liveMessage').textContent = message;
  liveEl('liveMessage').classList.toggle('error', error);
}
async function liveRefresh() {
  livePending = true; liveControls();
  try {
    const [catalog, result] = await Promise.all([window.hinana.voiceList(), window.hinana.liveDevices()]);
    const profiles = catalog.profiles.filter((p) => p.referenceHz > 0);
    const previous = liveEl('liveProfile').value;
    liveEl('liveProfile').replaceChildren(...profiles.map((p) => new Option(`${p.name} · 참고 ${Math.round(p.referenceHz)}Hz`, p.id)));
    liveEl('liveProfile').value = profiles.find((p) => p.id === previous)?.id || profiles.find((p) => p.name === '히나나')?.id || profiles[0]?.id || '';
    for (const [id, rows, defaultKey] of [
      ['liveInput', result.devices.filter((d) => d.inputs > 0), 'defaultInput'],
      ['liveOutput', result.devices.filter((d) => d.outputs > 0 && !d.virtual), 'defaultOutput']]) {
      const previousId = liveEl(id).value;
      liveEl(id).replaceChildren(...rows.map((d) => new Option(`${d.name} · ${d.api}`, String(d.id))));
      liveEl(id).value = String(rows.find((d) => String(d.id) === previousId)?.id ?? rows.find((d) => d[defaultKey])?.id ?? rows[0]?.id ?? '');
    }
    if (!profiles.length) liveMessage('음성 프리셋에서 참고 목소리를 먼저 등록해 주세요.', true);
  } catch (error) { liveMessage(error.message, true); }
  finally { livePending = false; liveControls(); }
}
liveEl('liveVoiceButton').addEventListener('click', async () => {
  liveDialog.showModal();
  if (!liveRunning) await liveRefresh();
});
liveEl('liveRefresh').addEventListener('click', liveRefresh);
liveEl('liveMode').addEventListener('change', liveControls);
liveEl('liveStart').addEventListener('click', async () => {
  livePending = true; liveControls(); liveMessage('입력 권한과 장치를 확인하고 있어요…');
  liveEl('liveMatchInfo').textContent = ''; liveEl('liveHealth').textContent = '';
  try {
    await window.hinana.liveStart({ profileId: liveEl('liveProfile').value, standalone: liveEl('liveMode').value === 'standalone',
      inputDevice: Number(liveEl('liveInput').value), outputDevice: Number(liveEl('liveOutput').value) });
    liveRunning = (await window.hinana.liveStatus()).running;
    if (!liveDialog.open) await window.hinana.liveStop();
  } catch (error) { liveMessage(error.message, true); }
  finally { livePending = false; liveControls(); }
});
async function liveStop() {
  if (!liveRunning && !livePending) return;
  liveMessage('입력을 중지하고 있어요…');
  try { await window.hinana.liveStop(); }
  catch (error) { liveMessage(error.message, true); }
  liveRunning = false; livePending = false; liveEl('liveMeter').value = 0; liveControls();
}
liveEl('liveStop').addEventListener('click', liveStop);
liveEl('closeLive').addEventListener('click', () => liveDialog.close());
liveDialog.addEventListener('close', liveStop);
window.hinana.onLiveEvent((event) => {
  if (event.event === 'live_status') {
    liveMessage(event.message + (event.latencyMs ? ` · 장치·변환 지연 약 ${event.latencyMs}ms` : ''));
  } else if (event.event === 'live_level') {
    liveEl('liveMeter').value = event.level;
    if (event.phase === 'calibrating') liveMessage(`입력 분석 중 ${event.seconds}/8초 · 평소 목소리로 말해 주세요.`);
    else liveEl('liveHealth').textContent = `입력 누락 ${event.inputDrops} · 출력 누락 ${event.outputDrops} · 버퍼 부족 ${event.underruns}`;
  } else if (event.event === 'live_match') {
    liveEl('liveMatchInfo').textContent = `입력 ${Math.round(event.inputHz)}Hz → 참고 ${Math.round(event.targetHz)}Hz · 보정 ${event.shift > 0 ? '+' : ''}${event.shift}반음${event.clamped ? ' (보정 범위 한도)' : ''}`;
  } else if (event.event === 'standalone_applied') liveMessage(event.message);
  else if (event.event === 'error') liveMessage(event.message, true);
  else if (event.event === 'live_stopped') liveMessage('실시간 입력과 변환을 중지했습니다.');
  else if (event.event === 'live_ended') { liveRunning = false; liveEl('liveMeter').value = 0; liveControls(); }
});
void window.hinana.liveStatus().then((state) => {
  liveRunning = state.running;
  if (state.last?.message) liveMessage(state.last.message, state.last.event === 'error');
  liveControls();
});
