const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

if (process.platform === 'win32') {
  const root = path.resolve(__dirname, '..');
  const localPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  const python = process.env.PYTHON_BIN || (fs.existsSync(localPython) ? localPython : 'python');
  const build = spawnSync(python, ['-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--console',
    '--name', 'vocoflex-host', '--distpath', path.join(root, 'backend-bin'),
    '--workpath', path.join(root, 'build', 'windows-host'), '--specpath', path.join(root, 'build', 'windows-host'),
    '--collect-all', 'pedalboard', path.join(root, 'windows_vocoflex_host.py')], { stdio: 'inherit' });
  if (build.error) throw build.error;
  process.exit(build.status || 0);
}
if (process.platform !== 'darwin') {
  console.error('Vocoflex Lab uses the macOS Audio Unit plugin.');
  process.exit(1);
}
const root = path.resolve(__dirname, '..');
const app = path.join(root, 'artifacts', 'vocoflex-lab', 'Hinana Vocoflex Lab.app');
const contents = path.join(app, 'Contents');
const executable = path.join(contents, 'MacOS', 'vocoflex-host');
fs.mkdirSync(path.dirname(executable), { recursive: true });
const build = spawnSync('clang', [
  '-fobjc-arc', '-O2', '-Wall', '-Wextra',
  '-Wno-unused-parameter', '-framework', 'Cocoa', '-framework', 'AudioToolbox',
  path.join(__dirname, 'vocoflex-host.m'), '-o', executable,
], { stdio: 'inherit' });
if (build.error) throw build.error;
if (build.status !== 0) process.exit(build.status || 1);
fs.writeFileSync(path.join(contents, 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>vocoflex-host</string>
<key>CFBundleIdentifier</key><string>com.hinanavoice.vocoflex-lab</string>
<key>CFBundleName</key><string>Hinana Vocoflex Lab</string>
<key>CFBundleDisplayName</key><string>Hinana Vocoflex Lab</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
`);
console.log(`Built: ${app}`);
const runtime = path.join(root, 'backend-bin', 'vocoflex-host');
fs.mkdirSync(path.dirname(runtime), { recursive: true });
fs.copyFileSync(executable, runtime);
fs.cpSync(app, path.join(root, 'backend-bin', 'VocoflexHost.app'), { recursive: true });
if (process.argv.includes('--open')) {
  const launch = spawnSync('open', ['-n', app], { stdio: 'inherit' });
  if (launch.error) throw launch.error;
  process.exitCode = launch.status || 0;
}
