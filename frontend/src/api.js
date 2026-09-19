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
export const stopRuntime = () => api.post('/api/stop').then((response) => response.data)

export const setSourceEnabled = (id, enabled) =>
  api.patch(`/api/sources/${id}`, { enabled }).then((response) => response.data)
export const deleteSource = (id) => api.delete(`/api/sources/${id}`).then((response) => response.data)
export const setTargetEnabled = (id, enabled) =>
  api.patch(`/api/targets/${id}`, { enabled }).then((response) => response.data)
export const createRoutesBatch = (sourceIds, targetIds) =>
  api.post('/api/routes/batch', { source_ids: sourceIds, target_ids: targetIds }).then((response) => response.data)
export const deleteRoute = (id) =>
  api.delete(`/api/routes/${id}`).then((response) => response.data)
export const updateRule = (sourceId, rule) =>
  api.put(`/api/rules/${sourceId}`, rule).then((response) => response.data)

export const getControlCommands = (limit = 50) =>
  api.get('/api/control/commands', { params: { limit } }).then((response) => response.data)
export const enqueueAddSource = (name, input, join = false) =>
  api.post('/api/control/add-source', { name, input, join }).then((response) => response.data)
export const enqueueAddTarget = (name, input) =>
  api.post('/api/control/add-target', { name, input }).then((response) => response.data)
export const enqueueSync = (sourceId, limit = 100, keywords = [], recent = true) =>
  api.post('/api/control/sync', { source_id: sourceId, limit, keywords, recent }).then((response) => response.data)

export const checkAccess = (sourceIds = [], targetIds = []) =>
  api.post('/api/access/check', { source_ids: sourceIds, target_ids: targetIds }).then((response) => response.data)
export const checkAuth = () => api.get('/api/auth/check').then((response) => response.data)

export const login = (username, password) => api.post('/api/auth/login', { username, password }).then((response) => response.data)

export const getAuditLogs = (limit = 100) =>
  api.get('/api/audit', { params: { limit } }).then((response) => response.data)

export const getUsers = () => api.get('/api/users').then((response) => response.data)
export const createUser = (payload) => api.post('/api/users', payload).then((response) => response.data)
export const updateUser = (id, payload) =>
  api.patch(`/api/users/${id}`, payload).then((response) => response.data)

export const logoutSession = () => api.post('/api/auth/logout').then((response) => response.data)

export const getLoginHistory = (limit = 100) =>
  api.get('/api/login-history', { params: { limit } }).then((response) => response.data)

export const changePassword = (currentPassword, newPassword) =>
  api.patch('/api/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  }).then((response) => response.data)
export const logoutAllSessions = () =>
  api.post('/api/auth/logout-all').then((response) => response.data)

export const getAdditionalSettings = () =>
  api.get('/api/settings/additional').then((response) => response.data)
export const getSyncBehavior = () => api.get('/api/settings/sync').then((response) => response.data)
export const updateSyncBehavior = (payload) => api.put('/api/settings/sync', payload).then((response) => response.data)
export const updateAdditionalSettings = (payload) =>
  api.put('/api/settings/additional', payload).then((response) => response.data)

export const uploadAdditionalImage = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/settings/additional/upload', formData).then((response) => response.data)
}

export const sendManualPost = (payload) =>
  api.post('/api/control/manual-post', payload).then((response) => response.data)

export const getAdImageDefaults = () =>
  api.get('/api/settings/ad-image').then((response) => response.data)
export const updateAdImageDefaults = (payload) =>
  api.put('/api/settings/ad-image', payload).then((response) => response.data)
export const generateAdImage = (payload) => {
  const formData = new FormData()
  formData.append('text', payload.text)
  formData.append('width', String(payload.width))
  formData.append('height', String(payload.height))
  formData.append('output_format', payload.outputFormat)
  if (payload.background) formData.append('background', payload.background)
  return api.post('/api/ad-image/generate', formData, { responseType: 'blob' })
}

export const getUploadAssets = () =>
  api.get('/api/uploads').then((response) => response.data)
export const deleteUploadAssets = (filenames) =>
  api.post('/api/uploads/delete', { filenames }).then((response) => response.data)
