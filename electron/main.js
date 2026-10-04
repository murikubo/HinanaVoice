const { app, BrowserWindow, ipcMain, Menu, shell, dialog, systemPreferences } = require("electron");
const vocoflex = require('./vocoflex');
const { VoiceStudio } = require('./voice-studio');
const { LiveVoice } = require('./live-voice');
const fs = require("node:fs");
const path = require("node:path");
const { spawn, execFile } = require("node:child_process");
const runFile = require('node:util').promisify(execFile);

let mainWindow;
let activeChatProcess;
let voiceStudio;
let liveVoice;
const GITHUB_URL = "https://github.com/murikubo/HinanaVoice";

function openAboutDialog() {
  const window = BrowserWindow.getFocusedWindow() || mainWindow;
  window?.webContents.send("about:open");
}

function createApplicationMenu() {
  const template = [];

  if (process.platform === "darwin") {
    template.push({
      label: app.name,
      submenu: [
        { label: `${app.name} 정보`, click: openAboutDialog },
        { type: "separator" },
        { label: "서비스", role: "services" },
        { type: "separator" },
        { label: `${app.name} 숨기기`, accelerator: "Command+H", role: "hide" },
        { label: "다른 프로그램 숨기기", accelerator: "Command+Alt+H", role: "hideOthers" },
        { label: "모두 표시", role: "unhide" },
        { type: "separator" },
        { label: `${app.name} 종료`, accelerator: "Command+Q", role: "quit" },
      ],
    });
  }

  template.push(
    {
      label: "파일",
      submenu: [
        { label: "창 닫기", accelerator: "CmdOrCtrl+W", role: "close" },
        ...(process.platform === "darwin"
          ? []
          : [
              { type: "separator" },
              { label: "종료", accelerator: "Alt+F4", role: "quit" },
            ]),
      ],
    },
    {
      label: "편집",
      submenu: [
        { label: "실행 취소", accelerator: "CmdOrCtrl+Z", role: "undo" },
        { label: "다시 실행", accelerator: "CmdOrCtrl+Y", role: "redo" },
        { type: "separator" },
        { label: "잘라내기", accelerator: "CmdOrCtrl+X", role: "cut" },
        { label: "복사", accelerator: "CmdOrCtrl+C", role: "copy" },
        { label: "붙여넣기", accelerator: "CmdOrCtrl+V", role: "paste" },
        { label: "삭제", role: "delete" },
        { type: "separator" },
        { label: "모두 선택", accelerator: "CmdOrCtrl+A", role: "selectAll" },
      ],
    },
    {
      label: "보기",
      submenu: [
        { label: "새로 고침", accelerator: "CmdOrCtrl+R", role: "reload" },
        { label: "강제로 새로 고침", accelerator: "CmdOrCtrl+Shift+R", role: "forceReload" },
        { label: "개발자 도구", accelerator: "F12", role: "toggleDevTools" },
        { type: "separator" },
        { label: "화면 확대", accelerator: "CmdOrCtrl+Plus", role: "zoomIn" },
        { label: "화면 축소", accelerator: "CmdOrCtrl+-", role: "zoomOut" },
        { label: "기본 배율", accelerator: "CmdOrCtrl+0", role: "resetZoom" },
        { type: "separator" },
        { label: "전체 화면", accelerator: "F11", role: "togglefullscreen" },
      ],
    },
    {
      label: "창",
      submenu: [
        { label: "최소화", accelerator: "CmdOrCtrl+M", role: "minimize" },
        ...(process.platform === "darwin"
          ? [
              { label: "확대/축소", role: "zoom" },
              { type: "separator" },
              { label: "모든 창을 앞으로", role: "front" },
            ]
          : []),
      ],
    },
    {
      label: "도움말",
      submenu: [
        { label: "Hinana Voice 정보", click: openAboutDialog },
      ],
    },
  );

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function backendSourcePath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "backend", "hinana_bridge.py")
    : path.join(app.getAppPath(), "hinana_bridge.py");
}

function pythonCommand() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  if (!app.isPackaged) {
    const localPython = process.platform === "win32"
      ? path.join(app.getAppPath(), ".venv", "Scripts", "python.exe")
      : path.join(app.getAppPath(), ".venv", "bin", "python3");
    if (fs.existsSync(localPython)) return localPython;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function backendInvocation() {
  const binaryName = process.platform === "win32" ? "hinana-backend.exe" : "hinana-backend";
  const binary = process.env.HINANA_BACKEND_BIN || (
    app.isPackaged
      ? path.join(process.resourcesPath, "backend", "bin", binaryName)
      : path.join(app.getAppPath(), "backend-bin", binaryName)
  );
  if (fs.existsSync(binary)) return { command: binary, args: [] };
  return { command: pythonCommand(), args: ["-u", backendSourcePath()] };
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function defaults() {
  return {
    voicepeak:
      process.platform === "darwin"
        ? "/Applications/VOICEPEAK.app/Contents/MacOS/voicepeak"
        : "C:\\Program Files\\VOICEPEAK\\voicepeak.exe",
    narrator: "Koharu Rikka",
    device: null,
    deviceName: "",
    deviceApi: "",
    speed: 95,
    pitch: 0,
    autoLaunchVocoflex: false,
    vocoflexPath: '',
  };
}

function loadSettings() {
  try {
    const saved = JSON.parse(fs.readFileSync(settingsPath(), "utf8"));
    return { ...defaults(), ...saved, hasEnvironmentKey: Boolean(process.env.OPENAI_API_KEY) };
  } catch {
    return { ...defaults(), hasEnvironmentKey: Boolean(process.env.OPENAI_API_KEY) };
  }
}

function saveSettings(value) {
  const safe = {
    voicepeak: String(value.voicepeak || defaults().voicepeak),
    narrator: String(value.narrator || "Koharu Rikka"),
    device: value.device === null ? null : Number(value.device),
    deviceName: String(value.deviceName || ""),
    deviceApi: String(value.deviceApi || ""),
    speed: Number(value.speed || 95),
    pitch: Number(value.pitch || 0),
    autoLaunchVocoflex: value.autoLaunchVocoflex === true,
    vocoflexPath: String(value.vocoflexPath || ''),
  };
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(safe, null, 2), "utf8");
  return safe;
}

function runBackend(command, onEvent) {
  let child;
  const promise = new Promise((resolve, reject) => {
    const backend = backendInvocation();
    child = spawn(backend.command, backend.args, {
      windowsHide: true,
      detached: command.action === 'live_start' && process.platform !== 'win32',
      env: { ...process.env, PYTHONUTF8: "1" },
    });
    let stdout = "";
    let stderr = "";
    let lastEvent = null;

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (data) => {
      stdout += data;
      const lines = stdout.split(/\r?\n/);
      stdout = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          lastEvent = JSON.parse(line);
          onEvent?.(lastEvent);
        } catch {
          stderr += `\nUnexpected backend output: ${line}`;
        }
      }
    });
    child.stderr.on("data", (data) => {
      stderr += data;
    });
    child.on("error", (error) => reject(error));
    child.on("close", (code) => {
      if (stdout.trim()) {
        try {
          lastEvent = JSON.parse(stdout);
          onEvent?.(lastEvent);
        } catch {
          stderr += `\nUnexpected backend output: ${stdout}`;
        }
      }
      if (code === 0) resolve(lastEvent);
      else reject(new Error(lastEvent?.message || stderr.trim() || `Backend exited with ${code}`));
    });
    child.stdin.end(`${JSON.stringify(command)}\n`);
  });
  promise.child = child;
  return promise;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 820,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: "#ffffff",
    icon: path.join(app.getAppPath(), "icon.png"),
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  if (process.env.HINANA_CAPTURE_PATH) {
    mainWindow.webContents.once("did-finish-load", () => {
      setTimeout(async () => {
        const image = await mainWindow.webContents.capturePage();
        fs.mkdirSync(path.dirname(process.env.HINANA_CAPTURE_PATH), { recursive: true });
        fs.writeFileSync(process.env.HINANA_CAPTURE_PATH, image.toPNG());
        app.quit();
      }, 8000);
    });
  }
}

app.whenReady().then(() => {
  const hostPath = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'bin', 'VocoflexHost.app', 'Contents', 'MacOS', 'vocoflex-host')
    : path.join(app.getAppPath(), 'backend-bin', 'VocoflexHost.app', 'Contents', 'MacOS', 'vocoflex-host');
  voiceStudio = new VoiceStudio({ root: path.join(app.getPath('userData'), 'voice-presets'),
    hostPath, runBackend,
    seedDirectory: app.isPackaged ? null : path.join(app.getAppPath(), 'artifacts', 'vocoflex-lab', 'pitch-matched') });
  voiceStudio.seed();
  liveVoice = new LiveVoice({ studio: voiceStudio, runBackend,
    applyStandalone: async (profile, calibration) => {
      const configured = loadSettings().vocoflexPath;
      if (!vocoflex.resolvePath(configured)) throw new Error('Vocoflex 앱 설치 경로를 확인해 주세요.');
      await runFile(hostPath, ['--quit-standalone'], { timeout: 20000 });
      let result, opened;
      try {
        result = await runBackend({ action: 'standalone_apply', statePath: profile.statePath,
          settingsPath: path.join(app.getPath('appData'), 'Dreamtonics', 'Vocoflex', 'settings', 'settings.xml'),
          name: profile.name, shift: calibration.shift, inputName: calibration.inputName, outputName: calibration.outputName });
      } finally { opened = await vocoflex.ensureRunning(configured); }
      if (!opened.running) throw new Error(`설정은 저장했습니다. Vocoflex를 직접 실행해 주세요. ${opened.error || ''}`);
      return result;
    },
    emit: (event) => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('live:event', event); } });
  const studioWork = (work) => {
    if (activeChatProcess) throw new Error('대화 음성 재생이 끝난 뒤 시도해 주세요.');
    return work();
  };
  ipcMain.handle('voice:list', () => voiceStudio.list());
  ipcMain.handle('live:devices', () => runBackend({ action: 'live_devices' }));
  ipcMain.handle('live:status', () => liveVoice.status());
  ipcMain.handle('live:start', (_event, request) => studioWork(async () => {
    if (process.platform !== 'darwin') throw new Error('실시간 Vocoflex 변환은 macOS에서 지원합니다.');
    if (!await systemPreferences.askForMediaAccess('microphone')) throw new Error('시스템 설정의 마이크 권한에서 Hinana Voice를 허용해 주세요.');
    return liveVoice.start(request);
  }));
  ipcMain.handle('live:stop', () => liveVoice.stop());
  ipcMain.handle('voice:select', async () => studioWork(async () => {
    if (process.platform !== 'darwin') throw new Error('음성 프리셋은 현재 macOS에서 지원합니다.');
    const result = await dialog.showOpenDialog(mainWindow, { title: '참고 음성 선택',
      properties: ['openFile'], filters: [{ name: '음성', extensions: ['wav', 'flac', 'ogg'] }] });
    return result.canceled ? null : voiceStudio.selectReference(result.filePaths[0], loadSettings());
  }));
  ipcMain.handle('voice:register', () => studioWork(() => voiceStudio.register()));
  ipcMain.handle('voice:analyze', () => studioWork(() => voiceStudio.analyze()));
  ipcMain.handle('voice:preview', (_event, request) => studioWork(() => voiceStudio.preview(request)));
  ipcMain.handle('voice:save', (_event, request) => voiceStudio.save(request));
  ipcMain.handle('voice:use', (_event, id) => studioWork(async () => {
    if (id) {
      const profile = voiceStudio.profile(id);
      const current = loadSettings();
      const probe = await runBackend({ action: 'probe', voicepeak: profile.voicepeak || current.voicepeak });
      const outputs = probe.devices.filter((device) => !device.virtual);
      const output = outputs.find((device) => device.name === current.deviceName && device.api === current.deviceApi)
        || outputs.find((device) => device.default) || outputs[0];
      if (!output) throw new Error('헤드폰이나 스피커를 연결한 뒤 다시 적용해 주세요.');
      saveSettings({ ...current, narrator: profile.narrator, speed: profile.speed, pitch: profile.pitch,
        device: output.id, deviceName: output.name, deviceApi: output.api,
        voicepeak: profile.voicepeak || current.voicepeak });
    }
    return voiceStudio.use(id);
  }));
  ipcMain.handle('vocoflex:status', () => vocoflex.inspect(loadSettings().vocoflexPath));
  ipcMain.handle('vocoflex:launch', () => vocoflex.ensureRunning(loadSettings().vocoflexPath));
  ipcMain.handle('vocoflex:browse', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Vocoflex 실행 파일 선택', properties: ['openFile'],
      filters: [{ name: 'Vocoflex', extensions: process.platform === 'darwin' ? ['app'] : ['exe'] }],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  createApplicationMenu();
  ipcMain.handle("settings:get", () => loadSettings());
  ipcMain.handle("settings:save", (_event, settings) => {
    const previous = loadSettings();
    const saved = saveSettings(settings);
    if (['voicepeak', 'narrator', 'speed', 'pitch'].some((key) => previous[key] !== saved[key])) voiceStudio.use(null);
    return saved;
  });
  ipcMain.handle("app:info", () => ({
    name: app.name,
    version: app.getVersion(),
    author: "비나래",
    github: GITHUB_URL,
  }));
  ipcMain.handle("external:open", (_event, url) => {
    if (url !== GITHUB_URL) throw new Error("허용되지 않은 외부 주소입니다.");
    return shell.openExternal(url);
  });
  ipcMain.handle("backend:probe", async (_event, settings) => {
    const result = await runBackend({ action: "probe", voicepeak: settings.voicepeak });
    return { ...result, voiceProfileActive: Boolean(voiceStudio.active()) };
  });
  ipcMain.handle("chat:send", async (event, request) => {
    if (activeChatProcess) throw new Error("이미 답변을 처리하고 있습니다.");
    if (voiceStudio.busy) throw new Error('음성 프리셋 작업이 끝난 뒤 대화를 시작해 주세요.');
    const profile = voiceStudio.active();
    // Resolve the trusted saved preset in the main process, never a renderer path.
    const voiceProfile = profile ? { statePath: profile.statePath, shift: profile.shift, hostPath } : null;
    const childPromise = runBackend(
      { ...request, action: "chat", voiceProfile,
        ...(profile ? { narrator: profile.narrator, speed: profile.speed, pitch: profile.pitch,
          voicepeak: profile.voicepeak || loadSettings().voicepeak } : {}) },
      (payload) => event.sender.send("backend:event", payload),
    );
    activeChatProcess = childPromise.child;
    try {
      await childPromise;
      return { accepted: true };
    } finally {
      activeChatProcess = null;
    }
  });

  createWindow();
  const startupSettings = loadSettings();
  if (startupSettings.autoLaunchVocoflex) void vocoflex.ensureRunning(startupSettings.vocoflexPath);
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  void liveVoice?.stop();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  void liveVoice?.stop();
  voiceStudio?.stop();
  if (activeChatProcess && !activeChatProcess.killed) activeChatProcess.kill();
});
