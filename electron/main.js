const { app, BrowserWindow, ipcMain, Menu } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

let mainWindow;
let activeChatProcess;

function createApplicationMenu() {
  const template = [];

  if (process.platform === "darwin") {
    template.push({
      label: app.name,
      submenu: [
        { label: `${app.name} 정보`, role: "about" },
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
  createApplicationMenu();
  ipcMain.handle("settings:get", () => loadSettings());
  ipcMain.handle("settings:save", (_event, settings) => saveSettings(settings));
  ipcMain.handle("backend:probe", async (_event, settings) => {
    const result = await runBackend({ action: "probe", voicepeak: settings.voicepeak });
    return result;
  });
  ipcMain.handle("chat:send", async (event, request) => {
    if (activeChatProcess) throw new Error("이미 답변을 처리하고 있습니다.");
    const childPromise = runBackend(
      { action: "chat", ...request },
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
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (activeChatProcess && !activeChatProcess.killed) activeChatProcess.kill();
});
