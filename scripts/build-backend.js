const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const output = path.join(root, "backend-bin");
const venvPython = process.platform === "win32"
  ? path.join(root, ".venv", "Scripts", "python.exe")
  : path.join(root, ".venv", "bin", "python3");
const python = process.env.PYTHON_BIN || (fs.existsSync(venvPython)
  ? venvPython
  : (process.platform === "win32" ? "python" : "python3"));

fs.mkdirSync(output, { recursive: true });

const args = [
  "-m",
  "PyInstaller",
  "--noconfirm",
  "--clean",
  "--onefile",
  "--console",
  "--name",
  "hinana-backend",
  "--distpath",
  output,
  "--workpath",
  path.join(root, "build", "backend"),
  "--specpath",
  path.join(root, "build", "backend"),
  "--collect-all",
  "sounddevice",
  "--collect-all",
  "soundfile",
  path.join(root, "hinana_bridge.py"),
];

const result = spawnSync(python, args, { cwd: root, stdio: "inherit", env: process.env });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);

console.log(`Backend ready: ${output}`);
