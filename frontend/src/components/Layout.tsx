import { NavLink, Outlet, useLocation } from 'react-router-dom'

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
  const active = links.find((link) => link.end ? location.pathname === '/' : location.pathname.startsWith(link.to))

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
        <div className="market-clock">
          <span className="live-dot" />
          <span>终端已连接</span>
        </div>
      </aside>

      <div className="main-wrap">
        <div className="top-strip" aria-hidden="true">
          <span>{active?.label || '知止终端'}</span>
          <i />
          <span>纪律是收益的边界</span>
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
