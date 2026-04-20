/**
 * dev-start.js — Cross-platform script to start both backend and frontend
 * Usage: node dev-start.js
 */
const { spawn } = require("child_process");
const path = require("path");
const os = require("os");

const isWin = os.platform() === "win32";
const backendDir = path.join(__dirname, "backend");

// Python venv path
const pythonPath = isWin
  ? path.join(backendDir, "venv", "Scripts", "python.exe")
  : path.join(backendDir, "venv", "bin", "python");

console.log("");
console.log("  ╔══════════════════════════════════════╗");
console.log("  ║       UltraFlow AI Platform          ║");
console.log("  ║   Backend (FastAPI) + Frontend (Next) ║");
console.log("  ╚══════════════════════════════════════╝");
console.log("");
console.log("  [Backend]  http://localhost:8000  (FastAPI + Swagger: /docs)");
console.log("  [Frontend] http://localhost:3000  (UltraFlow AI)");
console.log("");

// Start backend
const backend = spawn(pythonPath, [
  "-m", "uvicorn", "app.main:app",
  "--host", "0.0.0.0", "--port", "8000", "--reload"
], {
  cwd: backendDir,
  stdio: "pipe",
  shell: false,
});

backend.stdout.on("data", (data) => {
  process.stdout.write(`\x1b[33m[BACK]\x1b[0m ${data}`);
});
backend.stderr.on("data", (data) => {
  process.stderr.write(`\x1b[33m[BACK]\x1b[0m ${data}`);
});
backend.on("close", (code) => {
  console.log(`[BACK] exited with code ${code}`);
});

// Start frontend
const frontend = spawn("npx", ["next", "dev", "--port", "3000"], {
  cwd: __dirname,
  stdio: "pipe",
  shell: isWin,
});

frontend.stdout.on("data", (data) => {
  process.stdout.write(`\x1b[36m[NEXT]\x1b[0m ${data}`);
});
frontend.stderr.on("data", (data) => {
  process.stderr.write(`\x1b[36m[NEXT]\x1b[0m ${data}`);
});
frontend.on("close", (code) => {
  console.log(`[NEXT] exited with code ${code}`);
  backend.kill();
});

// Clean exit
process.on("SIGINT", () => {
  console.log("\n  Stopping servers...");
  backend.kill();
  frontend.kill();
  process.exit(0);
});

process.on("SIGTERM", () => {
  backend.kill();
  frontend.kill();
  process.exit(0);
});
