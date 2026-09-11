/**
 * Axios 统一封装（tasks.md 1.2）：
 * - baseURL=/api，withCredentials=true（httpOnly Cookie 会话，EventSource 同源自动携带）
 * - 响应拦截器统一处理 code!=0 业务错误与 401 跳转（design.md §2.6.3、§2.2.1）
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true,
})

request.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      if (body.code === 40100) {
        ElMessage.warning('请先登录')
        const target = window.location.pathname + window.location.search
        window.location.href = `/login?redirect=${encodeURIComponent(target)}`
        return Promise.reject(body)
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const body = error.response?.data
    if (status === 401) {
      ElMessage.warning('请先登录')
      const target = window.location.pathname + window.location.search
      window.location.href = `/login?redirect=${encodeURIComponent(target)}`
    } else {
      ElMessage.error(body?.message || error.message || '网络异常')
    }
    return Promise.reject(error)
  },
)

export default request