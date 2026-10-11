import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Dev server on :5173 — the origin the Flask API allows via CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    css: false,
    restoreMocks: true,
  },
})
