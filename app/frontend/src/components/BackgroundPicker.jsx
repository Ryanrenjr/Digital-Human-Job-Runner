import { useRef, useState } from 'react'
import * as api from '../api'

function BgCard({ bg, selected, onSelect, onDelete, manageAssets, t }) {
  const thumbUrl = api.getThumbnailUrl(bg.id)

  return (
    <div
      className={`bg-card${selected ? ' bg-card-selected' : ''}`}
      onClick={() => onSelect(bg.id)}
      title={bg.name}
    >
      <div className="bg-card-thumb">
        <img
          src={thumbUrl}
          alt={bg.name}
          onError={e => { e.currentTarget.style.display = 'none' }}
        />
        <span className={`bg-type-badge ${bg.type}`}>
          {bg.type === 'builtin' ? t.backgrounds.builtin : t.backgrounds.custom}
        </span>
        {selected && <span className="bg-selected-mark">✓</span>}
      </div>
      <div className="bg-card-info">
        <div className="bg-card-name">{bg.name}</div>
        <div className="bg-card-actions">
          <button
            className={`btn btn-xs${selected ? ' btn-primary' : ' btn-ghost'}`}
            onClick={e => { e.stopPropagation(); onSelect(bg.id) }}
          >
            {selected ? t.backgrounds.selected : t.backgrounds.select}
          </button>
          {manageAssets && bg.type === 'custom' && (
            <button
              className="btn btn-danger btn-xs"
              title={t.backgrounds.deleteBackground}
              onClick={e => { e.stopPropagation(); onDelete(bg.id) }}
            >
              ✕
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function BackgroundPicker({
  backgrounds,
  selectedId,
  onSelect,
  onDelete,
  onUpload,
  uploading,
  manageAssets = true,
  t,
}) {
  const fileRef = useRef(null)
  const [showReqs, setShowReqs] = useState(false)

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    await onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="bg-picker">
      <div className="bg-picker-header">
        <span className="bg-picker-title">{t.backgrounds.library}</span>
        {manageAssets && (
          <>
            <button
              className={`btn btn-ghost btn-xs bg-req-toggle${showReqs ? ' active' : ''}`}
              onClick={() => setShowReqs(v => !v)}
              title={t.backgrounds.requirementsTitle}
            >
              ℹ
            </button>
            <button
              className="btn btn-ghost btn-xs"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? t.backgrounds.uploading : t.backgrounds.uploadMp4}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".mp4,video/mp4"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
          </>
        )}
      </div>

      {manageAssets && showReqs && (
        <div className="bg-requirements">
          <div className="bg-req-title">{t.backgrounds.requirementsTitle}</div>
          <ol className="bg-req-list">
            {t.backgrounds.requirements.map((req, i) => (
              <li key={i}>{req}</li>
            ))}
          </ol>
        </div>
      )}

      {backgrounds.length === 0 ? (
        <div className="bg-grid-empty">—</div>
      ) : (
        <div className="bg-grid">
          {backgrounds.map(bg => (
            <BgCard
              key={bg.id}
              bg={bg}
              selected={bg.id === selectedId}
              onSelect={onSelect}
              onDelete={onDelete}
              manageAssets={manageAssets}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  )
}
