import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
let serial = 0
async function freshApi(t) {
  const originalWindow = globalThis.window
  const originalFetch = globalThis.fetch
  let expired = 0
  globalThis.window = {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    dispatchEvent(event) { if (event.type === 'fde:auth-expired') expired++; return true },
  }
  t.after(() => { globalThis.window = originalWindow; globalThis.fetch = originalFetch })
  const client = await import('data:text/javascript;base64,' + Buffer.from(compiled + `\n// instance-${serial++}`).toString('base64'))
  return { client, expired: () => expired }
}
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('account change aborts pending request and discards a late private response', async t => {
  const { client } = await freshApi(t)
  const response = deferred()
  let oldSignal
  globalThis.fetch = async (_url, options) => { oldSignal = options.signal; return response.promise }
  client.setCsrfToken('user-a-token')
  const request = client.api('/submissions')
  client.setCsrfToken('user-b-token')
  assert.equal(oldSignal.aborted, true)
  response.resolve(new Response(JSON.stringify({ items: [{ content: 'user A private work' }] }), { status: 200 }))
  await assert.rejects(request, client.SessionChangedError)
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.headers.get('X-CSRF-Token'), 'user-b-token')
    return new Response(JSON.stringify({ owner: 'B' }), { status: 200 })
  }
  assert.deepEqual(await client.api('/tasks/task-1/progress', { method: 'PATCH', body: '{}' }), { owner: 'B' })
})

test('a late 401 from a previous account does not log out the new account', async t => {
  const { client, expired } = await freshApi(t)
  const response = deferred()
  globalThis.fetch = async () => response.promise
  client.setCsrfToken('old-session')
  const request = client.api('/course')
  client.setCsrfToken('new-session')
  response.resolve(new Response(JSON.stringify({ detail: '旧会话失效' }), { status: 401 }))
  await assert.rejects(request, client.SessionChangedError)
  assert.equal(expired(), 0)
})

test('the active account still receives an authentication-expired event', async t => {
  const { client, expired } = await freshApi(t)
  client.setCsrfToken('active-session')
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: '请先登录' }), { status: 401 })
  await assert.rejects(client.api('/materials'), error => error instanceof client.ApiError && error.status === 401)
  assert.equal(expired(), 1)
})
