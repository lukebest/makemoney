import { View, Text } from '@tarojs/components'
import type { ReactNode } from 'react'

interface MetricProps {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: 'gain' | 'loss' | 'neutral'
}

export default function Metric({ label, value, note, tone }: MetricProps) {
  return (
    <View className='metric'>
      <Text className='metric__label'>{label}</Text>
      <Text className={`metric__value ${tone ? `metric__value--${tone}` : ''}`}>{value}</Text>
      {note != null && note !== '' && <Text className='metric__note'>{note}</Text>}
    </View>
  )
}
