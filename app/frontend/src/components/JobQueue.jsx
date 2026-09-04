import * as api from '../api'

function StatusBadge({ status }) {
  return <span className={`status-badge s-${status}`}>{status}</span>
}

function CardActions({ job, selected, onSelect, onRun, onCancel, onReset, onDelete, t }) {
  const { job_id, status, artifacts } = job
  const videoExists = artifacts?.clean_video_exists

  const handleDownload = () => {
    const a = document.createElement('a')
    a.href = api.getVideoUrl(job_id)
    a.download = `${job_id}_clean_video.mp4`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="jc-actions" onClick={e => e.stopPropagation()}>
      <button
        className={`btn btn-ghost btn-xs${selected ? ' jc-btn-active' : ''}`}
        onClick={() => onSelect(job_id)}
      >
        {selected ? t.queue.close : t.queue.view}
      </button>

      {status === 'pending' && (
        <button className="btn btn-primary btn-xs" onClick={() => onRun(job_id)}>{t.queue.run}</button>
      )}
      {status === 'running' && (
        <button className="btn btn-ghost btn-xs" onClick={() => onCancel(job_id)}>{t.queue.cancel}</button>
      )}
      {(status === 'failed' || status === 'cancelled') && (
        <>
          <button className="btn btn-primary btn-xs" onClick={() => onRun(job_id)}>{t.queue.run}</button>
          <button className="btn btn-ghost btn-xs" onClick={() => onReset(job_id)}>{t.queue.reset}</button>
        </>
      )}
      {status === 'finished' && videoExists && (
        <button className="btn btn-ghost btn-xs" onClick={handleDownload}>{t.queue.downloadMp4}</button>
      )}
      {status !== 'running' && (
        <button className="btn btn-danger btn-xs" onClick={() => onDelete(job_id)}>{t.queue.delete}</button>
      )}
    </div>
  )
}

function JobCard({ job, selected, onSelect, onRun, onCancel, onReset, onDelete, t }) {
  const pct   = job.progress?.percent ?? 0
  const stage = job.progress?.stage   ?? 'pending'
  const stageLabel = t.detail?.stageLabels?.[stage] || stage
  const date  = job.created_at?.slice(0, 10) ?? ''

  return (
    <div
      className={`job-card status-${job.status}${selected ? ' selected' : ''}`}
      onClick={() => onSelect(job.job_id)}
    >
      <div className="jc-top">
        <span className="jc-title">{job.title || '(no title)'}</span>
        <StatusBadge status={job.status} />
      </div>

      <div className="jc-meta">
        <span className="jc-id">{job.job_id}</span>
        <span className="jc-bg">{job.background_id}</span>
      </div>

      <div className="progress-track">
        <div
          className={`progress-fill status-${job.status}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="jc-bottom">
        <span className="jc-stage">{stageLabel} · {pct}% · {date}</span>
        <CardActions
          job={job}
          selected={selected}
          onSelect={onSelect}
          onRun={onRun}
          onCancel={onCancel}
          onReset={onReset}
          onDelete={onDelete}
          t={t}
        />
      </div>
    </div>
  )
}

export function JobQueue({ jobs, selectedJobId, onSelect, onRun, onCancel, onReset, onDelete, onRefresh, t }) {
  const running = jobs.filter(j => j.status === 'running').length
  const pending = jobs.filter(j => j.status === 'pending').length

  return (
    <div className="queue-section">
      <div className="queue-header">
        <span className="queue-label">{t.queue.title}</span>
        <div className="queue-controls">
          <span className="queue-meta">
            {jobs.length} {t.queue.total}
            {running > 0 && <span className="queue-running"> · {running} {t.queue.running}</span>}
            {pending > 0 && <span className="queue-pending"> · {pending} {t.queue.pending}</span>}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={onRefresh}>{t.queue.refresh}</button>
        </div>
      </div>

      {jobs.length === 0 ? (
        <div className="no-jobs">{t.queue.noJobs}</div>
      ) : (
        jobs.map(job => (
          <JobCard
            key={job.job_id}
            job={job}
            selected={job.job_id === selectedJobId}
            onSelect={onSelect}
            onRun={onRun}
            onCancel={onCancel}
            onReset={onReset}
            onDelete={onDelete}
            t={t}
          />
        ))
      )}
    </div>
  )
}
