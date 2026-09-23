const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { EventEmitter } = require('node:events');

function fixture(running, exists = true) {
  let launches = 0;
  const context = {
    module: { exports: {} }, process: { platform: 'win32', env: {} },
    setTimeout: callback => setTimeout(callback, 0),
    require: name => name === 'node:fs' ? { existsSync: () => exists }
      : name === 'node:child_process' ? {
        execFile: (_file, _args, _options, callback) => callback(null, { stdout: running ? '"vocoflex.exe","100"' : '' }),
        spawn: () => {
          launches++; running = true;
          const child = new EventEmitter(); child.unref = () => {};
          setImmediate(() => child.emit('spawn'));
          return child;
        },
      } : require(name),
  };
  vm.runInNewContext(fs.readFileSync('electron/vocoflex.js', 'utf8'), context);
  return { api: context.module.exports, launches: () => launches };
}

test('existing process is not launched twice', async () => {
  const f = fixture(true);
  assert.equal((await f.api.ensureRunning('')).running, true);
  assert.equal(f.launches(), 0);
});
test('concurrent startup requests launch one process', async () => {
  const f = fixture(false);
  const results = await Promise.all([f.api.ensureRunning(''), f.api.ensureRunning('')]);
  assert.ok(results.every(result => result.running));
  assert.equal(f.launches(), 1);
});
test('missing configured path returns an actionable error', async () => {
  const f = fixture(false, false);
  assert.ok((await f.api.ensureRunning('missing.exe')).error);
  assert.equal(f.launches(), 0);
});
