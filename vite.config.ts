import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  server: { host: true, port: 5173 },
  build: { target: 'es2022', outDir: 'dist', assetsDir: 'build', assetsInlineLimit: 0, chunkSizeWarningLimit: 1200 },
});
