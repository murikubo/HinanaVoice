const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

class VoiceStudio {
  constructor({ root, hostPath, runBackend, seedDirectory }) {
    this.root = root;
    this.hostPath = hostPath;
    this.runBackend = runBackend;
    this.seedDirectory = seedDirectory;
    this.job = null;
    this.busy = false;
    this.children = new Set();
    fs.mkdirSync(root, { recursive: true });
  }
  readJSON(file, fallback = null) {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; }
  }
  writeJSON(file, data) {
    fs.writeFileSync(`${file}.tmp`, JSON.stringify(data, null, 2));
    fs.renameSync(`${file}.tmp`, file);
  }
  profile(id) {
    if (!/^[0-9a-f-]{36}$/.test(id || '')) throw new Error('프리셋을 선택해 주세요.');
    const directory = path.join(this.root, id);
    const profile = this.readJSON(path.join(directory, 'profile.json'));
    if (!profile || !fs.existsSync(path.join(directory, 'voice.aupreset'))) throw new Error('프리셋 파일을 찾지 못했습니다.');
    return { ...profile, statePath: path.join(directory, 'voice.aupreset'), hostPath: this.hostPath };
  }
  active() {
    const id = this.readJSON(path.join(this.root, 'preferences.json'), {}).activeId;
    return id ? this.profile(id) : null;
  }
  list() {
    const profiles = fs.readdirSync(this.root).filter((id) => /^[0-9a-f-]{36}$/.test(id))
      .map((id) => this.readJSON(path.join(this.root, id, 'profile.json'))).filter(Boolean);
    const activeId = this.readJSON(path.join(this.root, 'preferences.json'), {}).activeId || null;
    return { available: process.platform === 'darwin' && fs.existsSync(this.hostPath), profiles, activeId };
  }
  use(id) {
    if (this.busy) throw new Error('음성 작업이 끝난 뒤 프리셋을 적용해 주세요.');
    if (id) this.profile(id);
    this.writeJSON(path.join(this.root, 'preferences.json'), { activeId: id || null });
    return this.list();
  }
  async locked(work) {
    if (this.busy) throw new Error('음성 작업이 진행 중입니다. 완료된 뒤 다시 시도해 주세요.');
    this.busy = true;
    try { return await work(); } finally { this.busy = false; }
  }
  selectReference(referencePath, settings) {
    if (this.busy) throw new Error('현재 음성 작업이 끝난 뒤 참고 음성을 변경해 주세요.');
    if (fs.statSync(referencePath).size > 150 * 1024 * 1024) throw new Error('참고 파일은 150MB 이하로 선택해 주세요.');
    const directory = path.join(this.root, 'jobs', crypto.randomUUID());
    fs.mkdirSync(directory, { recursive: true });
    this.job = { directory, referencePath, statePath: path.join(directory, 'voice.aupreset'),
      settings: { voicepeak: settings.voicepeak, narrator: settings.narrator, speed: settings.speed, pitch: settings.pitch } };
    return { name: path.basename(referencePath) };
  }
  async backend(request) {
    const operation = this.runBackend(request);
    if (operation.child) this.children.add(operation.child);
    try { return await operation; } finally { if (operation.child) this.children.delete(operation.child); }
  }
  async register() {
    return this.locked(async () => {
      const job = this.job;
      if (!job) throw new Error('먼저 참고 음성을 선택해 주세요.');
      if (!fs.existsSync(this.hostPath)) throw new Error('macOS용 Vocoflex 변환 도구가 필요합니다.');
      const registrationPath = path.join(job.directory, `${crypto.randomUUID()}.aupreset`);
      await new Promise((resolve, reject) => {
        const child = spawn(this.hostPath, ['--editor', '--reference', job.referencePath,
          '--finish-on-save', '--save-state', registrationPath], { stdio: ['ignore', 'ignore', 'pipe'] });
        this.children.add(child);
        let error = '';
        child.stderr.on('data', (data) => { error = (error + data).slice(-4000); });
        child.on('error', reject);
        child.on('close', (code) => { this.children.delete(child); code === 0 ? resolve() : reject(new Error(error || 'Vocoflex 등록 창이 종료되었습니다.')); });
      });
      if (!fs.existsSync(registrationPath)) throw new Error('등록이 취소되었습니다. 음색을 등록하고 ‘등록 저장’을 눌러 주세요.');
      fs.renameSync(registrationPath, job.statePath);
      return { registered: true };
    });
  }
  async analyze() {
    return this.locked(async () => {
      const job = this.job;
      if (!job || !fs.existsSync(job.statePath)) throw new Error('먼저 Vocoflex에 참고 음색을 등록해 주세요.');
      const result = await this.backend({ action: 'voice_analyze', ...job.settings,
        referencePath: job.referencePath, outputDir: path.join(job.directory, 'analysis') });
      job.analysis = result;
      job.previewedShift = null;
      return { ...result, originalAudio: this.audio(result.inputPath) };
    });
  }
  audio(file) {
    const bytes = fs.readFileSync(file);
    if (bytes.length > 12 * 1024 * 1024) throw new Error('미리 듣기 음성이 너무 깁니다. 문장을 짧게 줄여 주세요.');
    return `data:audio/wav;base64,${bytes.toString('base64')}`;
  }
  async preview({ shift, text, profileId } = {}) {
    return this.locked(async () => {
      const profile = profileId ? this.profile(profileId) : null;
      const job = this.job;
      if (!profile && (!job?.analysis || !fs.existsSync(job.statePath))) throw new Error('먼저 참고 음성을 등록하고 분석해 주세요.');
      const amount = Number(shift ?? profile?.shift ?? job.analysis.shift);
      if (!Number.isFinite(amount) || Math.abs(amount) > 12) throw new Error('음높이는 -12~12반음으로 설정해 주세요.');
      const outputDir = path.join(this.root, 'jobs', crypto.randomUUID());
      const settings = profile || job.settings;
      const result = await this.backend({ action: 'voice_preview', ...settings, shift: amount, text,
        statePath: profile?.statePath || job.statePath, hostPath: this.hostPath, outputDir });
      if (!profile) job.previewedShift = amount;
      return { ...result, audio: this.audio(result.path) };
    });
  }
  save({ name, shift }) {
    if (this.busy) throw new Error('미리 듣기가 끝난 뒤 저장해 주세요.');
    const job = this.job;
    if (!job?.analysis || job.previewedShift !== Number(shift)) throw new Error('이 보정값으로 먼저 미리 듣기를 만들어 주세요.');
    const id = crypto.randomUUID();
    const directory = path.join(this.root, id);
    fs.mkdirSync(directory);
    fs.copyFileSync(job.statePath, path.join(directory, 'voice.aupreset'));
    const profile = { id, name: String(name || '내 목소리').trim().slice(0, 60) || '내 목소리',
      shift: Number(shift), ...job.settings, referenceName: path.basename(job.referencePath),
      referenceHz: job.analysis.reference.medianHz, inputHz: job.analysis.input.medianHz };
    this.writeJSON(path.join(directory, 'profile.json'), profile);
    return { ...this.list(), savedId: id };
  }
  seed() {
    // Only the user's local development artifacts are imported. They are never bundled.
    if (!this.seedDirectory || this.list().profiles.length) return;
    const state = path.join(this.seedDirectory, 'matched.aupreset');
    const report = this.readJSON(path.join(this.seedDirectory, 'pitch-match.json'));
    if (!fs.existsSync(state) || !report) return;
    const id = crypto.randomUUID();
    const directory = path.join(this.root, id);
    fs.mkdirSync(directory);
    fs.copyFileSync(state, path.join(directory, 'voice.aupreset'));
    this.writeJSON(path.join(directory, 'profile.json'), { id, name: '히나나',
      shift: report.applied_centre_semitones, narrator: 'Koharu Rikka', speed: 95, pitch: 0,
      referenceName: path.basename(report.reference), referenceHz: report.reference_pitch.median_hz,
      inputHz: report.input_pitch.median_hz });
  }
  stop() { for (const child of this.children) child.kill(); }
}

module.exports = { VoiceStudio };
