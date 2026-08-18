import { FormEvent, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api, nearSessionFlip, tapeClosed } from '../api'
import type { SessionStatus } from '../types'

const links = [
  { to: '/', label: '大盘温度', short: '温度', glyph: '温', end: true },
  { to: '/preferred', label: '优选个股', short: '优选', glyph: '择' },
  { to: '/stock', label: '个股诊断', short: '诊股', glyph: '析' },
  { to: '/positions', label: '仓位管理', short: '仓位', glyph: '仓' },
  { to: '/trades', label: '交易执行', short: '交易', glyph: '执' },
  { to: '/review', label: '收盘复盘', short: '复盘', glyph: '省' },
]

export function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const active = links.find((link) => link.end ? location.pathname === '/' : location.pathname.startsWith(link.to))
  const [session, setSession] = useState<SessionStatus>()
  const [query, setQuery] = useState('')

  useEffect(() => {
    const load = () => {
      void api.today().then((brief) => {
        setSession(brief.session)
        if (!tapeClosed(brief.session.code)) {
          void api.preferred().catch(() => undefined)
        }
      }).catch(() => undefined)
    }
    load()
    void api.market().catch(() => undefined)
    void api.mainline().catch(() => undefined)
    const retry = window.setTimeout(() => load(), 4000)
    const timer = window.setInterval(() => {
      void api.today(nearSessionFlip()).then((brief) => {
        setSession(brief.session)
        if (!tapeClosed(brief.session.code)) {
          void api.preferred().catch(() => undefined)
        }
      }).catch(() => undefined)
    }, 15_000)
    return () => {
      window.clearTimeout(retry)
      window.clearInterval(timer)
    }
  }, [])

  const jump = (event: FormEvent) => {
    event.preventDefault()
    const code = query.replace(/\D/g, '')
    if (code.length < 5) return
    navigate(`/stock?code=${code}`)
    setQuery('')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="知止终端首页">
          <span className="brand-seal">止</span>
          <span><strong>知止</strong><small>A股纪律交易终端</small></span>
        </NavLink>
        <nav aria-label="主导航">
          {links.map((link, index) => (
            <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-index">{String(index + 1).padStart(2, '0')}</span>
              <span className="nav-glyph">{link.glyph}</span>
              <span>{link.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-rule">
          <span>交易守则</span>
          <blockquote>看不懂，不做。<br />没计划，不动。</blockquote>
        </div>
        <div className={`market-clock session-${session?.code || 'unknown'}`}>
          <span className={session?.trading ? 'live-dot' : 'live-dot idle'} />
          <span>{session ? `${session.label} ${session.clock}` : '正在对时'}</span>
        </div>
      </aside>

      <div className="main-wrap">
        <div className="top-strip">
          <span>{active?.label || '知止终端'}</span>
          <i />
          <span>{session?.action || '纪律是收益的边界'}</span>
          <form className="jump-form" onSubmit={jump}>
            <label className="sr-only" htmlFor="jump-code">跳转股票代码</label>
            <input id="jump-code" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="代码直达" inputMode="numeric" maxLength={8} />
          </form>
          <em>{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' })}</em>
        </div>
        <main id="main-content"><Outlet /></main>
      </div>

      <nav className="mobile-nav" aria-label="移动端主导航">
        {links.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.end} aria-label={link.label}>
            <span>{link.glyph}</span><small>{link.short}</small>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
