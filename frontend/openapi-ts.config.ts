import { defineConfig } from '@hey-api/openapi-ts'

/**
 * Генерация клиента API (Арх. 11.5): `make client` → `npm run client`.
 * Вход — docs/api/openapi.json (выгружает сборочный пакет); другой файл задаётся переменной OPENAPI_INPUT.
 * Каталог src/client целиком перезаписывается генератором и руками не правится.
 */
export default defineConfig({
  input: process.env.OPENAPI_INPUT ?? '../docs/api/openapi.json',
  output: {
    path: './src/client',
  },
  plugins: ['@hey-api/client-fetch', '@hey-api/typescript', '@hey-api/sdk', '@tanstack/react-query'],
})
