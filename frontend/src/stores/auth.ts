/**
 * 登录态管理（tasks.md 1.2/10.1）。
 * token 同时落 localStorage 便于刷新保持；请求本身依赖 httpOnly Cookie（决策记录3）。
 */
import { defineStore } from 'pinia'

const TOKEN_KEY = 'mw_token'
const USER_KEY = 'mw_user'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    userInfo: JSON.parse(localStorage.getItem(USER_KEY) || 'null') as
      | { id: string; email: string }
      | null,
  }),
  getters: {
    isLogged: (state) => Boolean(state.token),
  },
  actions: {
    setSession(token: string, userInfo: { id: string; email: string }) {
      this.token = token
      this.userInfo = userInfo
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
    },
    clearSession() {
      this.token = ''
      this.userInfo = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})