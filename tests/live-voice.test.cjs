const test = require('node:test');
const assert = require('node:assert/strict');
const { LiveVoice } = require('../electron/live-voice');

test('live conversion uses trusted profile and releases audio work on stop', async () => {
  let command, resolve;
  const operation = new Promise((done) => { resolve = done; });
  operation.child = { kill: () => resolve({ event: 'live_stopped' }) };
  const studio = { busy: false, profile: () => ({ referenceHz: 471, statePath: '/trusted/state', hostPath: '/trusted/host' }) };
  const live = new LiveVoice({ studio, runBackend: (value) => { command = value; return operation; }, emit: () => {} });
  live.start({ profileId: 'hinana', inputDevice: 1, outputDevice: 2, statePath: '/untrusted', targetHz: 100 });
  assert.equal(command.statePath, '/trusted/state');
  assert.equal(command.targetHz, 471);
  assert.equal(studio.busy, true);
  assert.throws(() => live.start({}), /중지/);
  await live.stop();
  await new Promise(setImmediate);
  assert.equal(live.status().running, false);
  assert.equal(studio.busy, false);
});

test('failed live process reports an error and unlocks the studio', async () => {
  const events = [];
  const studio = { busy: false, profile: () => ({ referenceHz: 471 }) };
  const live = new LiveVoice({ studio, runBackend: () => Promise.reject(new Error('Device lost')), emit: (event) => events.push(event) });
  live.start({ profileId: 'hinana' });
  await new Promise(setImmediate);
  assert.equal(studio.busy, false);
  assert.equal(events[0].message, 'Device lost');
  assert.equal(events.at(-1).event, 'live_ended');
});

test('standalone mode applies measured calibration after capture has closed', async () => {
  let finish, listener, applied;
  const events = [];
  const backend = new Promise((resolve) => { finish = resolve; });
  const studio = { busy: false, profile: () => ({ referenceHz: 471, statePath: '/voice' }) };
  const live = new LiveVoice({ studio, runBackend: (command, callback) => {
    assert.equal(command.calibrationOnly, true); listener = callback; return backend;
  }, emit: (event) => events.push(event), applyStandalone: async (profile, calibration) => {
    assert.equal(studio.busy, true); applied = calibration; return { shift: calibration.shift };
  } });
  live.start({ standalone: true });
  listener({ event: 'standalone_calibrated', shift: 6.5, inputName: 'Mic', outputName: 'Headphones' });
  listener({ event: 'live_stopped' });
  assert.equal(applied, undefined);
  finish();
  await new Promise(setImmediate);
  assert.equal(applied.shift, 6.5);
  assert.equal(studio.busy, false);
  assert.equal(events.at(-2).event, 'standalone_applied');
});
