import { useEffect, useRef, useState } from 'react'
import { BackgroundPicker }    from './BackgroundPicker'
import { AIScriptAssistant }   from './AIScriptAssistant'
import {
  CHINESE_DIALECTS,
  VOICE_LANGUAGES,
  VOICE_MODES,
  VOICE_PACE_PRESETS,
  VOICE_QUALITY_PRESETS,
  VOICE_STYLE_PRESETS,
} from '../voiceOptions'

const RECOMMENDED_VOICE_ID = 'voice_20260908_142126_748786_ryan_10'
const RECOMMENDED_VOICE_NAME = 'Ryan 10分钟测试版'

const INITIAL = {
  title: '',
  subtitle: '',
  keywords: '',
  script: '',
  background_id: '',
  voice_id: 'default_voice',
  voice_language: 'zh',
  voice_dialect: 'mandarin',
  voice_mode: 'basic_tts',
  voice_style: 'professional_natural',
  voice_pace: 'natural',
  voice_quality: 'high',
  voice_seed: 'auto',
  voice_best_of: null,
  voice_text_normalize: true,
  voice_reference_cleanup: false,
  voice_retry_badcase: true,
  output_type: 'clean_video',
  outro_id: null,
  subtitle_enabled: true,
  shutdown_after_done: false,
  // AI-generated extras (sent with job create but not shown as form fields)
  subtitle_lines: null,
  opening_hook: null,
  script_source: null,
  script_model: null,
}

export function CreateJobForm({
  backgrounds,
  onSubmit,
  isSubmitting,
  onUploadBackground,
  onDeleteBackground,
  uploadingBackground,
  t,
  voiceProfiles = [],
  outros = [],
}) {
  const [fields, setFields] = useState(INITIAL)
  const [errors, setErrors] = useState({})
  const recommendationApplied = useRef(false)
  const selectedVoiceProfile = voiceProfiles.find(profile => profile.id === fields.voice_id)
  const selectedVoiceIsTrained = selectedVoiceProfile?.trainingStatus === 'finished'
  const isHiFiClone = fields.voice_mode === 'ultimate_clone'

  useEffect(() => {
    if (recommendationApplied.current || fields.voice_id !== 'default_voice') return
    const recommended = voiceProfiles.find(profile => profile.id === RECOMMENDED_VOICE_ID)
      || voiceProfiles.find(profile => profile.name === RECOMMENDED_VOICE_NAME)
    if (!recommended) return
    recommendationApplied.current = true
    setFields(current => ({
      ...current,
      voice_id: recommended.id,
      voice_language: recommended.language || 'zh',
      voice_dialect: recommended.language === 'zh' ? (recommended.dialect || 'mandarin') : '',
      voice_mode: 'controllable_clone',
      voice_style: 'professional_natural',
      voice_pace: 'natural',
      voice_quality: 'high',
      voice_seed: 'auto',
    }))
  }, [fields.voice_id, voiceProfiles])

  useEffect(() => {
    if (fields.output_type !== 'clean_video') return
    if (fields.background_id || backgrounds.length === 0) return
    setFields(f => ({ ...f, background_id: backgrounds[0].id }))
  }, [backgrounds, fields.background_id, fields.output_type])

  const set = (key, value) => {
    setFields(f => {
      const next = { ...f, [key]: value }
      if (key === 'output_type' && value !== 'clean_video') next.outro_id = null
      if (key === 'voice_language' && value !== 'zh') next.voice_dialect = ''
      if (key === 'voice_language' && value === 'zh' && !next.voice_dialect) next.voice_dialect = 'mandarin'
      if (key === 'voice_id') {
        const profile = voiceProfiles.find(p => p.id === value)
        if (profile) {
          next.voice_language = profile.language || 'zh'
          next.voice_dialect = profile.language === 'zh' ? (profile.dialect || 'mandarin') : ''
          next.voice_style = profile.style || 'professional_natural'
          next.voice_mode = profile.mode || (profile.id === 'default_voice' ? 'basic_tts' : 'trained_profile')
          if (profile.id === RECOMMENDED_VOICE_ID || profile.name === RECOMMENDED_VOICE_NAME) {
            next.voice_mode = 'controllable_clone'
            next.voice_style = 'professional_natural'
            next.voice_pace = 'natural'
          }
        }
      }
      return next
    })
    if (errors[key]) setErrors(e => ({ ...e, [key]: null }))
  }

  const validate = () => {
    const e = {}
    if (!fields.title.trim())  e.title  = t.form.required
    if (!fields.script.trim()) e.script = t.form.required
    if (fields.output_type === 'clean_video' && !fields.background_id)
      e.background_id = t.form.backgroundRequired
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const submit = (andRun) => {
    if (!validate()) return
    const keywords = fields.keywords
      .split(',')
      .map(k => k.trim())
      .filter(Boolean)
    onSubmit({ ...fields, keywords }, andRun)
  }

  const inputProps = (key) => ({
    className: 'form-input',
    value: fields[key],
    onChange: e => set(key, e.target.value),
  })

  const handleDeleteBackground = (bgId) => {
    if (fields.background_id === bgId) set('background_id', '')
    onDeleteBackground(bgId)
  }

  const handleAiApply = (result) => {
    setFields(f => ({
      ...f,
      title:         result.title    || f.title,
      subtitle:      result.subtitle || f.subtitle,
      keywords:      Array.isArray(result.keywords)
                       ? result.keywords.join(', ')
                       : (result.keywords || f.keywords),
      script:        result.script   || f.script,
      subtitle_lines: result.subtitle_lines || null,
      opening_hook:   result.opening_hook   || null,
      script_source:  result.script_source  || null,
      script_model:   result.script_model   || null,
    }))
    // Clear any validation errors that were blocking
    setErrors({})
  }

  return (
    <div className="card">
      <div className="card-title">{t.form.cardTitle}</div>

      {/* AI Script Assistant — collapsible, optional */}
      <AIScriptAssistant onApply={handleAiApply} t={t} />

      <div className="form-group">
        <label className="form-label">{t.form.title} <span className="req">*</span></label>
        <input {...inputProps('title')} placeholder={t.form.titlePlaceholder} />
        {errors.title && <div className="form-error">{errors.title}</div>}
      </div>

      <div className="form-group">
        <label className="form-label">{t.form.subtitle}</label>
        <input {...inputProps('subtitle')} placeholder={t.form.subtitlePlaceholder} />
      </div>

      <div className="form-group">
        <label className="form-label">{t.form.keywords}</label>
        <input {...inputProps('keywords')} placeholder={t.form.keywordsPlaceholder} />
        <div className="form-hint">{t.form.keywordsHint}</div>
      </div>

      <div className="form-group">
        <label className="form-label">{t.form.script} <span className="req">*</span></label>
        <textarea
          className="form-textarea"
          value={fields.script}
          onChange={e => set('script', e.target.value)}
          placeholder={t.form.scriptPlaceholder}
        />
        {errors.script && <div className="form-error">{errors.script}</div>}
      </div>

      <div className="form-group voice-settings-panel">
        <div className="voice-settings-head">
          <div>
            <label className="form-label">{t.form.voiceSettings}</label>
            <div className="form-hint">{t.form.voiceSettingsHint}</div>
          </div>
        </div>

        <div className="voice-settings-grid">
          <label className="voice-field">
            <span>{t.form.voicePerson}</span>
            <select
              className="form-select"
              value={fields.voice_id}
              onChange={e => set('voice_id', e.target.value)}
            >
              {voiceProfiles.map(profile => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </label>

          <label className="voice-field">
            <span>{t.form.voiceLanguage}</span>
            <select
              className="form-select"
              value={fields.voice_language}
              disabled={selectedVoiceIsTrained}
              onChange={e => set('voice_language', e.target.value)}
            >
              {VOICE_LANGUAGES.map(([value, label]) => (
                <option key={value} value={value}>{t.voiceLanguages?.[value] || label}</option>
              ))}
            </select>
          </label>

          {fields.voice_language === 'zh' && (
            <label className="voice-field">
              <span>{t.form.voiceDialect}</span>
              <select
                className="form-select"
                value={fields.voice_dialect}
                disabled={selectedVoiceIsTrained}
                onChange={e => set('voice_dialect', e.target.value)}
              >
                {CHINESE_DIALECTS.map(([value, label]) => (
                  <option key={value} value={value}>{t.voiceDialects?.[value] || label}</option>
                ))}
              </select>
            </label>
          )}

          <label className="voice-field">
            <span>{t.form.voiceMode}</span>
            <select className="form-select" value={fields.voice_mode} onChange={e => set('voice_mode', e.target.value)}>
              {VOICE_MODES.map(([value, label]) => (
                <option key={value} value={value}>{t.voiceModes?.[value] || label}</option>
              ))}
            </select>
          </label>

          <label className="voice-field">
            <span>{t.form.voiceStyle}</span>
            <select className="form-select" value={fields.voice_style} disabled={isHiFiClone} onChange={e => set('voice_style', e.target.value)}>
              {VOICE_STYLE_PRESETS.map(([value, label]) => (
                <option key={value} value={value}>{t.voiceStyles?.[value] || label}</option>
              ))}
            </select>
          </label>

          <label className="voice-field">
            <span>{t.form.voicePace}</span>
            <select className="form-select" value={fields.voice_pace} disabled={isHiFiClone} onChange={e => set('voice_pace', e.target.value)}>
              {VOICE_PACE_PRESETS.map(([value, label]) => (
                <option key={value} value={value}>{t.voicePaces?.[value] || label}</option>
              ))}
            </select>
          </label>

          <label className="voice-field">
            <span>{t.form.voiceQuality}</span>
            <select className="form-select" value={fields.voice_quality} onChange={e => set('voice_quality', e.target.value)}>
              {VOICE_QUALITY_PRESETS.map(([value, label]) => (
                <option key={value} value={value}>{t.voiceQualities?.[value] || label}</option>
              ))}
            </select>
          </label>

          <label className="voice-field">
            <span>{t.form.voiceSeed}</span>
            <input
              className="form-input"
              value={fields.voice_seed}
              inputMode="numeric"
              placeholder={t.form.voiceSeedPlaceholder}
              onChange={e => set('voice_seed', e.target.value.trim() || 'auto')}
            />
          </label>
        </div>
        {selectedVoiceIsTrained && (
          <div className="form-hint voice-fixed-hint">{t.form.trainedVoiceFixedHint}</div>
        )}
        {isHiFiClone && (
          <div className="form-hint voice-fixed-hint">{t.form.hifiStyleHint}</div>
        )}
      </div>

      {/* ── Background picker (clean_video only) ── */}
      {fields.output_type === 'clean_video' && (
        <div className="form-group">
          <label className="form-label">{t.form.background} <span className="req">*</span></label>
          <BackgroundPicker
            backgrounds={backgrounds}
            selectedId={fields.background_id}
            onSelect={id => set('background_id', id)}
            onDelete={handleDeleteBackground}
            onUpload={onUploadBackground}
            uploading={uploadingBackground}
            manageAssets={false}
            t={t}
          />
          {errors.background_id && <div className="form-error">{errors.background_id}</div>}
        </div>
      )}

      {fields.output_type === 'clean_video' && (
        <div className="form-group">
          <label className="form-label">{t.form.outro}</label>
          <select
            className="form-select"
            value={fields.outro_id || ''}
            onChange={e => set('outro_id', e.target.value || null)}
          >
            <option value="">{t.form.noOutro}</option>
            {outros.map(outro => (
              <option key={outro.id} value={outro.id}>
                {outro.name}{outro.duration ? ` · ${Number(outro.duration).toFixed(1)}s` : ''}
              </option>
            ))}
          </select>
          <div className="form-hint">{t.form.outroHint}</div>
        </div>
      )}

      {fields.output_type === 'clean_video' && (
        <div className={`form-group caption-settings-panel${fields.subtitle_enabled ? ' enabled' : ''}`}>
          <div className="caption-settings-main">
            <div>
              <div className="caption-settings-title">{t.form.captionPresetTitle}</div>
              <div className="caption-settings-name">{t.form.captionPresetName}</div>
            </div>
            <label className="ios-switch" title={t.form.autoSubtitles}>
              <input
                type="checkbox"
                checked={fields.subtitle_enabled}
                onChange={e => set('subtitle_enabled', e.target.checked)}
              />
              <span className="ios-switch-track" aria-hidden="true" />
            </label>
          </div>
          <div className="caption-settings-tags">
            <span>{t.form.captionTagReadable}</span>
            <span>{t.form.captionTagOneLine}</span>
            <span>{t.form.captionTagAutoBreak}</span>
          </div>
          <div className="caption-style-preview" aria-hidden="true">
            <span>{t.form.captionPreview}</span>
          </div>
          <div className="form-hint">{t.form.captionPresetHint}</div>
        </div>
      )}

      <div className="form-group">
        <label className="form-label">{t.form.outputType}</label>
        <div className="output-type-toggle">
          <button
            type="button"
            className={`output-type-btn${fields.output_type === 'clean_video' ? ' active' : ''}`}
            onClick={() => set('output_type', 'clean_video')}
          >
            {t.form.outputTypeVideo}
          </button>
          <button
            type="button"
            className={`output-type-btn${fields.output_type === 'voice_only' ? ' active' : ''}`}
            onClick={() => set('output_type', 'voice_only')}
          >
            {t.form.outputTypeVoice}
          </button>
        </div>
      </div>

      <div className="form-group">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={fields.shutdown_after_done}
            onChange={e => set('shutdown_after_done', e.target.checked)}
          />
          <span className="checkbox-text">{t.form.shutdownAfterDone}</span>
          <span className="checkbox-warn"> {t.form.shutdownWarn}</span>
        </label>
      </div>

      <div className="form-actions">
        <button
          className="btn btn-primary"
          onClick={() => submit(false)}
          disabled={isSubmitting}
        >
          {isSubmitting ? t.form.creating : t.form.createJob}
        </button>
        <button
          className="btn btn-accent"
          onClick={() => submit(true)}
          disabled={isSubmitting}
        >
          {isSubmitting ? t.form.working : t.form.createAndRun}
        </button>
      </div>
    </div>
  )
}
