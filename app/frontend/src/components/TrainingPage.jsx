import { useRef, useState } from 'react'
import {
  CHINESE_DIALECTS,
  VOICE_LANGUAGES,
  VOICE_STYLE_PRESETS,
} from '../voiceOptions'

const AUDIO_MIN_MINUTES = 30
const AUDIO_TARGET_MINUTES = 60
const AUDIO_IDEAL_MINUTES = 90
const SOUND_SOURCE_ACCEPT = [
  'audio/wav',
  'audio/mpeg',
  'audio/mp4',
  'audio/x-m4a',
  'video/mp4',
  'video/quicktime',
  'video/webm',
  '.wav',
  '.mp3',
  '.m4a',
  '.mp4',
  '.mov',
  '.webm',
].join(',')

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60).toString().padStart(2, '0')
  return `${mins}:${secs}`
}

function formatMinutes(seconds) {
  return (seconds / 60).toFixed(1)
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0M'
  return `${(bytes / 1024 / 1024).toFixed(1)}M`
}

function loadMediaInfo(file) {
  return new Promise(resolve => {
    const url = URL.createObjectURL(file)
    const media = document.createElement(file.type.startsWith('video/') ? 'video' : 'audio')
    media.preload = 'metadata'
    media.onloadedmetadata = () => {
      const info = {
        duration: media.duration || 0,
        width: media.videoWidth || 0,
        height: media.videoHeight || 0,
      }
      URL.revokeObjectURL(url)
      resolve(info)
    }
    media.onerror = () => {
      URL.revokeObjectURL(url)
      resolve({ duration: 0, width: 0, height: 0 })
    }
    media.src = url
  })
}

function getSoundSourceType(file) {
  if (file.type.startsWith('video/') || /\.(mp4|mov|webm)$/i.test(file.name)) return 'video'
  return 'audio'
}

function getScoreLevel(score, t) {
  if (score >= 85) return t.training.scoreExcellent
  if (score >= 70) return t.training.scoreGood
  if (score >= 50) return t.training.scoreUsable
  return t.training.scoreNeedsWork
}

function scoreVideo(video, videoInfo, t) {
  if (!video) {
    return {
      score: 0,
      level: t.training.scoreWaiting,
      checks: [
        { ok: false, text: t.training.videoScoreUploadFirst },
      ],
    }
  }

  const duration = videoInfo.duration || 0
  const width = videoInfo.width || 0
  const height = videoInfo.height || 0
  const isCommonFormat = /video\/(mp4|quicktime)/.test(video.type) || /\.(mp4|mov)$/i.test(video.name)
  const hasGoodDuration = duration >= 10 && duration <= 30
  const hasUsableDuration = duration >= 8 && duration <= 45
  const hasGoodResolution = width >= 1920 && height >= 1080
  const hasUsableResolution = width >= 1280 && height >= 720

  let score = 0
  score += hasGoodDuration ? 30 : hasUsableDuration ? 20 : 8
  score += hasGoodResolution ? 30 : hasUsableResolution ? 22 : width && height ? 10 : 0
  score += isCommonFormat ? 20 : 8
  score += video.size > 2 * 1024 * 1024 ? 10 : 4
  score += duration > 0 ? 10 : 0

  const capped = Math.min(100, score)
  return {
    score: capped,
    level: getScoreLevel(capped, t),
    checks: [
      { ok: hasGoodDuration, text: hasGoodDuration ? t.training.videoScoreDurationGood : t.training.videoScoreDurationWarn },
      { ok: hasUsableResolution, text: hasUsableResolution ? `${t.training.videoScoreResolutionGood} ${width || '-'}×${height || '-'}` : t.training.videoScoreResolutionWarn },
      { ok: isCommonFormat, text: isCommonFormat ? t.training.videoScoreFormatGood : t.training.videoScoreFormatWarn },
      { ok: true, text: t.training.videoScoreManualCheck },
    ],
  }
}

function scoreAudio(audioFiles, totalAudioMinutes, t) {
  if (!audioFiles.length) {
    return {
      score: 0,
      level: t.training.scoreWaiting,
      checks: [
        { ok: false, text: t.training.audioScoreUploadFirst },
      ],
    }
  }

  const commonFormats = audioFiles.filter(file => /\.(wav|mp3|m4a|mp4|mov|webm)$/i.test(file.name)).length
  const usableClips = audioFiles.filter(file => file.duration >= 10).length
  const longEnoughClips = audioFiles.filter(file => file.duration >= 30).length
  const formatRatio = commonFormats / audioFiles.length
  const usableRatio = usableClips / audioFiles.length

  let score = 0
  score += totalAudioMinutes >= AUDIO_IDEAL_MINUTES ? 45 : totalAudioMinutes >= AUDIO_TARGET_MINUTES ? 38 : totalAudioMinutes >= AUDIO_MIN_MINUTES ? 28 : Math.min(24, totalAudioMinutes * 0.8)
  score += audioFiles.length >= 10 ? 18 : audioFiles.length >= 5 ? 14 : audioFiles.length >= 2 ? 9 : 4
  score += usableRatio === 1 ? 16 : usableRatio >= 0.8 ? 12 : 6
  score += formatRatio === 1 ? 12 : formatRatio >= 0.8 ? 9 : 4
  score += longEnoughClips >= 3 ? 9 : longEnoughClips >= 1 ? 6 : 2

  const capped = Math.min(100, Math.round(score))
  return {
    score: capped,
    level: getScoreLevel(capped, t),
    checks: [
      { ok: totalAudioMinutes >= AUDIO_MIN_MINUTES, text: totalAudioMinutes >= AUDIO_MIN_MINUTES ? t.training.audioScoreMinutesGood : t.training.audioScoreMinutesWarn },
      { ok: audioFiles.length >= 5, text: audioFiles.length >= 5 ? t.training.audioScoreClipsGood : t.training.audioScoreClipsWarn },
      { ok: usableRatio >= 0.8, text: usableRatio >= 0.8 ? t.training.audioScoreDurationGood : t.training.audioScoreDurationWarn },
      { ok: formatRatio >= 0.8, text: formatRatio >= 0.8 ? t.training.audioScoreFormatGood : t.training.audioScoreFormatWarn },
      { ok: true, text: t.training.audioScoreManualCheck },
    ],
  }
}

function QualityItem({ ok, children }) {
  return (
    <li className={ok ? 'quality-ok' : 'quality-warn'}>
      <span className="quality-dot" />
      <span>{children}</span>
    </li>
  )
}

export function TrainingPage({
  t,
  voiceProfiles,
  onCreateVoiceProfile,
  onTrainVoiceProfile,
  onDeleteVoiceProfile,
  onUploadAvatarVideo,
  uploadingAvatarVideo,
}) {
  const videoRef = useRef(null)
  const audioRef = useRef(null)
  const [video, setVideo] = useState(null)
  const [videoInfo, setVideoInfo] = useState({ duration: 0, width: 0, height: 0 })
  const [audioFiles, setAudioFiles] = useState([])
  const [profileName, setProfileName] = useState('')
  const [profileLanguage, setProfileLanguage] = useState('zh')
  const [profileDialect, setProfileDialect] = useState('mandarin')
  const [profileStyle, setProfileStyle] = useState('professional_calm')
  const [trainingNotice, setTrainingNotice] = useState('')
  const [trainingBusy, setTrainingBusy] = useState(false)
  const [videoNotice, setVideoNotice] = useState('')

  const totalAudioSeconds = audioFiles.reduce((sum, f) => sum + f.duration, 0)
  const totalAudioMinutes = totalAudioSeconds / 60
  const audioProgress = Math.min(100, Math.round((totalAudioMinutes / AUDIO_TARGET_MINUTES) * 100))
  const remainingTrainingMinutes = Math.max(0, AUDIO_MIN_MINUTES - totalAudioMinutes)
  const canStartTraining = profileName.trim() && totalAudioMinutes >= AUDIO_MIN_MINUTES

  const audioLevel =
    totalAudioMinutes >= AUDIO_IDEAL_MINUTES ? t.training.levelIdeal :
    totalAudioMinutes >= AUDIO_TARGET_MINUTES ? t.training.levelReady :
    totalAudioMinutes >= AUDIO_MIN_MINUTES ? t.training.levelMinimum :
    t.training.levelNeedsMore
  const videoScore = scoreVideo(video, videoInfo, t)
  const audioScore = scoreAudio(audioFiles, totalAudioMinutes, t)
  const overallScore = video && audioFiles.length
    ? Math.round((videoScore.score + audioScore.score) / 2)
    : Math.max(videoScore.score, audioScore.score)

  const handleVideoChange = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setVideoNotice('')
    setVideo(file)
    setVideoInfo(await loadMediaInfo(file))
  }

  const handleSaveVideo = async () => {
    if (!video || !onUploadAvatarVideo) return
    const saved = await onUploadAvatarVideo(video)
    if (saved) {
      setVideoNotice(t.training.videoSaved)
      setVideo(null)
      setVideoInfo({ duration: 0, width: 0, height: 0 })
      if (videoRef.current) videoRef.current.value = ''
    }
  }

  const handleAudioChange = async (event) => {
    const files = Array.from(event.target.files || [])
    if (!files.length) return
    setTrainingNotice('')
    const enriched = await Promise.all(files.map(async file => ({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      file,
      name: file.name,
      size: file.size,
      sourceType: getSoundSourceType(file),
      duration: (await loadMediaInfo(file)).duration,
    })))
    setAudioFiles(prev => [...prev, ...enriched])
    event.target.value = ''
  }

  const removeAudio = (id) => {
    setTrainingNotice('')
    setAudioFiles(prev => prev.filter(file => file.id !== id))
  }

  const createProfileFromCurrentMaterial = (trainingStatus = 'draft') => {
    const name = profileName.trim()
    if (!name || totalAudioSeconds <= 0) return false
    onCreateVoiceProfile({
      id: `voice_${Date.now()}`,
      name,
      language: profileLanguage,
      dialect: profileLanguage === 'zh' ? profileDialect : '',
      style: profileStyle,
      mode: totalAudioMinutes >= AUDIO_MIN_MINUTES ? 'lora_finetune' : 'controllable_clone',
      trainingStatus,
      audioMinutes: Number(totalAudioMinutes.toFixed(1)),
      audioScore: audioScore.score,
      audioFiles: audioFiles.map(file => ({ name: file.name, duration: file.duration, size: file.size, sourceType: file.sourceType })),
      createdAt: new Date().toISOString(),
    })
    setProfileName('')
    setAudioFiles([])
    return true
  }

  const handleSaveProfile = () => {
    if (createProfileFromCurrentMaterial('draft')) {
      setTrainingNotice(t.training.profileSavedAsMaterial)
    }
  }

  const handleStartTraining = async () => {
    if (!canStartTraining) return
    if (!onTrainVoiceProfile) {
      setTrainingNotice(t.training.trainingBackendMissing)
      return
    }
    setTrainingBusy(true)
    setTrainingNotice(t.training.trainingUploading)
    try {
      const profile = await onTrainVoiceProfile({
        name: profileName.trim(),
        language: profileLanguage,
        dialect: profileLanguage === 'zh' ? profileDialect : '',
        style: profileStyle,
        audioMinutes: Number(totalAudioMinutes.toFixed(1)),
        audioScore: audioScore.score,
        files: audioFiles.map(item => item.file).filter(Boolean),
      })
      setProfileName('')
      setAudioFiles([])
      setTrainingNotice(t.training.trainingStartedReal.replace('{name}', profile.name))
    } catch (e) {
      setTrainingNotice(`${t.training.trainingStartFailed}${e.detail || e.message}`)
    } finally {
      setTrainingBusy(false)
    }
  }

  const getTrainingButtonText = () => {
    if (!audioFiles.length) return t.training.trainUploadFirst
    if (totalAudioMinutes < AUDIO_MIN_MINUTES) {
      return t.training.trainNeedMore.replace('{minutes}', remainingTrainingMinutes.toFixed(1))
    }
    if (!profileName.trim()) return t.training.trainNameFirst
    if (trainingBusy) return t.training.trainingStarting
    return t.training.startTraining
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
          <span>{overallScore}</span>
          <small>{t.training.overallScore}</small>
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
            {voiceProfiles.filter(profile => !profile.builtIn && profile.id !== 'default_voice').length === 0 ? (
              <div className="audio-empty">{t.training.noVoiceProfiles}</div>
            ) : voiceProfiles.filter(profile => !profile.builtIn && profile.id !== 'default_voice').map(profile => (
              <div className="voice-profile-card" key={profile.id}>
                <div>
                  <strong>{profile.name}</strong>
                  <em className={`voice-training-state state-${profile.trainingStatus || 'draft'}`}>
                    {t.training.voiceTrainingStates?.[profile.trainingStatus || 'draft']}
                  </em>
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
                <span>{formatDuration(videoInfo.duration)} · {videoInfo.width || '-'}×{videoInfo.height || '-'} · {formatFileSize(video.size)}</span>
              </>
            ) : (
              <>
                <strong>{t.training.videoEmptyTitle}</strong>
                <span>{t.training.videoEmptyText}</span>
              </>
            )}
          </div>

          <div className={`quality-score score-${videoScore.score >= 70 ? 'good' : videoScore.score > 0 ? 'warn' : 'empty'}`}>
            <div className="quality-score-main">
              <span>{videoScore.score}</span>
              <div>
                <strong>{videoScore.level}</strong>
                <small>{t.training.videoScoreLabel}</small>
              </div>
            </div>
            <ul className="quality-score-checks">
              {videoScore.checks.map(check => (
                <QualityItem key={check.text} ok={check.ok}>{check.text}</QualityItem>
              ))}
            </ul>
          </div>

          <ul className="quality-list">
            {t.training.videoRules.map((rule, index) => (
              <QualityItem key={rule} ok={!video || index < 3 || videoInfo.duration >= 8}>
                {rule}
              </QualityItem>
            ))}
          </ul>

          <div className="training-action">
            <div>
              <strong>{t.training.videoActionTitle}</strong>
              <span>{t.training.videoActionHint}</span>
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={!video || uploadingAvatarVideo}
              onClick={handleSaveVideo}
            >
              {uploadingAvatarVideo ? t.training.videoSaving : video ? t.training.saveVideo : t.training.videoUploadFirst}
            </button>
          </div>
          {videoNotice ? <div className="training-notice">{videoNotice}</div> : null}
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
              accept={SOUND_SOURCE_ACCEPT}
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

          <div className={`quality-score score-${audioScore.score >= 70 ? 'good' : audioScore.score > 0 ? 'warn' : 'empty'}`}>
            <div className="quality-score-main">
              <span>{audioScore.score}</span>
              <div>
                <strong>{audioScore.level}</strong>
                <small>{t.training.audioScoreLabel}</small>
              </div>
            </div>
            <ul className="quality-score-checks">
              {audioScore.checks.map(check => (
                <QualityItem key={check.text} ok={check.ok}>{check.text}</QualityItem>
              ))}
            </ul>
          </div>

          <div className="audio-file-list">
            {audioFiles.length === 0 ? (
              <div className="audio-empty">{t.training.audioEmpty}</div>
            ) : audioFiles.map(file => (
              <div className="audio-file" key={file.id}>
                <div>
                  <strong>{file.name}</strong>
                  <span>
                    {file.sourceType === 'video' ? t.training.sourceVideoAudio : t.training.sourceAudio}
                    {' · '}
                    {formatDuration(file.duration)}
                    {' · '}
                    {formatFileSize(file.size)}
                  </span>
                </div>
                <button className="btn btn-ghost btn-xs" type="button" onClick={() => removeAudio(file.id)}>
                  {t.training.remove}
                </button>
              </div>
            ))}
          </div>

          <div className="training-action">
            <div>
              <strong>{t.training.trainingActionTitle}</strong>
              <span>{t.training.trainingActionHint}</span>
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={!canStartTraining || trainingBusy}
              onClick={handleStartTraining}
            >
              {getTrainingButtonText()}
            </button>
          </div>
          {trainingNotice ? <div className="training-notice">{trainingNotice}</div> : null}
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
