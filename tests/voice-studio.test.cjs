const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { VoiceStudio } = require('../electron/voice-studio');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hinana-profile-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const studio = new VoiceStudio({ root, hostPath: '/test/host', runBackend: () => { throw new Error('Unexpected backend call'); } });
  const directory = path.join(root, 'jobs', 'draft');
  fs.mkdirSync(directory, { recursive: true });
  const statePath = path.join(directory, 'voice.aupreset');
  fs.writeFileSync(statePath, 'voice-state-fixture');
  studio.job = { directory, statePath, referencePath: '/reference.wav',
    settings: { narrator: 'Test Narrator', speed: 95, pitch: 0 },
    analysis: { reference: { medianHz: 470 }, input: { medianHz: 292 } }, previewedShift: 8.5 };
  return { studio, root, statePath };
}

test('saved preset survives restart and removal of its temporary draft', (t) => {
  const { studio, root, statePath } = fixture(t);
  const result = studio.save({ name: 'My Voice', shift: 8.5 });
  const saved = result.profiles.find((profile) => profile.id === result.savedId);
  assert.ok(saved);
  studio.use(saved.id);
  fs.unlinkSync(statePath);
  const reopened = new VoiceStudio({ root, hostPath: '/new/host', runBackend: null });
  assert.equal(reopened.active().shift, 8.5);
  assert.equal(reopened.active().narrator, 'Test Narrator');
  assert.equal(reopened.active().hostPath, '/new/host');
  assert.equal(fs.readFileSync(reopened.active().statePath, 'utf8'), 'voice-state-fixture');
});
test('an unpreviewed shift cannot replace a verified preset', (t) => {
  const { studio } = fixture(t);
  assert.throws(() => studio.save({ name: 'Bad Voice', shift: 10 }), /미리 듣기/);
  assert.equal(studio.list().profiles.length, 0);
});
test('preset IDs cannot address files outside the library', (t) => {
  const { studio } = fixture(t);
  assert.throws(() => studio.profile('../settings.json'), /프리셋/);
  assert.throws(() => studio.use('../settings.json'), /프리셋/);
  assert.equal(studio.list().activeId, null);
});
test('busy conversion preserves its draft and reports an actionable error', (t) => {
  const { studio } = fixture(t);
  const job = studio.job;
  studio.busy = true;
  assert.throws(() => studio.selectReference('/another.wav', {}), /끝난 뒤/);
  assert.throws(() => studio.save({ name: 'Busy', shift: 8.5 }), /끝난 뒤/);
  assert.throws(() => studio.use(null), /끝난 뒤/);
  assert.equal(studio.job, job);
});
test('cancelling re-registration cannot reuse an older saved registration', { skip: process.platform === 'win32' }, async (t) => {
  const { studio, root, statePath } = fixture(t);
  studio.hostPath = path.join(root, 'cancel-host');
  fs.writeFileSync(studio.hostPath, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  await assert.rejects(studio.register(), /등록이 취소/);
  assert.equal(fs.readFileSync(statePath, 'utf8'), 'voice-state-fixture');
});

test('target WAV can be saved without synthesis or preview and survives restart', async (t) => {
  const { studio, root } = fixture(t);
  const oldJob = studio.job;
  const reference = path.join(root, 'hinana_2min.wav');
  fs.writeFileSync(reference, 'test-audio');
  studio.runBackend = (command) => {
    assert.equal(command.action, 'voice_target');
    assert.equal(command.referencePath, reference);
    return Promise.resolve({ reference: { medianHz: 456.7 } });
  };
  studio.registerState = async (selected, state) => {
    assert.equal(studio.busy, true);
    assert.equal(selected, reference);
    fs.writeFileSync(state, 'registered-state');
  };
  const result = await studio.createTarget(reference, { narrator: 'Koharu Rikka', speed: 95, pitch: 0 });
  const fresh = new VoiceStudio({ root, hostPath: studio.hostPath, runBackend: () => {} });
  const target = fresh.profile(result.savedId);
  assert.equal(target.referenceHz, 456.7);
  assert.equal(target.name, 'hinana_2min');
  assert.equal(target.targetOnly, true);
  assert.equal(fs.readFileSync(target.statePath, 'utf8'), 'registered-state');
  assert.equal(studio.job, oldJob);
  assert.equal(studio.busy, false);
  assert.throws(() => fresh.use(target.id), /자동 보정용/);
});

test('cancelled target registration does not publish a profile', async (t) => {
  const { studio, root } = fixture(t);
  const reference = path.join(root, 'target.wav');
  fs.writeFileSync(reference, 'test-audio');
  studio.runBackend = () => Promise.resolve({ reference: { medianHz: 456 } });
  studio.registerState = async () => { throw new Error('등록이 취소되었습니다.'); };
  await assert.rejects(studio.createTarget(reference, {}), /등록이 취소/);
  assert.equal(studio.list().profiles.length, 0);
  assert.equal(studio.busy, false);
});
