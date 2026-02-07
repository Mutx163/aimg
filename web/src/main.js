import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

const rawFetch = window.fetch.bind(window)
window.fetch = async (input, init = {}) => {
  const response = await rawFetch(input, { credentials: 'same-origin', ...init })
  const url = typeof input === 'string' ? input : String(input?.url || '')
  if (response.status === 401 && !url.includes('/api/auth/')) {
    window.dispatchEvent(new CustomEvent('aimg-auth-required'))
  }
  return response
}

createApp(App).mount('#app')
