import { useRef, useState } from 'react'
import {
  CHINESE_DIALECTS,
  VOICE_LANGUAGES,
  VOICE_STYLE_PRESETS,
} from '../voiceOptions'

const AUDIO_MIN_MINUTES = 30
const AUDIO_TARGET_MINUTES = 60
const AUDIO_IDEAL_MINUTES = 90

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60).toString().padStart(2, '0')
  return `${mins}:${secs}`
}

function formatMinutes(seconds) {
  return (seconds / 60).toFixed(1)
}

function loadMediaDuration(file) {
  return new Promise(resolve => {
    const url = URL.createObjectURL(file)
    const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio')
    media.preload = 'metadata'
    media.onloadedmetadata = () => {
      const duration = media.duration || 0
      URL.revokeObjectURL(url)
      resolve(duration)
    }
    media.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(0)
    }
    media.src = url
  })
}

function QualityItem({ ok, children }) {
  return (
    <li className={ok ? 'quality-ok' : 'quality-warn'}>
      <span className="quality-dot" />
      <span>{children}</span>
    </li>
  )
}

export function TrainingPage({ t, voiceProfiles, onCreateVoiceProfile, onDeleteVoiceProfile }) {
  const videoRef = useRef(null)
  const audioRef = useRef(null)
  const [video, setVideo] = useState(null)
  const [videoDuration, setVideoDuration] = useState(0)
  const [audioFiles, setAudioFiles] = useState([])
  const [profileName, setProfileName] = useState('')
  const [profileLanguage, setProfileLanguage] = useState('zh')
  const [profileDialect, setProfileDialect] = useState('mandarin')
  const [profileStyle, setProfileStyle] = useState('professional_calm')

  const totalAudioSeconds = audioFiles.reduce((sum, f) => sum + f.duration, 0)
  const totalAudioMinutes = totalAudioSeconds / 60
  const audioProgress = Math.min(100, Math.round((totalAudioMinutes / AUDIO_TARGET_MINUTES) * 100))

  const audioLevel =
    totalAudioMinutes >= AUDIO_IDEAL_MINUTES ? t.training.levelIdeal :
    totalAudioMinutes >= AUDIO_TARGET_MINUTES ? t.training.levelReady :
    totalAudioMinutes >= AUDIO_MIN_MINUTES ? t.training.levelMinimum :
    t.training.levelNeedsMore

  const handleVideoChange = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setVideo(file)
    setVideoDuration(await loadMediaDuration(file))
  }

  const handleAudioChange = async (event) => {
    const files = Array.from(event.target.files || [])
    if (!files.length) return
    const enriched = await Promise.all(files.map(async file => ({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      name: file.name,
      size: file.size,
      duration: await loadMediaDuration(file),
    })))
    setAudioFiles(prev => [...prev, ...enriched])
    event.target.value = ''
  }

  const removeAudio = (id) => {
    setAudioFiles(prev => prev.filter(file => file.id !== id))
  }

  const handleSaveProfile = () => {
    const name = profileName.trim()
    if (!name || totalAudioSeconds <= 0) return
    onCreateVoiceProfile({
      id: `voice_${Date.now()}`,
      name,
      language: profileLanguage,
      dialect: profileLanguage === 'zh' ? profileDialect : '',
      style: profileStyle,
      mode: totalAudioMinutes >= AUDIO_MIN_MINUTES ? 'lora_finetune' : 'controllable_clone',
      audioMinutes: Number(totalAudioMinutes.toFixed(1)),
      audioFiles: audioFiles.map(file => ({ name: file.name, duration: file.duration, size: file.size })),
      createdAt: new Date().toISOString(),
    })
    setProfileName('')
    setAudioFiles([])
  }

  return (
    <main className="training-main">
      <section className="training-hero">
        <div>
          <div className="training-kicker">{t.training.kicker}</div>
          <h1>{t.training.title}</h1>
          <p>{t.training.subtitle}</p>
        </div>
        <div className="training-score">
          <span>{formatMinutes(totalAudioSeconds)}</span>
          <small>{t.training.minutesCollected}</small>
        </div>
      </section>

      <section className="training-grid">
        <div className="training-panel">
          <div className="training-panel-head">
            <div>
              <h2>{t.training.voiceProfilesTitle}</h2>
              <p>{t.training.voiceProfilesSubtitle}</p>
            </div>
          </div>

          <div className="profile-form">
            <label className="voice-field">
              <span>{t.training.profileName}</span>
              <input
                className="form-input"
                value={profileName}
                onChange={e => setProfileName(e.target.value)}
                placeholder={t.training.profileNamePlaceholder}
              />
            </label>
            <label className="voice-field">
              <span>{t.form.voiceLanguage}</span>
              <select
                className="form-select"
                value={profileLanguage}
                onChange={e => {
                  setProfileLanguage(e.target.value)
                  if (e.target.value !== 'zh') setProfileDialect('')
                  if (e.target.value === 'zh' && !profileDialect) setProfileDialect('mandarin')
                }}
              >
                {VOICE_LANGUAGES.map(([value, label]) => (
                  <option key={value} value={value}>{t.voiceLanguages?.[value] || label}</option>
                ))}
              </select>
            </label>
            {profileLanguage === 'zh' && (
              <label className="voice-field">
                <span>{t.form.voiceDialect}</span>
                <select className="form-select" value={profileDialect} onChange={e => setProfileDialect(e.target.value)}>
                  {CHINESE_DIALECTS.map(([value, label]) => (
                    <option key={value} value={value}>{t.voiceDialects?.[value] || label}</option>
                  ))}
                </select>
              </label>
            )}
            <label className="voice-field">
              <span>{t.form.voiceStyle}</span>
              <select className="form-select" value={profileStyle} onChange={e => setProfileStyle(e.target.value)}>
                {VOICE_STYLE_PRESETS.map(([value, label]) => (
                  <option key={value} value={value}>{t.voiceStyles?.[value] || label}</option>
                ))}
              </select>
            </label>
          </div>

          <button
            className="btn btn-primary btn-sm profile-save-btn"
            type="button"
            disabled={!profileName.trim() || totalAudioSeconds <= 0}
            onClick={handleSaveProfile}
          >
            {t.training.saveVoiceProfile}
          </button>

          <div className="voice-profile-list">
            {voiceProfiles.filter(profile => profile.id !== 'default_voice').length === 0 ? (
              <div className="audio-empty">{t.training.noVoiceProfiles}</div>
            ) : voiceProfiles.filter(profile => profile.id !== 'default_voice').map(profile => (
              <div className="voice-profile-card" key={profile.id}>
                <div>
                  <strong>{profile.name}</strong>
                  <span>
                    {t.voiceLanguages?.[profile.language] || profile.language}
                    {profile.dialect ? ` · ${t.voiceDialects?.[profile.dialect] || profile.dialect}` : ''}
                    {profile.audioMinutes ? ` · ${profile.audioMinutes} ${t.training.minutes}` : ''}
                  </span>
                </div>
                <button className="btn btn-ghost btn-xs" type="button" onClick={() => onDeleteVoiceProfile(profile.id)}>
                  {t.training.remove}
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="training-panel">
          <div className="training-panel-head">
            <div>
              <h2>{t.training.videoTitle}</h2>
              <p>{t.training.videoSubtitle}</p>
            </div>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => videoRef.current?.click()}>
              {t.training.uploadVideo}
            </button>
            <input
              ref={videoRef}
              type="file"
              accept="video/mp4,video/quicktime,.mp4,.mov"
              hidden
              onChange={handleVideoChange}
            />
          </div>

          <div className="upload-dropzone" onClick={() => videoRef.current?.click()}>
            {video ? (
              <>
                <strong>{video.name}</strong>
                <span>{formatDuration(videoDuration)} · {(video.size / 1024 / 1024).toFixed(1)} MB</span>
              </>
            ) : (
              <>
                <strong>{t.training.videoEmptyTitle}</strong>
                <span>{t.training.videoEmptyText}</span>
              </>
            )}
          </div>

          <ul className="quality-list">
            {t.training.videoRules.map((rule, index) => (
              <QualityItem key={rule} ok={!video || index < 3 || videoDuration >= 8}>
                {rule}
              </QualityItem>
            ))}
          </ul>
        </div>

        <div className="training-panel">
          <div className="training-panel-head">
            <div>
              <h2>{t.training.audioTitle}</h2>
              <p>{t.training.audioSubtitle}</p>
            </div>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => audioRef.current?.click()}>
              {t.training.uploadAudio}
            </button>
            <input
              ref={audioRef}
              type="file"
              accept="audio/wav,audio/mpeg,audio/mp4,audio/x-m4a,.wav,.mp3,.m4a"
              multiple
              hidden
              onChange={handleAudioChange}
            />
          </div>

          <div className="audio-meter">
            <div className="audio-meter-top">
              <strong>{audioLevel}</strong>
              <span>{formatMinutes(totalAudioSeconds)} / {AUDIO_TARGET_MINUTES} {t.training.minutes}</span>
            </div>
            <div className="progress-box-track">
              <div className="progress-box-fill audio-meter-fill" style={{ width: `${audioProgress}%` }} />
            </div>
            <div className="audio-meter-scale">
              <span>{AUDIO_MIN_MINUTES} {t.training.minLabel}</span>
              <span>{AUDIO_TARGET_MINUTES} {t.training.targetLabel}</span>
              <span>{AUDIO_IDEAL_MINUTES}+ {t.training.idealLabel}</span>
            </div>
          </div>

          <div className="audio-file-list">
            {audioFiles.length === 0 ? (
              <div className="audio-empty">{t.training.audioEmpty}</div>
            ) : audioFiles.map(file => (
              <div className="audio-file" key={file.id}>
                <div>
                  <strong>{file.name}</strong>
                  <span>{formatDuration(file.duration)} · {(file.size / 1024 / 1024).toFixed(1)} MB</span>
                </div>
                <button className="btn btn-ghost btn-xs" type="button" onClick={() => removeAudio(file.id)}>
                  {t.training.remove}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="training-panel training-wide">
        <div className="training-panel-head">
          <div>
            <h2>{t.training.standardTitle}</h2>
            <p>{t.training.standardSubtitle}</p>
          </div>
        </div>
        <div className="standard-grid">
          <div>
            <h3>{t.training.audioStandardTitle}</h3>
            <ul className="quality-list">
              {t.training.audioRules.map(rule => <QualityItem key={rule} ok>{rule}</QualityItem>)}
            </ul>
          </div>
          <div>
            <h3>{t.training.trainingPlanTitle}</h3>
            <ol className="training-steps">
              {t.training.trainingSteps.map(step => <li key={step}>{step}</li>)}
            </ol>
          </div>
        </div>
      </section>
    </main>
  )
}
