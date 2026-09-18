import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_session_token') || localStorage.getItem('admin_api_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export const getStatus = () => api.get('/api/status').then((response) => response.data)
export const getSources = () => api.get('/api/sources').then((response) => response.data)
export const getTargets = () => api.get('/api/targets').then((response) => response.data)
export const getRoutes = () => api.get('/api/routes').then((response) => response.data)
export const getRules = () => api.get('/api/rules').then((response) => response.data)
export const getJobs = (status = '', limit = 100) =>
  api
    .get('/api/jobs', { params: { status: status || undefined, limit } })
    .then((response) => response.data)
export const pauseRuntime = () => api.post('/api/pause').then((response) => response.data)
export const resumeRuntime = () => api.post('/api/resume').then((response) => response.data)
export const retryFailed = () => api.post('/api/retry-failed').then((response) => response.data)

export const setSourceEnabled = (id, enabled) =>
  api.patch(`/api/sources/${id}`, { enabled }).then((response) => response.data)
export const setTargetEnabled = (id, enabled) =>
  api.patch(`/api/targets/${id}`, { enabled }).then((response) => response.data)
export const createRoute = (sourceId, targetId) =>
  api.post('/api/routes', { source_id: sourceId, target_id: targetId }).then((response) => response.data)
export const deleteRoute = (id) =>
  api.delete(`/api/routes/${id}`).then((response) => response.data)
export const updateRule = (sourceId, rule) =>
  api.put(`/api/rules/${sourceId}`, rule).then((response) => response.data)

export const getControlCommands = (limit = 50) =>
  api.get('/api/control/commands', { params: { limit } }).then((response) => response.data)
export const enqueueAddSource = (input, join = false) =>
  api.post('/api/control/add-source', { input, join }).then((response) => response.data)
export const enqueueAddTarget = (input) =>
  api.post('/api/control/add-target', { input }).then((response) => response.data)
export const enqueueSync = (sourceId, limit = 100) =>
  api.post('/api/control/sync', { source_id: sourceId, limit }).then((response) => response.data)

export const checkAuth = () => api.get('/api/auth/check').then((response) => response.data)

export const login = (username, password) => api.post('/api/auth/login', { username, password }).then((response) => response.data)

export const getAuditLogs = (limit = 100) =>
  api.get('/api/audit', { params: { limit } }).then((response) => response.data)

export const getUsers = () => api.get('/api/users').then((response) => response.data)
export const createUser = (payload) => api.post('/api/users', payload).then((response) => response.data)
export const updateUser = (id, payload) =>
  api.patch(`/api/users/${id}`, payload).then((response) => response.data)

export const logoutSession = () => api.post('/api/auth/logout').then((response) => response.data)
