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
test('cancelling re-registration cannot reuse an older saved registration', async (t) => {
  const { studio, root, statePath } = fixture(t);
  studio.hostPath = path.join(root, 'cancel-host');
  fs.writeFileSync(studio.hostPath, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  await assert.rejects(studio.register(), /등록이 취소/);
  assert.equal(fs.readFileSync(statePath, 'utf8'), 'voice-state-fixture');
});
