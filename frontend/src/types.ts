export type MarketPhase = 'spring' | 'summer' | 'autumn' | 'winter'

export interface MarketIndex {
  code: string
  name: string
  value: number
  change: number
  turnover?: number
}

export interface MarketOverview {
  phase: MarketPhase
  phaseLabel?: string
  score: number
  summary: string
  indices: MarketIndex[]
  advance: number
  decline: number
  limitUp: number
  limitDown: number
  updatedAt?: string
  source?: string
  fallbackReason?: string
}

export interface KlineBar {
  date: string
  open: number
  close: number
  low: number
  high: number
  volume: number
  ma5?: number
  ma10?: number
  ma20?: number
  ma60?: number
}

export interface StockAnalysis {
  code: string
  name: string
  price: number
  change: number
  trend: string
  score?: number
  summary?: string
  checks: Array<{ label: string; passed: boolean; detail?: string }>
  klines: KlineBar[]
  source?: string
  fallbackReason?: string
  support?: number
  resistance?: number
  market?: 'A' | 'HK'
  currency?: 'CNY' | 'HKD'
  cnyRate?: number
}

export interface PreferredCheck {
  key: string
  label: string
  status: 'passed' | 'failed' | 'manual'
  detail: string
}

export interface PreferredStock {
  code: string
  name: string
  price: number
  change: number
  amount: number
  score: number
  setup: string
  checks: PreferredCheck[]
  stopLoss?: number
  washoutDays?: number
  pullbackPct?: number
}

export interface PreferredStocksData {
  items: PreferredStock[]
  source?: string
  fallbackReason?: string
  analyzedCount: number
  updatedAt?: string
}

export interface Settings {
  totalCapital: number
  updatedAt?: string
}

export interface Position {
  id: string | number
  code: string
  name: string
  quantity: number
  costPrice: number
  currentPrice: number
  stopPrice: number
  tier: 1 | 2 | 3
  note?: string
  createdAt?: string
  stopTriggered?: boolean
  change?: number
  market?: 'A' | 'HK'
  currency?: 'CNY' | 'HKD'
  fxRate?: number
  marketValue?: number
  costValue?: number
  unrealizedPnl?: number
}

export interface PositionInput {
  code: string
  name?: string
  quantity: number
  costPrice: number
  currentPrice?: number
  stopPrice: number
  tier: 1 | 2 | 3
  note?: string
}

export type TradeSide = 'buy' | 'sell'

export interface Trade {
  id: string | number
  code: string
  name?: string
  side: TradeSide
  price: number
  quantity: number
  tradedAt: string
  reason?: string
  stopPrice?: number
  questions?: [string, string, string]
  market?: 'A' | 'HK'
  currency?: 'CNY' | 'HKD'
  fxRate?: number
}

export interface TradeInput {
  code: string
  name?: string
  side: TradeSide
  price: number
  quantity: number
  tradedAt: string
  reason?: string
  stopPrice?: number
  questions?: [string, string, string]
}

export interface ReviewData {
  winRate: number
  profitLossRatio: number
  totalProfit: number
  tradeCount: number
  monthly: Array<{ month: string; profit: number; trades?: number }>
  violations: Array<{ id?: string | number; date?: string; title: string; detail?: string }>
  fatalMistakes?: string[]
}
