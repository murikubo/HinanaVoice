const voiceDialog = document.querySelector('#voiceDialog');
const voiceElement = (id) => document.getElementById(id);
let voiceCatalog = { profiles: [] };
let voicePending = false;
let voiceSelected = false;
let voiceRegistered = false;
let voiceAnalyzed = false;
let voicePreviewShift = null;

function voiceControls() {
  sendButton.disabled = voicePending || busy || !settings;
  const unavailable = voicePending || busy || !voiceCatalog.available;
  for (const id of ['voiceSelect', 'voiceDisable']) voiceElement(id).disabled = unavailable;
  for (const id of ['voiceListenSaved', 'voiceApply']) voiceElement(id).disabled = unavailable || !voiceElement('voicePreset').value;
  if (voiceCatalog.profiles.find(p => p.id === voiceElement('voicePreset').value)?.targetOnly) {
    voiceElement('voiceApply').disabled = true;
    voiceElement('voiceListenSaved').disabled = true;
  }
  voiceElement('voiceRegister').disabled = unavailable || !voiceSelected;
  voiceElement('voiceAnalyze').disabled = unavailable || !voiceRegistered;
  voiceElement('voicePreview').disabled = unavailable || !voiceAnalyzed;
  voiceElement('voiceSave').disabled = unavailable || voicePreviewShift !== Number(voiceElement('voiceShift').value);
  for (const id of ['voiceShift', 'voiceTestText', 'voicePreset', 'voiceName']) voiceElement(id).disabled = unavailable;
}
function voicePresetInfo() {
  const selected = voiceCatalog.profiles.find((item) => item.id === voiceElement('voicePreset').value);
  voiceElement('voicePresetInfo').textContent = selected
    ? selected.targetOnly ? `자동 보정용 목표 · 참고 ${Math.round(selected.referenceHz)}Hz · Vocoflex 자동 설정에서 선택하세요.`
      : `${selected.narrator} · ${selected.shift > 0 ? '+' : ''}${selected.shift}반음${selected.id === voiceCatalog.activeId ? ' · 대화에 적용 중' : ''}` : '참고 음색을 등록해 첫 프리셋을 만들어 보세요.';
  const active = voiceCatalog.profiles.find((item) => item.id === voiceCatalog.activeId);
  voiceElement('voiceStudioButton').textContent = active ? `목소리 · ${active.name}` : '음성 프리셋';
  voiceControls();
}
async function refreshVoiceCatalog(preferred) {
  voiceCatalog = await window.hinana.voiceList();
  const selection = preferred || voiceElement('voicePreset').value || voiceCatalog.activeId;
  const options = voiceCatalog.profiles.map((item) => new Option(item.name, item.id));
  voiceElement('voicePreset').replaceChildren(...(options.length ? options : [new Option('저장된 프리셋 없음', '')]));
  if (selection && voiceCatalog.profiles.some((item) => item.id === selection)) voiceElement('voicePreset').value = selection;
  voiceElement('voiceNotice').textContent = voiceCatalog.available
    ? '참고 음성은 이 PC에서만 처리합니다. Vocoflex가 설치·활성화되어 있어야 합니다.'
    : 'Vocoflex 변환 도구가 준비되지 않았습니다. Vocoflex와 앱을 다시 설치해 주세요.';
  voicePresetInfo();
}
async function voiceWork(message, task) {
  if (voicePending || busy) return;
  voicePending = true;
  voiceControls();
  voiceElement('voiceMessage').classList.remove('error');
  voiceElement('voiceMessage').textContent = message;
  try { await task(); } catch (error) {
    voiceElement('voiceMessage').textContent = error.message;
    voiceElement('voiceMessage').classList.add('error');
  } finally { voicePending = false; voiceControls(); }
}
voiceElement('voiceStudioButton').addEventListener('click', () => voiceWork('저장된 목소리를 불러오는 중…', async () => {
  await refreshVoiceCatalog(); voiceDialog.showModal(); voiceElement('voiceMessage').textContent = '';
}));
voiceElement('closeVoice').addEventListener('click', () => {
  voiceElement('voiceOriginalAudio').pause(); voiceElement('voicePreviewAudio').pause(); voiceDialog.close();
});
voiceDialog.addEventListener('close', () => { voiceElement('voiceOriginalAudio').pause(); voiceElement('voicePreviewAudio').pause(); });
voiceElement('voicePreset').addEventListener('change', voicePresetInfo);
voiceElement('voiceSelect').addEventListener('click', () => voiceWork('참고 음성 선택 중…', async () => {
  const result = await window.hinana.voiceSelect();
  if (!result) { voiceElement('voiceMessage').textContent = ''; return; }
  voiceSelected = true; voiceRegistered = false; voiceAnalyzed = false; voicePreviewShift = null;
  voiceElement('voiceReferenceName').textContent = result.name;
  voiceElement('voiceAnalysis').textContent = '';
  for (const id of ['voiceOriginalAudio', 'voicePreviewAudio']) { voiceElement(id).pause(); voiceElement(id).removeAttribute('src'); voiceElement(id).load(); }
  voiceElement('voiceMessage').textContent = '다음으로 Vocoflex에 참고 음색을 등록해 주세요.';
}));
voiceElement('voiceRegister').addEventListener('click', () => voiceWork('Vocoflex 등록 창에서 음성을 가져오고 ‘등록 저장’을 눌러 주세요.', async () => {
  await window.hinana.voiceRegister(); voiceRegistered = true; voiceAnalyzed = false; voicePreviewShift = null;
  voiceElement('voiceMessage').textContent = '음색 등록 완료. 이제 음높이를 분석해 주세요.';
}));
voiceElement('voiceAnalyze').addEventListener('click', () => voiceWork('참고 음성과 VOICEPEAK의 음높이를 비교하고 있어요…', async () => {
  const result = await window.hinana.voiceAnalyze(); voiceAnalyzed = true; voicePreviewShift = null;
  voiceElement('voiceShift').value = result.shift;
  voiceElement('voiceOriginalAudio').src = result.originalAudio;
  voiceElement('voiceAnalysis').textContent = `참고 ${Math.round(result.reference.medianHz)}Hz · 원음 ${Math.round(result.input.medianHz)}Hz → ${result.shift > 0 ? '+' : ''}${result.shift}반음${result.clamped ? ' (보정 한도 적용)' : ''}`;
  voiceElement('voiceMessage').textContent = '미리 듣기를 만든 뒤 음높이를 조절해 보세요. 말투와 억양은 입력 음성의 영향을 받습니다.';
}));
voiceElement('voiceShift').addEventListener('input', () => { voicePreviewShift = null; voiceControls(); });
voiceElement('voiceTestText').addEventListener('input', () => { voicePreviewShift = null; voiceControls(); });
voiceElement('voicePreview').addEventListener('click', () => voiceWork('보정된 목소리를 만들고 있어요…', async () => {
  const shift = Number(voiceElement('voiceShift').value);
  const result = await window.hinana.voicePreview({ shift, text: voiceElement('voiceTestText').value });
  voiceElement('voicePreviewAudio').src = result.audio; voicePreviewShift = shift;
  voiceElement('voiceMessage').textContent = `미리 듣기 준비됨 · 출력 음높이 약 ${Math.round(result.pitch.medianHz)}Hz. 마음에 들면 프리셋으로 저장하세요.`;
}));
voiceElement('voiceListenSaved').addEventListener('click', () => voiceWork('저장된 목소리로 테스트 문장을 만들고 있어요…', async () => {
  voicePreviewShift = null;
  const result = await window.hinana.voicePreview({ profileId: voiceElement('voicePreset').value, text: voiceElement('voiceTestText').value });
  voiceElement('voicePreviewAudio').src = result.audio;
  voiceElement('voiceMessage').textContent = `미리 듣기 준비됨 · 약 ${Math.round(result.pitch.medianHz)}Hz`;
}));
voiceElement('voiceSave').addEventListener('click', () => voiceWork('프리셋 저장 중…', async () => {
  const result = await window.hinana.voiceSave({ name: voiceElement('voiceName').value, shift: Number(voiceElement('voiceShift').value) });
  await refreshVoiceCatalog(result.savedId);
  voiceElement('voiceMessage').textContent = '저장했습니다. ‘대화에 적용’을 누르면 이 목소리를 사용합니다.';
}));
for (const [id, apply] of [['voiceApply', true], ['voiceDisable', false]]) voiceElement(id).addEventListener('click', () => voiceWork('목소리 설정 중…', async () => {
  await window.hinana.voiceUse(apply ? voiceElement('voicePreset').value : null);
  settings = await window.hinana.getSettings(); fillSettings(settings); await probe();
  await refreshVoiceCatalog();
  voiceElement('voiceMessage').textContent = apply ? `대화에 적용했습니다. 출력: ${document.querySelector('#device').selectedOptions[0]?.dataset.name || '헤드폰·스피커'}` : '프리셋을 해제했습니다.';
  if (apply && document.querySelector('#device').selectedOptions[0]?.dataset.virtual === 'true') {
    voiceDialog.close();
    settingsMessage.textContent = '프리셋을 적용했습니다. 오디오 출력을 실제 헤드폰이나 스피커로 바꾸고 저장해 주세요.';
    settingsDialog.showModal();
  }
}));
document.querySelector('#settingsForm').addEventListener('submit', () => setTimeout(() => refreshVoiceCatalog().catch(() => {}), 250));
void refreshVoiceCatalog().catch(() => {});
