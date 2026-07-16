// API base URL. Injected at build time from the TARO_APP_API_BASE env variable,
// falling back to the local backend default.
export const API_BASE: string =
  process.env.TARO_APP_API_BASE || 'http://127.0.0.1:8000/api'
