import type {
  AIResult,
  AIStatus,
  AITradeReviewInput,
  MarketOverview,
  Position,
  PositionInput,
  PreferredStocksData,
  ReviewData,
  Settings,
  StockAnalysis,
  Trade,
  TradeInput,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || '/api'
type JsonObject = Record<string, unknown>

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      message = body.detail || body.message || message
    } catch {
      // Keep status-based fallback for non-JSON errors.
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  const body = await response.json()
  return (body?.data ?? body) as T
}

function listFrom<T>(value: unknown, keys: string[]): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') {
    const object = value as Record<string, unknown>
    for (const key of keys) if (Array.isArray(object[key])) return object[key] as T[]
  }
  return []
}

const objectFrom = (value: unknown): JsonObject =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}

const numberFrom = (value: unknown, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const stringFrom = (value: unknown, fallback = '') =>
  typeof value === 'string' ? value : fallback

function normalizeMarket(value: unknown): MarketOverview {
  const raw = objectFrom(value)
  const phase = objectFrom(raw.phase)
  const breadth = objectFrom(raw.breadth)
  const advanceRatio = numberFrom(breadth.advance_ratio, 0.5)
  const mainIndex = listFrom<JsonObject>(raw.indexes, []).find((item) => item.code === '000001')
  const momentum = Math.max(-10, Math.min(10, numberFrom(mainIndex?.change_pct) * 4))
  return {
    phase: (stringFrom(phase.code, 'spring') as MarketOverview['phase']),
    phaseLabel: stringFrom(phase.name, '春播期'),
    score: Math.round(Math.max(0, Math.min(100, advanceRatio * 80 + 10 + momentum))),
    summary: stringFrom(phase.strategy, '观察待机，小仓验证市场方向'),
    indices: listFrom<JsonObject>(raw.indexes, []).map((item) => ({
      code: stringFrom(item.code),
      name: stringFrom(item.name),
      value: numberFrom(item.price ?? item.value),
      change: numberFrom(item.change_pct ?? item.change),
      turnover: numberFrom(item.amount ?? item.turnover),
    })),
    advance: numberFrom(breadth.up ?? raw.advance),
    decline: numberFrom(breadth.down ?? raw.decline),
    limitUp: numberFrom(breadth.limit_up ?? raw.limitUp),
    limitDown: numberFrom(breadth.limit_down ?? raw.limitDown),
    fried: numberFrom(breadth.fried ?? raw.fried),
    volumeRatio: numberFrom(breadth.volume_ratio ?? raw.volumeRatio, 1),
    boardDate: stringFrom(breadth.board_date ?? raw.boardDate),
    updatedAt: stringFrom(raw.updated_at ?? raw.updatedAt),
    source: stringFrom(raw.source),
    fallbackReason: stringFrom(raw.fallback_reason),
  }
}

function normalizeStock(value: unknown): StockAnalysis {
  const raw = objectFrom(value)
  const checks = listFrom<JsonObject>(raw.checklist ?? raw.checks, [])
  const chan = objectFrom(raw.chan)
  const pivot = chan.pivot ? objectFrom(chan.pivot) : null
  const thirdBuy = chan.third_buy ? objectFrom(chan.third_buy) : null
  const trendCode = stringFrom(raw.trend)
  const trendNames: Record<string, string> = {
    up: '多头排列',
    down: '空头排列',
    sideways: '均线缠绕',
    insufficient: '数据不足',
  }
  return {
    code: stringFrom(raw.code),
    name: stringFrom(raw.name),
    price: numberFrom(raw.price),
    change: numberFrom(raw.change_pct ?? raw.change),
    trend: trendNames[trendCode] || trendCode || '待确认',
    score: checks.length ? Math.round(checks.filter((item) => Boolean(item.passed)).length / checks.length * 100) : 0,
    summary: stringFrom(raw.summary),
    checks: checks.map((item) => ({
      label: stringFrom(item.label),
      passed: Boolean(item.passed),
      detail: stringFrom(item.detail),
    })),
    klines: listFrom<JsonObject>(raw.klines, []).map((bar) => ({
      date: stringFrom(bar.date),
      open: numberFrom(bar.open),
      close: numberFrom(bar.close),
      low: numberFrom(bar.low),
      high: numberFrom(bar.high),
      volume: numberFrom(bar.volume),
      ma5: bar.ma5 == null ? undefined : numberFrom(bar.ma5),
      ma10: bar.ma10 == null ? undefined : numberFrom(bar.ma10),
      ma20: bar.ma20 == null ? undefined : numberFrom(bar.ma20),
      ma60: bar.ma60 == null ? undefined : numberFrom(bar.ma60),
    })),
    source: stringFrom(raw.source),
    fallbackReason: stringFrom(raw.fallback_reason),
    support: numberFrom(raw.support),
    resistance: numberFrom(raw.resistance),
    market: stringFrom(raw.market, 'A') as StockAnalysis['market'],
    currency: stringFrom(raw.currency, 'CNY') as StockAnalysis['currency'],
    cnyRate: numberFrom(raw.cny_rate, 1),
    chanPivot: pivot
      ? {
          zg: numberFrom(pivot.zg),
          zd: numberFrom(pivot.zd),
          startDate: stringFrom(pivot.start_date),
          endDate: stringFrom(pivot.end_date),
        }
      : undefined,
    chanThirdBuy: thirdBuy
      ? {
          date: stringFrom(thirdBuy.date),
          price: numberFrom(thirdBuy.price),
          pullbackLow: numberFrom(thirdBuy.pullback_low),
          zg: numberFrom(thirdBuy.zg),
        }
      : undefined,
  }
}

function normalizePreferred(value: unknown): PreferredStocksData {
  const raw = objectFrom(value)
  return {
    items: listFrom<JsonObject>(raw.items, []).map((item) => ({
      code: stringFrom(item.code),
      name: stringFrom(item.name),
      price: numberFrom(item.price),
      change: numberFrom(item.change_pct),
      amount: numberFrom(item.amount),
      score: numberFrom(item.score),
      setup: stringFrom(item.setup, '条件不足'),
      stopLoss: item.stop_loss == null ? undefined : numberFrom(item.stop_loss),
      washoutDays: item.washout_days == null ? undefined : numberFrom(item.washout_days),
      pullbackPct: item.pullback_pct == null ? undefined : numberFrom(item.pullback_pct),
      checks: listFrom<JsonObject>(item.checks, []).map((check) => ({
        key: stringFrom(check.key),
        label: stringFrom(check.label),
        status: stringFrom(check.status, 'failed') as 'passed' | 'failed' | 'manual',
        detail: stringFrom(check.detail),
      })),
    })),
    source: stringFrom(raw.source),
    fallbackReason: stringFrom(raw.fallback_reason),
    analyzedCount: numberFrom(raw.analyzed_count),
    updatedAt: stringFrom(raw.updated_at),
  }
}

function normalizePosition(value: unknown): Position {
  const raw = objectFrom(value)
  const tier = numberFrom(raw.tier, 1)
  return {
    id: stringFrom(raw.code, String(raw.id ?? '')),
    code: stringFrom(raw.code),
    name: stringFrom(raw.name),
    quantity: numberFrom(raw.quantity),
    costPrice: numberFrom(raw.avg_price ?? raw.costPrice),
    currentPrice: numberFrom(raw.live_price ?? raw.currentPrice ?? raw.avg_price),
    stopPrice: numberFrom(raw.stop_loss ?? raw.stopPrice),
    tier: (tier >= 1 && tier <= 3 ? tier : 1) as 1 | 2 | 3,
    note: stringFrom(raw.thesis ?? raw.note),
    createdAt: stringFrom(raw.created_at ?? raw.createdAt),
    stopTriggered: Boolean(raw.stop_triggered),
    change: numberFrom(raw.change_pct),
    market: stringFrom(raw.market, 'A') as Position['market'],
    currency: stringFrom(raw.currency, 'CNY') as Position['currency'],
    fxRate: numberFrom(raw.fx_rate, 1),
    marketValue: raw.market_value == null ? undefined : numberFrom(raw.market_value),
    costValue: numberFrom(raw.avg_price ?? raw.costPrice) * numberFrom(raw.quantity) * numberFrom(raw.fx_rate, 1),
    unrealizedPnl: raw.unrealized_pnl == null ? undefined : numberFrom(raw.unrealized_pnl),
  }
}

function normalizeTrade(value: unknown): Trade {
  const raw = objectFrom(value)
  const logic = stringFrom(raw.logic)
  const note = stringFrom(raw.note)
  return {
    id: numberFrom(raw.id),
    code: stringFrom(raw.code),
    name: stringFrom(raw.name),
    side: stringFrom(raw.side, 'buy') as Trade['side'],
    price: numberFrom(raw.price),
    quantity: numberFrom(raw.quantity),
    tradedAt: stringFrom(raw.traded_at ?? raw.tradedAt),
    reason: note || logic,
    stopPrice: numberFrom(raw.stop_loss ?? raw.stopPrice) || undefined,
    questions: logic ? [logic, note, '已确认资金与上涨空间'] : undefined,
    market: stringFrom(raw.market, 'A') as Trade['market'],
    currency: stringFrom(raw.currency, 'CNY') as Trade['currency'],
    fxRate: numberFrom(raw.fx_rate, 1),
  }
}

function normalizeReview(value: unknown): ReviewData {
  const raw = objectFrom(value)
  const violationCount = numberFrom(raw.violations)
  return {
    winRate: numberFrom(raw.win_rate ?? raw.winRate) * (raw.win_rate != null ? 100 : 1),
    profitLossRatio: numberFrom(raw.profit_loss_ratio ?? raw.profitLossRatio),
    totalProfit: numberFrom(raw.realized_pnl ?? raw.totalProfit),
    tradeCount: numberFrom(raw.total_trades ?? raw.tradeCount),
    monthly: listFrom<JsonObject>(raw.monthly_pnl ?? raw.monthly, []).map((item) => ({
      month: stringFrom(item.month),
      profit: numberFrom(item.pnl ?? item.profit),
    })),
    violations: Array.from({ length: violationCount }, (_, index) => ({
      id: index + 1,
      title: '交易纪律违例',
      detail: '该笔交易存在未按计划执行的记录，请回看交易日志。',
    })),
  }
}

function normalizeAIResult(value: unknown): AIResult {
  const raw = objectFrom(value)
  return {
    text: stringFrom(raw.text),
    model: stringFrom(raw.model),
    generatedAt: stringFrom(raw.generated_at ?? raw.generatedAt),
  }
}

export const api = {
  market: async () => normalizeMarket(await request<unknown>('/market/overview')),
  async aiStatus(): Promise<AIStatus> {
    const raw = objectFrom(await request<unknown>('/ai/status'))
    return { available: Boolean(raw.available), model: stringFrom(raw.model) }
  },
  aiInterpret: async (code: string) =>
    normalizeAIResult(await request<unknown>(`/ai/interpret/${encodeURIComponent(code)}`, { method: 'POST' })),
  aiReviewTrade: async (input: AITradeReviewInput) =>
    normalizeAIResult(await request<unknown>('/ai/review-trade', {
      method: 'POST',
      body: JSON.stringify({
        code: input.code,
        price: input.price || undefined,
        quantity: input.quantity || undefined,
        stop_loss: input.stopLoss || undefined,
        logic: input.logic,
        funds_answer: input.fundsAnswer,
        space_answer: input.spaceAnswer,
      }),
    })),
  aiReviewReport: async () =>
    normalizeAIResult(await request<unknown>('/ai/review-report', { method: 'POST' })),
  preferred: async (limit = 8) =>
    normalizePreferred(await request<unknown>(`/market/preferred?limit=${limit}&candidates=${Math.max(limit, 12)}`)),
  stock: async (code: string) => normalizeStock(await request<unknown>(`/stocks/${encodeURIComponent(code)}`)),
  async settings(): Promise<Settings> {
    const raw = objectFrom(await request<unknown>('/settings'))
    return { totalCapital: numberFrom(raw.total_capital ?? raw.totalCapital) }
  },
  async updateSettings(settings: Settings): Promise<Settings> {
    const raw = objectFrom(await request<unknown>('/settings', {
      method: 'PUT',
      body: JSON.stringify({ total_capital: settings.totalCapital }),
    }))
    return { totalCapital: numberFrom(raw.total_capital ?? raw.totalCapital) }
  },
  async positions() {
    return listFrom<unknown>(await request<unknown>('/positions'), ['items', 'positions', 'results']).map(normalizePosition)
  },
  async createPosition(position: PositionInput) {
    return normalizePosition(await request<unknown>('/positions', {
      method: 'POST',
      body: JSON.stringify({
        code: position.code,
        name: position.name || position.code,
        quantity: position.quantity,
        avg_price: position.costPrice,
        stop_loss: position.stopPrice,
        tier: position.tier,
        thesis: position.note || '',
      }),
    }))
  },
  async updatePosition(id: Position['id'], position: PositionInput) {
    return normalizePosition(await request<unknown>(`/positions/${encodeURIComponent(String(id))}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: position.name || position.code,
        quantity: position.quantity,
        avg_price: position.costPrice,
        stop_loss: position.stopPrice,
        tier: position.tier,
        thesis: position.note || '',
      }),
    }))
  },
  deletePosition: (id: Position['id']) =>
    request<void>(`/positions/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  async trades() {
    return listFrom<unknown>(await request<unknown>('/trades'), ['items', 'trades', 'results']).map(normalizeTrade)
  },
  async createTrade(trade: TradeInput) {
    const questions = trade.questions || ['', '', '']
    const result = objectFrom(await request<unknown>('/trades', {
      method: 'POST',
      body: JSON.stringify({
        code: trade.code,
        name: trade.name || undefined,
        side: trade.side,
        price: trade.price,
        quantity: trade.quantity,
        logic: trade.side === 'buy' ? questions[0] : '',
        funds_confirmed: trade.side === 'buy' ? Boolean(questions[1].trim()) : false,
        space_confirmed: trade.side === 'buy' ? Boolean(questions[2].trim()) : false,
        stop_loss: trade.side === 'buy' ? trade.stopPrice : undefined,
        note: trade.side === 'buy'
          ? `资金验证：${questions[1]}；上涨空间：${questions[2]}`
          : trade.reason,
      }),
    }))
    return normalizeTrade(result.trade ?? result)
  },
  review: async () => normalizeReview(await request<unknown>('/review')),
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '连接交易服务失败，请稍后重试'
}
