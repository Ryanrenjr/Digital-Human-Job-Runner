export function SystemReadinessPanel({ readiness, onRefresh, loading }) {
  if (!readiness) return null

  return (
    <section className="readiness-panel" aria-label="系统就绪检查">
      <div className="readiness-heading">
        <div>
          <h2>运行环境</h2>
          <p>{readiness.ready ? '可以开始处理任务' : '有必需组件未就绪'}</p>
        </div>
        <div className="readiness-actions">
          <button className="btn btn-ghost btn-xs" onClick={onRefresh} disabled={loading} type="button">
            {loading ? '检测中' : '重新检测'}
          </button>
          <span className={`readiness-overall ${readiness.ready ? 'is-ready' : 'is-missing'}`}>
            {readiness.ready ? '就绪' : '需要处理'}
          </span>
        </div>
      </div>
      <div className="readiness-grid">
        {readiness.checks.map(check => (
          <div className="readiness-item" key={check.key}>
            <span className={`readiness-dot readiness-${check.status}`} />
            <div className="readiness-copy">
              <strong>{check.label}</strong>
              <span>{check.status === 'ready' ? check.message : '缺失'}</span>
              {!check.required && check.status !== 'ready' && <small>可选</small>}
            </div>
            {check.status !== 'ready' && <span className="readiness-fix" title={check.fix}>修复</span>}
          </div>
        ))}
      </div>
    </section>
  )
}
