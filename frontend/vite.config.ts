import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // In development, /api goes to the FastAPI backend, so no CORS setup is needed.
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
