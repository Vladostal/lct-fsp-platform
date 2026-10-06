import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Один origin с API (Арх. 9.1): в разработке запросы /api и /mail/ уходят на стенд через прокси Vite.
// Адрес стенда задаётся переменной VITE_PROXY_TARGET (по умолчанию — uvicorn на 8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const mailTarget = env.VITE_MAIL_PROXY_TARGET || 'http://127.0.0.1:8025'

  return {
    plugins: [
      // Плагин маршрутов обязан стоять раньше плагина React: он генерирует src/routeTree.gen.ts.
      tanstackRouter({
        target: 'react',
        autoCodeSplitting: true,
        routesDirectory: './src/routes',
        generatedRouteTree: './src/routeTree.gen.ts',
        quoteStyle: 'single',
        semicolons: false,
      }),
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: false },
        '/mail': { target: mailTarget, changeOrigin: false, ws: true },
      },
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
    },
    build: {
      target: 'es2022',
      sourcemap: false,
      // Ничего не встраивается в CSS и JS как data:-адреса: политика CSP стенда (infra/nginx) разрешает шрифты
      // и картинки только со своего origin, а мелкие файлы шрифтов иначе попали бы в стили как data:font/woff2.
      assetsInlineLimit: 0,
    },
  }
})
