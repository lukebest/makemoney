import Taro from '@tarojs/taro'

export const TOKEN_KEY = 'auth_token'
export const USER_KEY = 'auth_user'

export function get<T = string>(key: string): T | undefined {
  try {
    const value = Taro.getStorageSync(key)
    return (value === '' || value == null) ? undefined : (value as T)
  } catch {
    return undefined
  }
}

export function set(key: string, value: unknown): void {
  try {
    Taro.setStorageSync(key, value)
  } catch {
    // Ignore storage write failures (quota / private mode).
  }
}

export function remove(key: string): void {
  try {
    Taro.removeStorageSync(key)
  } catch {
    // Ignore.
  }
}

export const getToken = () => get<string>(TOKEN_KEY)
export const setToken = (token: string) => set(TOKEN_KEY, token)
export const clearToken = () => remove(TOKEN_KEY)
