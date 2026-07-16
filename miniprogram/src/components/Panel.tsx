import { View, Text } from '@tarojs/components'
import type { ReactNode } from 'react'

interface PanelProps {
  title?: string
  eyebrow?: string
  action?: ReactNode
  className?: string
  children: ReactNode
}

export default function Panel({ title, eyebrow, action, className = '', children }: PanelProps) {
  return (
    <View className={`panel ${className}`}>
      {(title || eyebrow || action) && (
        <View className='panel__head'>
          <View className='panel__head-text'>
            {eyebrow && <Text className='panel__kicker'>{eyebrow}</Text>}
            {title && <Text className='panel__title'>{title}</Text>}
          </View>
          {action && <View className='panel__action'>{action}</View>}
        </View>
      )}
      {children}
    </View>
  )
}
