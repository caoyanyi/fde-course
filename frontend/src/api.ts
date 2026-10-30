let csrfToken: string | null = null
let sessionEpoch = 0
const controllers = new Set<AbortController>()
export const currentSessionEpoch = () => sessionEpoch
export const setCsrfToken = (token: string | null) => {
  if (token !== csrfToken) {
    sessionEpoch++
    for (const controller of controllers) controller.abort()
  }
  csrfToken = token
}

export class SessionChangedError extends Error {
  constructor() { super(''); this.name = 'SessionChangedError' }
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const epoch = sessionEpoch
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (method !== 'GET' && method !== 'HEAD') {
    headers.set('X-FDE-Client', 'web')
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  }
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const controller = new AbortController()
  controllers.add(controller)
  const timeout = window.setTimeout(() => controller.abort(), 210000)
  try {
    const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin', signal: controller.signal })
    const text = await response.text()
    if (epoch !== sessionEpoch) throw new SessionChangedError()
    let payload: unknown = null
    try { payload = text ? JSON.parse(text) : null } catch { /* A proxy error need not contain JSON. */ }
    if (!response.ok) {
      let message = `请求未成功（${response.status}），请稍后重试。`
      const detail = (payload as { detail?: unknown } | null)?.detail
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map((x: { msg?: string }) => x.msg || '输入格式不正确').join('；')
      if (response.status === 401) window.dispatchEvent(new CustomEvent('fde:auth-expired'))
      throw new ApiError(message, response.status)
    }
    return payload as T
  } catch (error) {
    if (epoch !== sessionEpoch || error instanceof SessionChangedError) throw new SessionChangedError()
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw new ApiError('请求超时，请检查网络和服务状态后重试。', 0)
    throw new ApiError('暂时无法连接服务器，请检查网络连接。', 0)
  } finally { window.clearTimeout(timeout); controllers.delete(controller) }
}

export const json = (data: unknown) => JSON.stringify(data)
export const errorMessage = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试。'
