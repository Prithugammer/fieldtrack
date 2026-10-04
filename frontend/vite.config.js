import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on :5173 — the origin the Flask API allows via CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
