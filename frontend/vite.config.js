import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Native Windows uvicorn → localhost:8000. docker-compose backend
// container is reachable as the service name `backend:8000`; the compose
// file injects VITE_BACKEND_URL to override the default.
const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': backend } },
  test: {
    environment: 'jsdom',
    globals: true,
  },
});
