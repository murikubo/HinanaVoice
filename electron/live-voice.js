class LiveVoice {
  constructor({ studio, runBackend, emit, applyStandalone }) {
    this.studio = studio;
    this.runBackend = runBackend;
    this.emit = emit;
    this.applyStandalone = applyStandalone;
    this.operation = null;
    this.last = { event: 'live_stopped' };
    this.stopping = false;
  }
  start(request) {
    if (this.operation || this.studio.busy) throw new Error('진행 중인 음성 작업을 먼저 중지해 주세요.');
    const profile = this.studio.profile(request.profileId);
    if (!Number.isFinite(profile.referenceHz) || profile.referenceHz <= 0) throw new Error('참고 음높이가 저장된 프리셋을 선택해 주세요.');
    this.studio.busy = true;
    this.stopping = false;
    this.last = { event: 'live_status', phase: 'starting', message: '입력 장치 준비 중…' };
    let operation, calibration;
    try { operation = this.runBackend({ action: 'live_start', calibrationOnly: request.standalone === true, inputDevice: request.inputDevice,
      outputDevice: request.outputDevice, statePath: profile.statePath, hostPath: profile.hostPath,
      targetHz: profile.referenceHz }, (event) => {
        if (this.stopping && event.event === 'error') return;
        if (event.event === 'standalone_calibrated') calibration = event;
        if (request.standalone && event.event === 'live_stopped') return;
        if (event.event !== 'live_level') this.last = event;
        this.emit(event);
      }); } catch (error) { this.studio.busy = false; throw error; }
    if (request.standalone) {
      const backend = operation;
      operation = backend.then(async () => {
        if (this.stopping || !calibration) return;
        this.emit({ event: 'live_status', phase: 'applying', message: 'Vocoflex 자체 설정에 적용하고 다시 여는 중…' });
        const result = await this.applyStandalone(profile, calibration);
        this.last = { event: 'standalone_applied', ...result, message: 'Vocoflex 자체에 적용했습니다. 이제 Hinana Voice를 닫아도 Vocoflex에서 변환됩니다.' };
        this.emit(this.last);
      });
      operation.child = backend.child;
    }
    this.operation = operation;
    operation.catch((error) => {
      if (this.stopping) return;
      this.last = { event: 'error', message: error.message };
      this.emit(this.last);
    }).finally(() => {
      this.operation = null;
      this.studio.busy = false;
      if (this.stopping) {
        this.last = { event: 'live_stopped' };
        this.emit(this.last);
      }
      this.emit({ event: 'live_ended' });
    });
    return { started: true };
  }
  async stop() {
    const operation = this.operation;
    if (!operation) return;
    this.stopping = true;
    const terminate = (signal) => {
      try {
        if (process.platform !== 'win32' && operation.child?.pid) process.kill(-operation.child.pid, signal);
        else operation.child?.kill(signal);
      } catch (error) { if (error.code !== 'ESRCH') throw error; }
    };
    if (operation.child?.exitCode != null) { await operation.catch(() => {}); return; }
    terminate('SIGTERM');
    const timeout = setTimeout(() => terminate('SIGKILL'), 5000);
    timeout.unref();
    try { await operation.catch(() => {}); } finally { clearTimeout(timeout); }
  }
  status() { return { running: Boolean(this.operation), last: this.last }; }
}
module.exports = { LiveVoice };
