import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The UI is static JS only; every byte of data comes from the FastAPI backend.
const backend = process.env.VITE_BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend, ws: true }
    }
  },
  test: { environment: 'node' }
})
