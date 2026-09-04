const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL
export const BASE_URL = configuredBaseUrl && !configuredBaseUrl.includes(':8008')
  ? configuredBaseUrl
  : 'http://127.0.0.1:8018'

async function request(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res  = await fetch(BASE_URL + path, opts)
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    const err = new Error(data.detail || JSON.stringify(data))
    err.status = res.status
    err.detail = data.detail || JSON.stringify(data)
    throw err
  }
  return data
}

export const getHealth      = ()        => request('GET',    '/health')
export const getBackgrounds = ()        => request('GET',    '/backgrounds')
export const createJob      = (payload) => request('POST',   '/jobs', payload)
export const getJobs        = ()        => request('GET',    '/jobs')
export const getJob         = (jobId)   => request('GET',    `/jobs/${jobId}`)
export const runJob         = (jobId)   => request('POST',   `/jobs/${jobId}/run`)
export const cancelJob      = (jobId)   => request('POST',   `/jobs/${jobId}/cancel`)
export const resetJob       = (jobId)   => request('POST',   `/jobs/${jobId}/reset`)
export const deleteJob      = (jobId)   => request('DELETE', `/jobs/${jobId}`)
export const getJobLog      = (jobId)   => request('GET',    `/jobs/${jobId}/log`)
export const getVideoUrl    = (jobId)   => `${BASE_URL}/jobs/${jobId}/download`
export const getVoiceUrl   = (jobId)   => `${BASE_URL}/jobs/${jobId}/download-voice`

// Voice training
export const getVoices = () => request('GET', '/voices')
export const getVoiceLog = (voiceId) => request('GET', `/voices/${voiceId}/log`)
export const retryVoiceTraining = (voiceId) => request('POST', `/voices/${voiceId}/retry`)
export const deleteVoice = (voiceId) => request('DELETE', `/voices/${voiceId}`)
export const trainVoice = async ({ name, language, dialect, style, audioMinutes, audioScore, files }) => {
  const form = new FormData()
  form.append('name', name)
  form.append('language', language)
  form.append('dialect', dialect || '')
  form.append('style', style || 'friendly_natural')
  form.append('audio_minutes', String(audioMinutes || 0))
  form.append('audio_score', String(audioScore || 0))
  files.forEach(file => form.append('files', file))
  const res = await fetch(`${BASE_URL}/voices/train`, { method: 'POST', body: form })
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    const err = new Error(data.detail || JSON.stringify(data))
    err.status = res.status
    err.detail = data.detail
    throw err
  }
  return data
}

// Background management
export const deleteBackground = (bgId) => request('DELETE', `/backgrounds/${bgId}`)
export const getThumbnailUrl  = (bgId) => `${BASE_URL}/backgrounds/${bgId}/thumbnail`
export const getPreviewUrl    = (bgId) => `${BASE_URL}/backgrounds/${bgId}/preview`

export const uploadBackground = async (file) => {
  const form = new FormData()
  form.append('file', file)
  const res  = await fetch(`${BASE_URL}/backgrounds/upload`, { method: 'POST', body: form })
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) {
    const err = new Error(data.detail || JSON.stringify(data))
    err.status = res.status
    err.detail = data.detail
    throw err
  }
  return data
}

// Queue control
export const getQueueStatus            = ()        => request('GET',  '/queue/status')
export const setQueueAutoRun           = (enabled) => request('POST', '/queue/auto-run',              { enabled })
export const pauseQueue                = ()        => request('POST', '/queue/pause')
export const resumeQueue               = ()        => request('POST', '/queue/resume')
export const runNextJob                = ()        => request('POST', '/queue/run-next')
export const setQueueShutdownOnComplete= (enabled) => request('POST', '/queue/shutdown-after-complete', { enabled })

// AI Script Assistant
export const formatScript      = (payload) => request('POST', '/script/format', payload)
export const checkScriptHealth = (model)   => request('GET',  `/script/health?model=${encodeURIComponent(model)}`)
export const startOllama       = ()        => request('POST', '/script/start-ollama')
export const pullModel         = (model)   => request('POST', '/script/pull-model', { model })
export const getPullStatus     = (model)   => request('GET',  `/script/pull-status?model=${encodeURIComponent(model)}`)
export const installOllama     = ()        => request('POST', '/script/install-ollama')
export const getInstallStatus  = ()        => request('GET',  '/script/install-status')
export const repairRunners     = ()        => request('POST', '/script/repair-runners')
export const getRepairStatus   = ()        => request('GET',  '/script/repair-status')
