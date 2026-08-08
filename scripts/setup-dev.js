const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const venv = path.join(root, ".venv");
const systemPython = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");
const venvPython = process.platform === "win32"
  ? path.join(venv, "Scripts", "python.exe")
  : path.join(venv, "bin", "python3");

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", env: process.env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}

if (!fs.existsSync(venvPython)) run(systemPython, ["-m", "venv", venv]);
run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
run(venvPython, ["-m", "pip", "install", "-r", "requirements.txt", "pyinstaller>=6.0"]);

console.log(`Development runtime ready: ${venvPython}`);
