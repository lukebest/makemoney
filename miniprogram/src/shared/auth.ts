import Taro from '@tarojs/taro'

import { api } from './api'
import { clearToken, get, getToken, remove, set, setToken, USER_KEY } from './storage'
import type { AuthUser } from './types'

interface EnsureLoginOptions {
  // When true, failures resolve to undefined instead of throwing (used on launch).
  silent?: boolean
  // Force a fresh login even if a token already exists.
  force?: boolean
}

const isDev = process.env.NODE_ENV !== 'production'

async function wechatCode(): Promise<string | undefined> {
  try {
    const result = await Taro.login()
    return result?.code || undefined
  } catch {
    return undefined
  }
}

export async function ensureLogin(options: EnsureLoginOptions = {}): Promise<AuthUser | undefined> {
  const { silent = false, force = false } = options

  if (!force) {
    const token = getToken()
    if (token) {
      const cached = get<AuthUser>(USER_KEY)
      if (cached) return cached
      try {
        const { user } = await api.me()
        set(USER_KEY, user)
        return user
      } catch {
        // Token likely expired; fall through to a fresh login.
        clearToken()
      }
    }
  }

  try {
    const code = await wechatCode()
    if (code) {
      const result = await api.loginWechat(code)
      setToken(result.token)
      set(USER_KEY, result.user)
      return result.user
    }
  } catch (error) {
    // Real WeChat login failed (e.g. missing credentials in local dev).
    if (!isDev) {
      if (silent) return undefined
      throw error
    }
  }

  // Dev fallback: mock/dev login so authenticated flows are testable locally.
  if (isDev) {
    try {
      const result = await api.loginDev('miniprogram')
      setToken(result.token)
      set(USER_KEY, result.user)
      return result.user
    } catch (error) {
      if (silent) return undefined
      throw error
    }
  }

  if (silent) return undefined
  throw new Error('登录失败，请稍后重试')
}

export async function logout(): Promise<void> {
  try {
    await api.logout()
  } catch {
    // Best effort; clear local state regardless.
  }
  clearToken()
  remove(USER_KEY)
}

export const currentUser = () => get<AuthUser>(USER_KEY)
