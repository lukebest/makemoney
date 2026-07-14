import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

export function Panel({
  title,
  eyebrow,
  action,
  className = '',
  children,
}: {
  title?: string
  eyebrow?: string
  action?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || eyebrow || action) && (
        <div className="panel-head">
          <div>
            {eyebrow && <span className="panel-kicker">{eyebrow}</span>}
            {title && <h2>{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Button({
  tone = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'ghost' | 'danger' }) {
  return <button className={`button button-${tone} ${className}`} {...props} />
}

export function StatusView({
  state,
  message,
  onRetry,
}: {
  state: 'loading' | 'error' | 'empty'
  message?: string
  onRetry?: () => void
}) {
  const content = {
    loading: ['正在接入行情…', '数据列阵中'],
    error: ['数据暂不可用', message || '服务连接失败'],
    empty: ['暂无记录', message || '这里还没有数据'],
  }[state]
  return (
    <div className={`status-view status-${state}`} role={state === 'error' ? 'alert' : 'status'}>
      <span className="status-mark" aria-hidden="true">{state === 'loading' ? '◌' : state === 'error' ? '!' : '空'}</span>
      <strong>{content[0]}</strong>
      <small>{content[1]}</small>
      {onRetry && state === 'error' && <Button tone="ghost" onClick={onRetry}>重新连接</Button>}
    </div>
  )
}

export function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: 'gain' | 'loss' | 'neutral'
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone ? tone : ''}>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}

export const money = (value: number) =>
  new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(value || 0)

export const percent = (value: number) => `${value > 0 ? '+' : ''}${Number(value || 0).toFixed(2)}%`
