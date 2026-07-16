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
  fried: number
  volumeRatio: number
  boardDate?: string
  updatedAt?: string
  source?: string
  fallbackReason?: string
}

export interface MainlineStock {
  code: string
  name: string
  sector: string
  boardCount: number
  amount: number
  sealedAmount: number
  breakCount: number
  firstSealedAt?: string
}

export interface MainlineSector {
  name: string
  limitUpCount: number
  firstBoardCount: number
  secondPlusCount: number
  maxBoard: number
  leader?: MainlineStock
}

export interface MarketMainline {
  source: string
  date?: string
  mainSector?: string
  activeSectors: string[]
  sectors: MainlineSector[]
  ladders: Array<{ boardCount: number; stocks: MainlineStock[] }>
  leaders: MainlineStock[]
  totalCount: number
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
  chanPivot?: { zg: number; zd: number; startDate: string; endDate: string }
  chanThirdBuy?: { date: string; price: number; pullbackLow: number; zg: number }
  structure?: {
    phase: string
    label: string
    summary: string
    evidence: string[]
    acceptance: {
      code: string
      label: string
      summary: string
      change3dPct?: number
      volumeRatio?: number
    }
  }
}

export interface AIResult {
  text: string
  model: string
  generatedAt?: string
  hardWarnings: string[]
  gatePassed?: boolean
}

export interface AIStatus {
  available: boolean
  model: string
}

export interface AITradeReviewInput {
  code: string
  price?: number
  quantity?: number
  stopLoss?: number
  logic: string
  fundsAnswer: string
  spaceAnswer: string
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
  sector?: string
  inMainline?: boolean
}

export interface PreferredStocksData {
  items: PreferredStock[]
  source?: string
  fallbackReason?: string
  analyzedCount: number
  activeSectors: string[]
  updatedAt?: string
}

export interface CloseScreenData extends PreferredStocksData {
  matchCount: number
  asOfDate?: string
  forDate?: string
  afterClose?: boolean
}

export interface Settings {
  totalCapital: number
  maxPositionRatio?: number
  maxInvestedRatio?: number
  updatedAt?: string
}

export interface PortfolioSummary {
  totalCapital: number
  investedCost: number
  realizedPnl: number
  availableFunds: number
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
