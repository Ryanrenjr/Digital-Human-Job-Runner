import { useState, useEffect, useCallback } from 'react'
import { Header }             from './components/Header'
import { CreateJobForm }      from './components/CreateJobForm'
import { JobQueue }           from './components/JobQueue'
import { JobDetail }          from './components/JobDetail'
import { QueueControlPanel }  from './components/QueueControlPanel'
import { TrainingPage }       from './components/TrainingPage'
import { translations }       from './translations'
import * as api from './api'

const DEFAULT_VOICE_PROFILE = {
  id: 'default_voice',
  name: 'System Voice',
  language: 'zh',
  dialect: 'mandarin',
  style: 'professional_calm',
  mode: 'basic_tts',
}

function loadVoiceProfiles() {
  try {
    const saved = JSON.parse(localStorage.getItem('dhjr_voice_profiles') || '[]')
    const custom = Array.isArray(saved) ? saved.filter(p => p?.id && p.id !== 'default_voice') : []
    return [DEFAULT_VOICE_PROFILE, ...custom]
  } catch {
    return [DEFAULT_VOICE_PROFILE]
  }
}

export default function App() {
  const [backendOnline,       setBackendOnline]       = useState(null)
  const [backgrounds,         setBackgrounds]         = useState([])
  const [jobs,                setJobs]                = useState([])
  const [selectedJobId,       setSelectedJobId]       = useState(null)
  const [jobLog,              setJobLog]              = useState(null)
  const [banner,              setBanner]              = useState(null)
  const [isSubmitting,        setIsSubmitting]        = useState(false)
  const [uploadingBackground, setUploadingBackground] = useState(false)
  const [queueStatus,         setQueueStatus]         = useState(null)
  const [queueLoading,        setQueueLoading]        = useState(true)
  const [queueError,          setQueueError]          = useState(null)
  const [activePage,          setActivePage]          = useState(
    () => window.location.hash === '#training' ? 'training' : 'jobs'
  )
  const [language,            setLanguage]            = useState(
    () => localStorage.getItem('dhjr_language') || 'zh'
  )
  const [voiceProfiles,       setVoiceProfiles]       = useState(loadVoiceProfiles)

  const t           = translations[language]
  const selectedJob = jobs.find(j => j.job_id === selectedJobId) || null

  const handleLanguageChange = (lang) => {
    setLanguage(lang)
    localStorage.setItem('dhjr_language', lang)
  }

  const handlePageChange = (page) => {
    setActivePage(page)
    if (page === 'training') {
      window.location.hash = 'training'
    } else {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }

  const saveVoiceProfiles = (profiles) => {
    setVoiceProfiles(profiles)
    localStorage.setItem(
      'dhjr_voice_profiles',
      JSON.stringify(profiles.filter(p => p.id !== 'default_voice')),
    )
  }

  const handleCreateVoiceProfile = (profile) => {
    saveVoiceProfiles([...voiceProfiles.filter(p => p.id !== profile.id), profile])
  }

  const handleDeleteVoiceProfile = (profileId) => {
    saveVoiceProfiles(voiceProfiles.filter(p => p.id === 'default_voice' || p.id !== profileId))
  }

  // ---- API helpers ----
  const checkHealth = useCallback(async () => {
    try   { await api.getHealth(); setBackendOnline(true) }
    catch { setBackendOnline(false) }
  }, [])

  const loadBackgrounds = useCallback(async () => {
    try   { setBackgrounds(await api.getBackgrounds()) }
    catch (e) { console.warn('backgrounds:', e) }
  }, [t.messages.backendConnectionFailed])

  const loadJobs = useCallback(async () => {
    try   { setJobs(await api.getJobs()) }
    catch (e) { console.warn('jobs:', e) }
  }, [])

  const loadQueueStatus = useCallback(async () => {
    try {
      const s = await api.getQueueStatus()
      setQueueStatus(s)
      setQueueError(null)
    } catch (e) {
      // If we've never loaded successfully, surface error; otherwise keep stale data silently
      setQueueStatus(prev => {
        if (prev === null) setQueueError(e.detail || e.message || t.messages.backendConnectionFailed)
        return prev
      })
    } finally {
      setQueueLoading(false)
    }
  }, [])

  const loadJobLog = useCallback(async (jobId) => {
    try   { const d = await api.getJobLog(jobId); setJobLog(d.log) }
    catch (e) { console.warn('log:', e) }
  }, [])

  // ---- Polling ----
  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 30_000)
    return () => clearInterval(timer)
  }, [checkHealth])

  useEffect(() => { loadBackgrounds() }, [loadBackgrounds])

  useEffect(() => {
    loadJobs()
    loadQueueStatus()
    const timer = setInterval(() => { loadJobs(); loadQueueStatus() }, 5_000)
    return () => clearInterval(timer)
  }, [loadJobs, loadQueueStatus])

  useEffect(() => {
    if (!selectedJobId) { setJobLog(null); return }
    loadJobLog(selectedJobId)
    const job = jobs.find(j => j.job_id === selectedJobId)
    if (job?.status === 'running') {
      const timer = setInterval(() => loadJobLog(selectedJobId), 5_000)
      return () => clearInterval(timer)
    }
  }, [selectedJobId, jobs, loadJobLog])

  // ---- Banner helpers ----
  const showBanner = (type, text) => {
    setBanner({ type, text })
    if (type === 'success') setTimeout(() => setBanner(null), 5_000)
  }

  // ---- Background handlers ----
  const handleUploadBackground = async (file) => {
    setUploadingBackground(true)
    try {
      await api.uploadBackground(file)
      await loadBackgrounds()
      showBanner('success', t.backgrounds.uploadSuccess)
    } catch (e) {
      showBanner('error', `${t.backgrounds.uploadFail}: ${e.detail || e.message}`)
    } finally {
      setUploadingBackground(false)
    }
  }

  const handleDeleteBackground = async (bgId) => {
    if (!window.confirm(t.backgrounds.deleteConfirm)) return
    try {
      await api.deleteBackground(bgId)
      await loadBackgrounds()
    } catch (e) {
      showBanner('error', e.detail || t.backgrounds.deleteBuiltinError)
    }
  }

  const retryQueueStatus = useCallback(() => {
    setQueueLoading(true)
    setQueueError(null)
    loadQueueStatus()
  }, [loadQueueStatus])

  // ---- Queue handlers ----
  const handleToggleAutoRun = async (enabled) => {
    try   { setQueueStatus(await api.setQueueAutoRun(enabled)) }
    catch (e) { console.warn('auto-run:', e) }
  }

  const handlePauseQueue = async () => {
    try   { setQueueStatus(await api.pauseQueue()) }
    catch (e) { console.warn('pause:', e) }
  }

  const handleResumeQueue = async () => {
    try   { setQueueStatus(await api.resumeQueue()); await loadJobs() }
    catch (e) { console.warn('resume:', e) }
  }

  const handleRunNext = async () => {
    try   { setQueueStatus(await api.runNextJob()); await loadJobs() }
    catch (e) { showBanner('error', e.detail || t.messages.anotherRunning) }
  }

  const handleToggleShutdown = async (enabled) => {
    try   { setQueueStatus(await api.setQueueShutdownOnComplete(enabled)) }
    catch (e) { console.warn('shutdown toggle:', e) }
  }

  // ---- Job handlers ----
  const handleCreateJob = async (formData, andRun) => {
    setIsSubmitting(true)
    setBanner(null)
    try {
      const job = await api.createJob(formData)
      if (andRun) {
        try {
          await api.runJob(job.job_id)
          showBanner('success', `${t.messages.jobStarted}: ${job.job_id}`)
        } catch (e) {
          if (e.status === 409) {
            // Another job is running — message depends on auto-run state
            const autoOn = queueStatus?.auto_run
            showBanner(
              autoOn ? 'success' : 'error',
              autoOn ? t.messages.jobQueuedAutoRun : t.messages.jobCreatedAutoRunOff,
            )
          } else {
            showBanner('error', `${t.messages.createdButCouldNotStart}: ${e.detail || e.message || t.messages.unknownError}`)
          }
        }
      } else {
        showBanner('success', `${t.messages.jobCreated}: ${job.job_id}`)
      }
      await loadJobs()
      setSelectedJobId(job.job_id)
    } catch (e) {
      showBanner('error', `${t.messages.failCreate}: ${e.detail || e.message || t.messages.unknownError}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleRunJob = async (jobId) => {
    setBanner(null)
    try {
      await api.runJob(jobId)
      await loadJobs()
      setSelectedJobId(jobId)
      showBanner('success', `${t.messages.jobStarted}: ${jobId}`)
    } catch (e) {
      if (e.status === 409) showBanner('error', t.messages.anotherRunning)
      else if (e.status === 400) showBanner('error', e.detail || t.messages.failRun)
      else showBanner('error', `${t.messages.failRun}: ${e.detail || e.message}`)
    }
  }

  const handleCancelJob = async (jobId) => {
    setBanner(null)
    try {
      await api.cancelJob(jobId)
      await loadJobs()
      showBanner('success', `${t.messages.jobCancelled}: ${jobId}`)
    } catch (e) {
      if (e.status === 409) showBanner('error', t.messages.activeProcess)
      else showBanner('error', e.detail || t.messages.failCancel)
    }
  }

  const handleResetJob = async (jobId) => {
    setBanner(null)
    try {
      await api.resetJob(jobId)
      await loadJobs()
      showBanner('success', `${t.messages.jobReset}: ${jobId}`)
    } catch (e) {
      if (e.status === 409) showBanner('error', t.messages.activeProcess)
      else showBanner('error', e.detail || t.messages.failReset)
    }
  }

  const handleDeleteJob = async (jobId) => {
    if (!window.confirm(
      `${t.messages.deleteConfirmTitle}\n${t.messages.deleteConfirmBody}`
    )) return
    setBanner(null)
    try {
      await api.deleteJob(jobId)
      if (selectedJobId === jobId) setSelectedJobId(null)
      await loadJobs()
      showBanner('success', `${t.messages.jobDeleted}: ${jobId}`)
    } catch (e) {
      if (e.status === 409) showBanner('error', t.messages.cannotDeleteRunning)
      else showBanner('error', e.detail || t.messages.failDelete)
    }
  }

  const handleSelectJob = (jobId) => {
    setSelectedJobId(prev => prev === jobId ? null : jobId)
  }

  return (
    <div>
      <Header
        online={backendOnline}
        language={language}
        onLanguageChange={handleLanguageChange}
        activePage={activePage}
        onPageChange={handlePageChange}
        t={t}
      />

      {banner && (
        <div className="banner-wrap">
          <div className={`banner banner-${banner.type}`}>
            <span>{banner.text}</span>
            <button className="banner-close" onClick={() => setBanner(null)}>×</button>
          </div>
        </div>
      )}

      {activePage === 'training' ? (
        <TrainingPage
          t={t}
          voiceProfiles={voiceProfiles}
          onCreateVoiceProfile={handleCreateVoiceProfile}
          onDeleteVoiceProfile={handleDeleteVoiceProfile}
        />
      ) : (
        <main className="main">
          <div className="left-panel">
            <CreateJobForm
              backgrounds={backgrounds}
              onSubmit={handleCreateJob}
              isSubmitting={isSubmitting}
              onUploadBackground={handleUploadBackground}
              onDeleteBackground={handleDeleteBackground}
              uploadingBackground={uploadingBackground}
              voiceProfiles={voiceProfiles.map(profile => ({
                ...profile,
                name: profile.id === 'default_voice' ? t.form.systemVoice : profile.name,
              }))}
              t={t}
            />
          </div>

          <div className="right-panel">
            <QueueControlPanel
              status={queueStatus}
              loading={queueLoading}
              error={queueError}
              onRetry={retryQueueStatus}
              onToggleAutoRun={handleToggleAutoRun}
              onPause={handlePauseQueue}
              onResume={handleResumeQueue}
              onRunNext={handleRunNext}
              onToggleShutdown={handleToggleShutdown}
              t={t}
            />
            <JobQueue
              jobs={jobs}
              selectedJobId={selectedJobId}
              onSelect={handleSelectJob}
              onRun={handleRunJob}
              onCancel={handleCancelJob}
              onReset={handleResetJob}
              onDelete={handleDeleteJob}
              onRefresh={loadJobs}
              t={t}
            />
            {selectedJob ? (
              <JobDetail
                job={selectedJob}
                log={jobLog}
                onClose={() => setSelectedJobId(null)}
                onRefreshLog={() => loadJobLog(selectedJobId)}
                onCancel={handleCancelJob}
                onReset={handleResetJob}
                onDelete={handleDeleteJob}
                t={t}
              />
            ) : (
              <div className="detail-empty">
                <div className="detail-empty-icon">◻</div>
                <div className="detail-empty-text">{t.detail.emptyTitle}</div>
              </div>
            )}
          </div>
        </main>
      )}
    </div>
  )
}
