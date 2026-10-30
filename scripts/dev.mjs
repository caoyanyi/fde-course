import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const local = join(root, '.local')
mkdirSync(local, { recursive: true, mode: 0o700 })
const secretsFile = join(local, 'dev-secrets.json')
if (!existsSync(secretsFile)) {
  writeFileSync(secretsFile, JSON.stringify({
    setupToken: randomBytes(32).toString('base64url'),
    masterKey: randomBytes(48).toString('base64url'),
  }), { mode: 0o600 })
}
const secrets = JSON.parse(readFileSync(secretsFile, 'utf8'))
const pythonCandidates = [
  process.env.FDE_PYTHON,
  join(root, '.venv', 'bin', 'python'),
].filter(Boolean)
const python = pythonCandidates.find(candidate => existsSync(candidate)) || 'python3'
const portIndex = process.argv.indexOf('--port')
const port = String(portIndex >= 0 ? process.argv[portIndex + 1] : (process.env.PORT || 5173))
if (!/^\d+$/.test(port) || Number(port) < 1024 || Number(port) > 65535) throw new Error('Invalid development port')
const children = []
let stopping = false

function start(command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, stdio: 'inherit' })
  children.push(child)
  child.on('error', error => { console.error(error.message); stop(1) })
  child.on('exit', code => { if (!stopping) stop(code || 0) })
  return child
}
function stop(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) child.kill('SIGTERM')
  const deadline = setTimeout(() => {
    for (const child of children) child.kill('SIGKILL')
    process.exit(code)
  }, 4000)
  Promise.all(children.map(child => child.exitCode !== null
    ? Promise.resolve()
    : new Promise(resolveExit => child.once('exit', resolveExit))))
    .then(() => { clearTimeout(deadline); process.exit(code) })
}
process.on('SIGINT', () => stop())
process.on('SIGTERM', () => stop())

start(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], join(root, 'backend'), {
  DATA_DIR: join(local, 'data'),
  COURSE_PATH: join(root, 'course', 'curriculum.json'),
  APP_SETUP_TOKEN: secrets.setupToken,
  APP_MASTER_KEY: secrets.masterKey,
  PUBLIC_ORIGIN: '',
  SESSION_COOKIE_SECURE: 'false',
  PYTHONDONTWRITEBYTECODE: '1',
})
start(process.execPath, [join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '0.0.0.0', '--port', port, '--strictPort'], join(root, 'frontend'), {})
