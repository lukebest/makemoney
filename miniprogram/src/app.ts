import { PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'

import { ensureLogin } from './shared/auth'

import './app.scss'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // Silent best-effort login so authenticated calls (credits/AI) work later.
    // Never block launch or surface errors here.
    void ensureLogin({ silent: true }).catch(() => undefined)
  })

  return children
}

export default App
