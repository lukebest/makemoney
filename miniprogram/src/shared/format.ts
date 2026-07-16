export const money = (value: number): string => {
  const n = Number(value) || 0
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  const fixed = abs.toFixed(2)
  const [intPart, decimals] = fixed.split('.')
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}¥${grouped}.${decimals}`
}

export const percent = (value: number): string => {
  const n = Number(value) || 0
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

export const amount = (value: number): string => {
  const n = Number(value) || 0
  if (n >= 100_000_000) return `${(n / 100_000_000).toFixed(1)} 亿`
  if (n >= 10_000) return `${(n / 10_000).toFixed(0)} 万`
  return n.toFixed(0)
}

export const yuanFromFen = (fen: number): string => money((Number(fen) || 0) / 100)
