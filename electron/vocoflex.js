const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const run = promisify(execFile);

function candidates(platform = process.platform) {
  return platform === 'darwin'
    ? ['/Applications/Vocoflex.app', path.join(os.homedir(), 'Applications/Vocoflex.app')]
    : [path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Vocoflex/vocoflex.exe'),
       path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Dreamtonics/Vocoflex/vocoflex.exe')];
}

function resolvePath(configured) {
  if (configured) return fs.existsSync(configured) ? configured : '';
  return candidates().find(item => fs.existsSync(item)) || '';
}

async function isRunning() {
  if (process.platform === 'win32') {
    const { stdout } = await run('tasklist.exe', ['/FI', 'IMAGENAME eq vocoflex.exe', '/FO', 'CSV', '/NH'], { windowsHide: true, timeout: 5000 });
    return /^"vocoflex\.exe",/im.test(stdout);
  }
  if (process.platform === 'darwin') {
    const { stdout } = await run('/bin/ps', ['-axo', 'comm='], { timeout: 5000 });
    return stdout.split('\n').some(line => /(?:^|\/)vocoflex$/i.test(line.trim()));
  }
  throw new Error('Vocoflex 자동 실행은 Windows와 macOS에서 지원합니다.');
}

async function inspect(configured) {
  try {
    return { running: await isRunning(), path: resolvePath(configured) };
  } catch (error) {
    return { running: null, path: resolvePath(configured), error: error.message };
  }
}

let launchTask;
function ensureRunning(configured) {
  if (launchTask) return launchTask;
  launchTask = (async () => {
    const state = await inspect(configured);
    if (state.error || state.running) return state;
    if (!state.path) return { ...state, error: 'Vocoflex를 찾지 못했습니다. 설정에서 실행 파일을 선택해 주세요.' };
    if (process.platform === 'darwin') {
      await run('/usr/bin/open', ['-a', state.path], { timeout: 10000 });
    } else {
      await new Promise((resolve, reject) => {
        const child = spawn(state.path, [], { detached: true, stdio: 'ignore', windowsHide: true });
        child.once('error', reject);
        child.once('spawn', () => { child.unref(); resolve(); });
      });
    }
    for (let attempt = 0; attempt < 12; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 500));
      if (await isRunning()) return { running: true, path: state.path };
    }
    return { ...state, error: '실행을 요청했지만 아직 확인되지 않았습니다. 잠시 후 다시 확인해 주세요.' };
  })().catch(error => ({ running: null, path: resolvePath(configured), error: error.message }))
    .finally(() => { launchTask = null; });
  return launchTask;
}

module.exports = { candidates, resolvePath, inspect, ensureRunning };
