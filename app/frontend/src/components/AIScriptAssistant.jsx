import { useState, useEffect, useCallback } from 'react'
import * as api from '../api'

const DEFAULT_MODEL   = 'qwen2.5:7b'
const POLL_INTERVAL   = 5000   // ms between auto-polls
const KNOWN_MODELS    = ['qwen2.5:7b', 'qwen2.5:14b', 'qwen2.5:3b', 'qwen2.5:1.5b', 'qwen3:32b']

function chooseAvailableModel(models, current) {
  if (!models?.length || models.includes(current)) return current
  const preferred = ['qwen2.5:14b', 'qwen3:32b', 'qwen2.5:7b', 'qwen2.5:3b', 'qwen2.5:1.5b']
  return preferred.find(name => models.includes(name)) || models[0]
}

export function AIScriptAssistant({ onApply, t }) {
  const [expanded,       setExpanded]       = useState(false)
  const [rawScript,      setRawScript]      = useState('')
  const [model,          setModel]          = useState(DEFAULT_MODEL)

  // AI formatting
  const [loading,        setLoading]        = useState(false)
  const [result,         setResult]         = useState(null)
  const [editResult,     setEditResult]     = useState(null)
  const [error,          setError]          = useState(null)
  const [applied,        setApplied]        = useState(false)
  const [copied,         setCopied]         = useState(false)

  // Health / connection
  const [testing,        setTesting]        = useState(false)
  const [healthInfo,     setHealthInfo]     = useState(null)

  // Install flow
  const [installingOllama, setInstallingOllama] = useState(false)
  const [installStatus,    setInstallStatus]    = useState(null)   // {installed,running,failed,log_tail}

  // Start Ollama flow
  const [startingOllama,    setStartingOllama]    = useState(false)
  const [oneClickStarting,  setOneClickStarting]  = useState(false)

  // Repair runners flow
  const [repairingRunners, setRepairingRunners] = useState(false)
  const [repairStatus,     setRepairStatus]     = useState(null)   // {runner_ok,running,failed,log_tail}

  // Pull model flow
  const [pullingModel,   setPullingModel]   = useState(false)
  const [pullStatus,     setPullStatus]     = useState(null)       // {installed,running,log_tail}

  // The default model may not be installed on a new machine. Follow the
  // actual Ollama inventory so users do not have to diagnose this themselves.
  useEffect(() => {
    const available = healthInfo?.available_models || []
    if (!available.length || available.includes(model)) return
    const nextModel = chooseAvailableModel(available, model)
    setModel(nextModel)
    setHealthInfo(prev => {
      if (!prev) return prev
      const runnerReady = prev.runner_ok !== false
      return {
        ...prev,
        model: nextModel,
        model_found: true,
        ok: runnerReady,
        message: runnerReady ? 'ready' : 'runner_missing',
        user_message: runnerReady ? 'AI is ready' : prev.user_message,
        user_message_zh: runnerReady ? 'AI 可以使用' : prev.user_message_zh,
      }
    })
  }, [healthInfo?.available_models, model])

  const setField = (key, val) =>
    setEditResult(r => ({ ...r, [key]: val }))

  // ── Error parsing ─────────────────────────────────────────────────────────

  const parseError = (e) => {
    const detail = e.detail
    const status = e.status
    if (detail && typeof detail === 'object') {
      const code = detail.code
      if (code === 'OLLAMA_NOT_RUNNING') return t.ai.ollamaError
      if (code === 'RUNNER_MISSING')     return t.ai.runnerError
      if (code === 'MODEL_NOT_FOUND')    return `${t.ai.modelError} ${detail.model || model}`
      return `${t.ai.genericError}: ${detail.message || JSON.stringify(detail)}`
    }
    const msg = typeof detail === 'string' ? detail : (e.message || '')
    const lc  = msg.toLowerCase()
    if (status === 503 || lc.includes('not running') || lc.includes('ollama')) return t.ai.ollamaError
    if (lc.includes('runner') || lc.includes('llama-server'))  return t.ai.runnerError
    if (status === 404 || lc.includes('not found'))  return `${t.ai.modelError} ${model}`
    return `${t.ai.genericError}: ${msg || status}`
  }

  // ── Step 0: Test health ───────────────────────────────────────────────────

  const handleTest = useCallback(async () => {
    setTesting(true)
    setHealthInfo(null)
    setPullStatus(null)
    setInstallStatus(null)
    setRepairStatus(null)
    try {
      const res = await api.checkScriptHealth(model)
      setHealthInfo(res)
    } catch (e) {
      const isNetworkErr = !e.status && /fetch|network|connect/i.test(e.message || '')
      setHealthInfo({
        ok: false, ollama_running: false,
        ollama_installed: isNetworkErr ? null : false,  // null = unknown (backend unreachable)
        runner_ok: true, model_found: false,
        user_message: isNetworkErr ? (t.ai.genericError + ': Failed to fetch — backend not running?') : parseError(e),
        available_models: [],
        network_error: isNetworkErr,
      })
    } finally {
      setTesting(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model])

  // ── Step 1: Install Ollama ────────────────────────────────────────────────

  const handleInstallOllama = async () => {
    setInstallingOllama(true)
    setError(null)
    try {
      const res = await api.installOllama()
      if (res.already_installed) {
        // Already installed — just update health state and proceed
        setHealthInfo(prev => ({
          ...prev,
          ollama_installed: true,
          user_message:    res.message    || '',
          user_message_zh: res.message_zh || '',
        }))
      } else if (res.ok && res.started) {
        // Download in progress — start polling
        setInstallStatus({ installed: false, running: true, failed: false, log_tail: '' })
      } else {
        setInstallStatus({ installed: false, running: false, failed: true, log_tail: res.message_zh || res.message || '' })
      }
    } catch (e) {
      setInstallStatus({ installed: false, running: false, failed: true, log_tail: parseError(e) })
    } finally {
      setInstallingOllama(false)
    }
  }

  // Auto-poll install status while download is running
  useEffect(() => {
    if (!installStatus?.running) return
    const timer = setInterval(async () => {
      try {
        const res = await api.getInstallStatus()
        setInstallStatus(res)
        if (res.installed) {
          // Download finished — auto-start Ollama
          clearInterval(timer)
          handleStartOllamaInternal()
        } else if (!res.running) {
          clearInterval(timer)  // failed or unexpected stop
        }
      } catch { /* ignore poll errors */ }
    }, POLL_INTERVAL)
    return () => clearInterval(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installStatus?.running])

  // ── Step 1b: Repair CPU runners ──────────────────────────────────────────

  const handleRepairRunners = async () => {
    setRepairingRunners(true)
    setError(null)
    try {
      const res = await api.repairRunners()
      if (res.already_ok) {
        await handleTest()
      } else if (res.ok && res.started) {
        setRepairStatus({ runner_ok: false, running: true, failed: false, log_tail: '' })
      } else {
        setRepairStatus({ runner_ok: false, running: false, failed: true, log_tail: res.message_zh || res.message || '' })
      }
    } catch (e) {
      setRepairStatus({ runner_ok: false, running: false, failed: true, log_tail: parseError(e) })
    } finally {
      setRepairingRunners(false)
    }
  }

  // Auto-poll repair status while running
  useEffect(() => {
    if (!repairStatus?.running) return
    const timer = setInterval(async () => {
      try {
        const res = await api.getRepairStatus()
        setRepairStatus(res)
        if (res.runner_ok) {
          clearInterval(timer)
          await handleTest()
        } else if (!res.running) {
          clearInterval(timer)
        }
      } catch { /* ignore */ }
    }, POLL_INTERVAL)
    return () => clearInterval(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repairStatus?.running])

  // ── Step 2: Start Ollama ──────────────────────────────────────────────────

  const handleStartOllamaInternal = async () => {
    setStartingOllama(true)
    setInstallStatus(null)
    try {
      const res = await api.startOllama()
      if (res.ok) {
        await handleTest()   // refresh health → shows model status
      } else {
        // Not installed after all — re-check
        setHealthInfo({
          ok: false, ollama_running: false,
          ollama_installed: res.ollama_installed ?? false,
          model_found: false, available_models: [],
          user_message:    res.message    || t.ai.ollamaError,
          user_message_zh: res.message_zh || t.ai.ollamaError,
        })
      }
    } catch (e) {
      setHealthInfo(prev => ({
        ok: false, ollama_running: false,
        ollama_installed: prev?.ollama_installed ?? false,
        model_found: false, available_models: prev?.available_models || [],
        user_message:    parseError(e),
        user_message_zh: parseError(e),
      }))
    } finally {
      setStartingOllama(false)
    }
  }

  const handleStartOllama = () => handleStartOllamaInternal()

  // ── One-click start: check → start → pull in sequence ────────────────────

  const handleOneClickStart = async () => {
    setOneClickStarting(true)
    setError(null)
    try {
      const health = await api.checkScriptHealth(model)
      setHealthInfo(health)
      const selectedModel = chooseAvailableModel(health.available_models, model)
      const effectiveHealth = selectedModel === model
        ? health
        : { ...health, model: selectedModel, model_found: true, ok: health.runner_ok !== false }
      if (selectedModel !== model) setModel(selectedModel)
      if (effectiveHealth.ok) return

      if (!effectiveHealth.ollama_installed) return   // show install wizard, user must install manually

      if (!effectiveHealth.ollama_running) {
        await handleStartOllamaInternal()    // starts Ollama + re-checks health internally
        return
      }

      if (effectiveHealth.runner_ok === false) {
        await handleRepairRunners()
        return
      }

      if (!effectiveHealth.model_found) {
        await handlePullModel(selectedModel)
      }
    } catch (e) {
      setError(parseError(e))
    } finally {
      setOneClickStarting(false)
    }
  }

  // ── Step 3: Pull model ────────────────────────────────────────────────────

  const handlePullModel = async (requestedModel = model) => {
    setPullingModel(true)
    setPullStatus(null)
    try {
      const res = await api.pullModel(requestedModel)
      if (res.ok) {
        setPullStatus({ running: res.started && !res.installed, installed: !!res.installed, log_tail: '' })
      } else {
        setError(res.message_zh || res.message || t.ai.pullFailed)
      }
    } catch (e) {
      setError(parseError(e))
    } finally {
      setPullingModel(false)
    }
  }

  // Auto-poll pull status while model is downloading
  useEffect(() => {
    if (!pullStatus?.running) return
    const timer = setInterval(async () => {
      try {
        const res = await api.getPullStatus(model)
        setPullStatus(res)
        if (res.installed) {
          clearInterval(timer)
          await handleTest()   // refresh to show "AI Ready"
        } else if (!res.running) {
          clearInterval(timer)
        }
      } catch { /* ignore */ }
    }, POLL_INTERVAL)
    return () => clearInterval(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pullStatus?.running, model])

  // ── Format ────────────────────────────────────────────────────────────────

  const handleFormat = async () => {
    if (!rawScript.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    setApplied(false)
    try {
      let lastError = null
      for (let attempt = 0; attempt < 6; attempt++) {
        if (attempt > 0) {
          setError(`后端启动中，正在重试… (${attempt}/5)`)
          await new Promise(r => setTimeout(r, 3000))
        }
        try {
          const r = await api.formatScript({ raw_text: rawScript, model })
          setError(null)
          setResult(r)
          setEditResult({
            title:          r.title          || '',
            subtitle:       r.subtitle       || '',
            keywords:       (r.keywords || []).join(', '),
            clean_script:   r.clean_script   || '',
            subtitle_lines: (r.subtitle_lines || []).join('\n'),
            opening_hook:   r.opening_hook   || '',
          })
          return
        } catch (e) {
          lastError = e
          const isNetworkErr = !e.status && /fetch|network|connect/i.test(e.message || '')
          if (!isNetworkErr) { setError(parseError(e)); return }
        }
      }
      setError(parseError(lastError))
    } finally {
      setLoading(false)
    }
  }

  // ── Apply ─────────────────────────────────────────────────────────────────

  const handleApply = () => {
    const keywords = editResult.keywords.split(',').map(k => k.trim()).filter(Boolean)
    onApply({
      title:          editResult.title,
      subtitle:       editResult.subtitle,
      keywords,
      script:         editResult.clean_script,
      subtitle_lines: editResult.subtitle_lines.split('\n').map(s => s.trim()).filter(Boolean),
      opening_hook:   editResult.opening_hook,
      script_source:  'ollama',
      script_model:   model,
    })
    setApplied(true)
    setTimeout(() => setApplied(false), 3000)
  }

  const handleCopySubtitles = () => {
    navigator.clipboard.writeText(editResult.subtitle_lines).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // ── Render: setup wizard ──────────────────────────────────────────────────

  const renderSetupFlow = () => {
    if (!healthInfo) return null

    const { ollama_installed, ollama_running, model_found, ok } = healthInfo

    // Message banner
    const msg  = healthInfo.user_message_zh || healthInfo.user_message || ''
    const msgOk = ok

    const banner = (
      <div className={`ai-health${msgOk ? ' ai-health-ok' : ' ai-health-fail'}`}>
        {msgOk ? '✓ ' : '✕ '}{msg}
        {!msgOk && healthInfo.available_models?.length > 0 && (
          <div className="ai-health-models">
            {t.ai.availableModels} {healthInfo.available_models.join(', ')}
          </div>
        )}
      </div>
    )

    // Network error — backend unreachable, don't show any wizard steps
    if (healthInfo.network_error) return banner

    // Step 1 — Ollama not installed
    if (ollama_installed === false) {
      return (
        <>
          {banner}
          <div className="ai-ollama-actions">
            {/* Install progress */}
            {installStatus?.running && (
              <div className="ai-pull-status ai-install-progress">
                <span className="ai-spinner">⟳</span> {t.ai.installInProgress}
              </div>
            )}
            {installStatus?.failed && (
              <div className="ai-pull-status ai-health-fail">
                {t.ai.installFailed}
                {installStatus.log_tail && <pre className="ai-pull-log">{installStatus.log_tail}</pre>}
              </div>
            )}

            {!installStatus?.running && (
              <button
                className="btn btn-warning btn-sm ai-action-btn"
                onClick={handleInstallOllama}
                disabled={installingOllama}
                type="button"
              >
                {installingOllama ? t.ai.installingOllama : `① ${t.ai.installOllama}`}
              </button>
            )}
          </div>
        </>
      )
    }

    // Step 2 — Installed but not running
    if (ollama_installed && !ollama_running) {
      return (
        <>
          {banner}
          <div className="ai-ollama-actions">
            {startingOllama && (
              <div className="ai-pull-status ai-install-progress">
                <span className="ai-spinner">⟳</span> {t.ai.startingOllama}
              </div>
            )}
            {!startingOllama && (
              <button
                className="btn btn-warning btn-sm ai-action-btn"
                onClick={handleStartOllama}
                disabled={startingOllama || testing}
                type="button"
              >
                {`② ${t.ai.startOllama}`}
              </button>
            )}
          </div>
        </>
      )
    }

    // Step 2b — Running but CPU runner missing
    const runner_ok = healthInfo.runner_ok !== false  // default true for backwards compat
    if (ollama_running && !runner_ok) {
      return (
        <>
          {banner}
          <div className="ai-ollama-actions">
            {repairStatus?.running && (
              <div className="ai-pull-status ai-install-progress">
                <span className="ai-spinner">⟳</span> {t.ai.repairInProgress}
              </div>
            )}
            {repairStatus?.runner_ok && (
              <div className="ai-pull-status ai-health-ok">{t.ai.repairDone}</div>
            )}
            {repairStatus?.failed && (
              <div className="ai-pull-status ai-health-fail">
                {t.ai.repairFailed}
                {repairStatus.log_tail && <pre className="ai-pull-log">{repairStatus.log_tail}</pre>}
              </div>
            )}
            {!repairStatus?.running && !repairStatus?.runner_ok && (
              <button
                className="btn btn-warning btn-sm ai-action-btn"
                onClick={handleRepairRunners}
                disabled={repairingRunners}
                type="button"
              >
                {repairingRunners ? t.ai.repairingRunners : t.ai.repairRunners}
              </button>
            )}
          </div>
        </>
      )
    }

    // Step 3 — Running but model missing
    if (ollama_running && !model_found) {
      return (
        <>
          {banner}
          <div className="ai-ollama-actions">
            {pullStatus?.running && (
              <div className="ai-pull-status ai-install-progress">
                <span className="ai-spinner">⟳</span> {t.ai.downloadInProgress}
              </div>
            )}
            {pullStatus?.installed && (
              <div className="ai-pull-status ai-health-ok">{t.ai.modelInstalled}</div>
            )}
            {!pullStatus?.running && !pullStatus?.installed && (
              <button
                className="btn btn-warning btn-sm ai-action-btn"
                onClick={handlePullModel}
                disabled={pullingModel}
                type="button"
              >
                {pullingModel ? t.ai.pullingModel : `③ ${t.ai.pullModel}: ${model}`}
              </button>
            )}
            {pullStatus?.log_tail && !pullStatus.installed && (
              <pre className="ai-pull-log">{pullStatus.log_tail}</pre>
            )}
          </div>
        </>
      )
    }

    // All good — show green banner only
    return banner
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={`ai-assistant${expanded ? ' ai-expanded' : ''}`}>
      <button
        className="ai-toggle-btn"
        onClick={() => setExpanded(v => !v)}
        type="button"
      >
        <span className="ai-toggle-icon">{expanded ? '▼' : '▶'}</span>
        {t.ai.title}
      </button>

      {expanded && (
        <div className="ai-body">
          {/* Model row + buttons */}
          <div className="ai-model-row">
            <div className="ai-model-group">
              <label className="ai-field-label">{t.ai.modelLabel}</label>
              <select
                className="form-input ai-model-input"
                value={model}
                onChange={e => { setModel(e.target.value); setHealthInfo(null); setPullStatus(null); setInstallStatus(null); setRepairStatus(null) }}
              >
                {[...new Set([
                  ...KNOWN_MODELS,
                  ...(healthInfo?.available_models || []),
                  model,
                ])].filter(Boolean).map(m => (
                  <option key={m} value={m}>
                    {m}{healthInfo?.available_models?.length && !healthInfo.available_models.includes(m) ? '（未安装）' : ''}
                  </option>
                ))}
              </select>
            </div>
            <button
              className="btn btn-primary btn-sm ai-test-btn"
              onClick={handleOneClickStart}
              disabled={oneClickStarting || testing || startingOllama || installingOllama}
              type="button"
            >
              {oneClickStarting ? t.ai.oneClickStarting : t.ai.oneClickStart}
            </button>
            <button
              className="btn btn-ghost btn-sm ai-test-btn"
              onClick={handleTest}
              disabled={testing || oneClickStarting || startingOllama || installingOllama}
              type="button"
            >
              {testing ? t.ai.testing : t.ai.testConnection}
            </button>
          </div>

          {renderSetupFlow()}

          {/* Raw script */}
          <div className="ai-input-row">
            <label className="ai-field-label">{t.ai.rawScript}</label>
            <textarea
              className="form-textarea ai-raw-textarea"
              value={rawScript}
              onChange={e => setRawScript(e.target.value)}
              placeholder={t.ai.rawScriptPlaceholder}
              rows={6}
            />
          </div>

          <div className="ai-format-row">
            <button
              className="btn btn-accent btn-sm"
              onClick={handleFormat}
              disabled={loading || !rawScript.trim()}
              type="button"
            >
              {loading ? t.ai.formatting : t.ai.formatWithAi}
            </button>
            {loading && <span className="ai-loading-dots">…</span>}
          </div>

          {error && <div className="ai-error">{error}</div>}

          {result && editResult && (
            <div className="ai-results">
              <div className="ai-results-title">— {t.ai.title} —</div>

              <AiField label={t.form.title} value={editResult.title}
                onChange={v => setField('title', v)} />
              <AiField label={t.form.subtitle} value={editResult.subtitle}
                onChange={v => setField('subtitle', v)} />
              <AiField label={t.form.keywords} value={editResult.keywords}
                onChange={v => setField('keywords', v)} />
              <AiField label={t.ai.openingHook} value={editResult.opening_hook}
                onChange={v => setField('opening_hook', v)} />
              <AiField label={t.ai.cleanScript} value={editResult.clean_script}
                onChange={v => setField('clean_script', v)} rows={5} />

              <div className="ai-field">
                <div className="ai-field-header">
                  <span className="ai-field-label">{t.ai.subtitleLines}</span>
                  <button className="btn btn-ghost btn-xs" onClick={handleCopySubtitles} type="button">
                    {copied ? t.ai.copied : t.ai.copySubtitles}
                  </button>
                </div>
                <textarea
                  className="form-textarea ai-subtitle-textarea"
                  value={editResult.subtitle_lines}
                  onChange={e => setField('subtitle_lines', e.target.value)}
                  rows={8}
                />
              </div>

              <div className="ai-apply-row">
                <button className="btn btn-primary btn-sm" onClick={handleApply} type="button">
                  {applied ? t.ai.applied : t.ai.applyToForm}
                </button>
              </div>
            </div>
          )}

          {!result && !error && !loading && (
            <div className="ai-hint">{t.ai.noResult}</div>
          )}
        </div>
      )}
    </div>
  )
}

function AiField({ label, value, onChange, rows }) {
  return (
    <div className="ai-field">
      <label className="ai-field-label">{label}</label>
      {rows ? (
        <textarea className="form-textarea" value={value}
          onChange={e => onChange(e.target.value)} rows={rows} />
      ) : (
        <input className="form-input" value={value}
          onChange={e => onChange(e.target.value)} />
      )}
    </div>
  )
}
