const API_ROOT = import.meta.env.VITE_API_ROOT || '/api'

export function token() { return localStorage.getItem('zhiyan_token') || '' }
export function refreshToken() { return localStorage.getItem('zhiyan_refresh_token') || '' }
export function portalMode() { return localStorage.getItem('zhiyan_portal') || 'personal' }
export function setPortalMode(value = 'personal') { localStorage.setItem('zhiyan_portal', value === 'team' ? 'team' : 'personal') }
export function activeTeamId() { return localStorage.getItem('zhiyan_active_team_id') || '' }
export function activeWorkspace() { return activeTeamId() ? 'team' : 'personal' }
export function setActiveTeamId(value = '') {
  if (value) localStorage.setItem('zhiyan_active_team_id', String(value))
  else localStorage.removeItem('zhiyan_active_team_id')
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('zhiyan-workspace-change', { detail: { teamId: value || '' } }))
}

let refreshPromise = null
let refreshTimer = null

function scheduleTokenRefresh(value) {
  if (refreshTimer && typeof window !== 'undefined') window.clearTimeout(refreshTimer)
  if (!value || typeof window === 'undefined') return
  try {
    const encoded = value.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=')))
    if (!payload.exp) return
    // Refresh one minute before expiry. The 401 path below covers sleeping
    // tabs and clocks that cannot run this timer precisely.
    const delay = Math.max(payload.exp * 1000 - Date.now() - 60_000, 5_000)
    refreshTimer = window.setTimeout(() => {
      refreshAccessToken().catch(() => {})
    }, delay)
  } catch {
    // A malformed token will be rejected by the API and handled normally.
  }
}

export function setToken(value, refreshValue = '') {
  if (value) localStorage.setItem('zhiyan_token', value)
  if (refreshValue) localStorage.setItem('zhiyan_refresh_token', refreshValue)
  scheduleTokenRefresh(value)
}

export function clearToken() {
  localStorage.removeItem('zhiyan_token')
  localStorage.removeItem('zhiyan_refresh_token')
  localStorage.removeItem('zhiyan_active_team_id')
  localStorage.removeItem('zhiyan_portal')
  if (refreshTimer && typeof window !== 'undefined') window.clearTimeout(refreshTimer)
  refreshTimer = null
}

async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise
  const storedRefreshToken = refreshToken()
  if (!storedRefreshToken) return false
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_ROOT}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: storedRefreshToken }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.access_token || !data.refresh_token) {
        clearToken()
        return false
      }
      setToken(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

async function fetchWithRefresh(path, options, unauthenticated = false) {
  const headers = new Headers(options.headers || {})
  const existingToken = token()
  if (existingToken && !unauthenticated) headers.set('Authorization', `Bearer ${existingToken}`)
  const teamId = activeTeamId()
  if (teamId && !unauthenticated) headers.set('X-Team-ID', teamId)
  let response = await fetch(`${API_ROOT}${path}`, { ...options, headers })
  if (response.status === 401 && existingToken && !unauthenticated && path !== '/auth/refresh') {
    if (await refreshAccessToken()) {
      headers.set('Authorization', `Bearer ${token()}`)
      response = await fetch(`${API_ROOT}${path}`, { ...options, headers })
    }
  }
  return { response, hadToken: Boolean(existingToken), unauthenticated }
}

export async function api(path, options = {}) {
  const isUnauthenticatedEndpoint = ['/auth/login', '/auth/register', '/auth/phone/code', '/auth/phone/login'].includes(path)
  const requestOptions = { ...options }
  if (requestOptions.body && !(requestOptions.body instanceof FormData) && typeof requestOptions.body !== 'string') {
    requestOptions.headers = new Headers(requestOptions.headers || {})
    requestOptions.headers.set('Content-Type', 'application/json')
    requestOptions.body = JSON.stringify(requestOptions.body)
  }
  const { response, hadToken } = await fetchWithRefresh(path, requestOptions, isUnauthenticatedEndpoint)
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (response.status === 401 && hadToken && !isUnauthenticatedEndpoint) {
    clearToken()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.assign('/login')
    }
  }
  if (!response.ok) throw new Error(data.detail || '请求失败，请稍后重试')
  return data
}

export async function apiStream(path, options = {}) {
  const isUnauthenticatedEndpoint = ['/auth/login', '/auth/register', '/auth/phone/code', '/auth/phone/login'].includes(path)
  const requestOptions = { ...options }
  if (requestOptions.body && !(requestOptions.body instanceof FormData) && typeof requestOptions.body !== 'string') {
    requestOptions.headers = new Headers(requestOptions.headers || {})
    requestOptions.headers.set('Content-Type', 'application/json')
    requestOptions.body = JSON.stringify(requestOptions.body)
  }
  const { response, hadToken } = await fetchWithRefresh(path, requestOptions, isUnauthenticatedEndpoint)
  if (response.status === 401 && hadToken && !isUnauthenticatedEndpoint) {
    clearToken()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.assign('/login')
    }
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || '请求失败，请稍后重试')
  }
  return response
}

export async function apiBlob(path, options = {}) {
  const { response, hadToken } = await fetchWithRefresh(path, { ...options })
  if (response.status === 401 && hadToken) {
    clearToken()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) window.location.assign('/login')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || '文件加载失败')
  }
  return response.blob()
}

scheduleTokenRefresh(token())

export function formatBytes(bytes = 0) {
  if (!bytes) return '0 KB'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}
