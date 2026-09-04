import { useState, useEffect, useRef } from 'react'
import * as api from '../api'

const labelFor = (map, value) => value ? (map?.[value] || value) : ''

function Row({ label, value, mono }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="detail-row">
      <span className="detail-key">{label}</span>
      <span className={`detail-val${mono ? ' mono' : ''}`}>{String(value)}</span>
    </div>
  )
}

function ProgressBox({ job, t }) {
  const pct   = job.progress?.percent         ?? 0
  const stage = job.progress?.stage           ?? 'pending'
  const msg   = job.progress?.message         ?? ''
  const curW  = job.progress?.current_window  ?? 0
  const totW  = job.progress?.total_windows   ?? 0
  const stageLabel = t.detail.stageLabels?.[stage] || stage

  const fillColor =
    job.status === 'finished'  ? 'var(--success)' :
    job.status === 'failed'    ? 'var(--error)'   :
    job.status === 'running'   ? 'var(--running)' :
    'var(--navy)'

  return (
    <div className="progress-box">
      <div className="progress-box-header">
        <span className="progress-box-label">{t.detail.progressLabel}</span>
        <span className="progress-box-pct">{stageLabel} · {pct}%</span>
      </div>
      <div className="progress-box-track">
        <div className="progress-box-fill" style={{ width: `${pct}%`, background: fillColor }} />
      </div>
      {totW > 0 && (
        <div className="progress-box-windows">{t.detail.windowPrefix} {curW} / {totW}</div>
      )}
      {msg && <div className="progress-box-msg">{msg}</div>}
    </div>
  )
}

function CopyPathRow({ path, copyText, copiedText }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(path).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="copy-path-wrap">
      <span className="copy-path-text" title={path}>{path}</span>
      <button className="btn btn-ghost btn-xs copy-path-btn" onClick={copy}>
        {copied ? copiedText : copyText}
      </button>
    </div>
  )
}

export function JobDetail({ job, log, onClose, onRefreshLog, onCancel, onReset, onDelete, t }) {
  const logRef = useRef(null)

  useEffect(() => {
    if (logRef.current && log) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  const paths      = job.paths || {}
  const artifacts  = job.artifacts || {}
  const videoExists = artifacts.clean_video_exists
  const voiceExists = artifacts.voice_wav_exists
  const videoUrl    = videoExists ? api.getVideoUrl(job.job_id)  : null
  const voiceUrl    = voiceExists ? api.getVoiceUrl(job.job_id)  : null

  const canCancel = job.status !== 'finished'
  const canReset  = ['failed', 'cancelled', 'running'].includes(job.status)
  const canDelete = job.status !== 'running'

  const handleDownload = () => {
    if (!videoUrl) return
    const a = document.createElement('a')
    a.href = videoUrl
    a.download = `${job.job_id}_clean_video.mp4`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const handleDownloadVoice = () => {
    if (!voiceUrl) return
    const a = document.createElement('a')
    a.href = voiceUrl
    a.download = `${job.job_id}_voice.wav`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="job-detail">
      <div className="detail-header">
        <span className="detail-header-title">{t.detail.title}</span>
        <div className="detail-actions">
          <button className="btn btn-ghost btn-sm" onClick={onRefreshLog}>{t.detail.refreshLog}</button>
          {canCancel && (
            <button className="btn btn-ghost btn-sm" onClick={() => onCancel(job.job_id)}>
              {t.detail.cancel}
            </button>
          )}
          {canReset && (
            <button className="btn btn-ghost btn-sm" onClick={() => onReset(job.job_id)}>
              {t.detail.reset}
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={onClose}>{t.detail.close}</button>
        </div>
      </div>

      <div className="detail-body">
        {/* ── Metadata ── */}
        <div className="detail-section">
          <Row label={t.detail.jobId}        value={job.job_id}     mono />
          <Row label={t.detail.titleLabel}   value={job.title} />
          <Row label={t.detail.subtitleLabel}value={job.subtitle} />
          <Row label={t.detail.background}   value={job.background_id} />
          <Row label={t.detail.voice}        value={job.voice_id} />
          <Row label={t.detail.voiceLanguage} value={labelFor(t.voiceLanguages, job.voice_language)} />
          <Row label={t.detail.voiceDialect}  value={labelFor(t.voiceDialects, job.voice_dialect)} />
          <Row label={t.detail.voiceMode}     value={labelFor(t.voiceModes, job.voice_mode)} />
          <Row label={t.detail.voiceStyle}    value={labelFor(t.voiceStyles, job.voice_style)} />
          <Row label={t.detail.created}      value={job.created_at} />
          <Row label={t.detail.started}      value={job.started_at} />
          <Row label={t.detail.finished}     value={job.finished_at} />
          {job.error_message && (
            <div className="detail-row">
              <span className="detail-key">{t.detail.errorLabel}</span>
              <span className="detail-val error-text">{job.error_message}</span>
            </div>
          )}
        </div>

        {/* ── Subtitle lines (AI-generated) or fallback to raw script ── */}
        {job.subtitle_lines_text ? (
          <div className="detail-section">
            <div className="detail-section-title">{t.detail.subtitleLinesLabel}</div>
            <pre className="detail-script detail-subtitle-lines">{job.subtitle_lines_text}</pre>
          </div>
        ) : job.script ? (
          <div className="detail-section">
            <div className="detail-section-title">{t.detail.scriptLabel}</div>
            <div className="detail-script">{job.script}</div>
          </div>
        ) : null}

        {/* ── Progress ── */}
        <ProgressBox job={job} t={t} />

        {/* ── Video preview + output actions (finished only) ── */}
        {job.status === 'finished' && videoExists && (
          <div className="detail-section">
            <div className="detail-section-title">{t.detail.previewLabel}</div>
            <div className="video-preview">
              <video controls src={videoUrl} preload="metadata" />
            </div>
            <div className="output-actions">
              <button className="btn btn-primary btn-sm" onClick={handleDownload}>
                {t.detail.downloadMp4}
              </button>
              {paths.windows_desktop_output && (
                <CopyPathRow
                  path={paths.windows_desktop_output}
                  copyText={t.detail.copyPath}
                  copiedText={t.detail.copied}
                />
              )}
            </div>
          </div>
        )}

        {/* ── Voice-only output (finished, no video) ── */}
        {job.status === 'finished' && !videoExists && voiceExists && (
          <div className="detail-section">
            <div className="output-actions">
              <button className="btn btn-primary btn-sm" onClick={handleDownloadVoice}>
                {t.detail.downloadVoice}
              </button>
            </div>
            <Row label={t.detail.windowsOutput} value={paths.windows_desktop_output} mono />
          </div>
        )}

        {/* ── Output paths (finished, no video, no voice) ── */}
        {job.status === 'finished' && !videoExists && !voiceExists && (
          <div className="detail-section">
            <Row label={t.detail.outputLabel}    value={paths.clean_video}            mono />
            <Row label={t.detail.windowsOutput}  value={paths.windows_desktop_output} mono />
          </div>
        )}

        {/* ── Log ── */}
        <div className="log-section">
          <div className="log-header">
            <span className="log-label">{t.detail.logLabel}</span>
          </div>
          {log ? (
            <pre className="log-viewer" ref={logRef}>{log}</pre>
          ) : (
            <div className="log-empty">{t.detail.noLog}</div>
          )}
        </div>

        {/* ── Delete zone ── */}
        {canDelete && (
          <div className="danger-zone">
            <button
              className="btn btn-danger btn-sm"
              onClick={() => onDelete(job.job_id)}
            >
              {t.detail.deleteJob}
            </button>
            <span className="danger-zone-hint">{t.detail.deleteHint}</span>
          </div>
        )}
      </div>
    </div>
  )
}
