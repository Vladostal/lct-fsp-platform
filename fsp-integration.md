---
title: Схема интеграции с ФСП ID и реестром ФСП
subtitle: Привязка профиля кандидата, получение достижений, использование в подборе, отвязка
eyebrow: ФСП.Подбор · специальный трек ФСП
header: ФСП.Подбор · схема интеграции с ФСП
toc_depth: 2
Дата: 11.10.2026
Репозиторий: github.com/Vladostal/lct-fsp-platform
---

## 1. Что интегрируется и в каких границах

API и структура данных ФСП организаторами не предоставлялись, поэтому в репозитории лежат обе стороны интеграции: модуль платформы `fsp` и собственный демо-провайдер `fsp_mock`, который играет роль ФСП ID и реестра. Между ними проходит один шов — интерфейс `FspGateway`.

| Участник | Что это в сборке | Адрес |
|---|---|---|
| Кандидат | браузер с SPA, экран «Настройки → ФСП» | `/candidate/settings/fsp` |
| Платформа | сервисы `web` (nginx + SPA) и `api` (FastAPI), модуль `fsp` | `/api/v1/fsp/*` |
| ФСП ID | демо-провайдер OIDC, смонтирован в процесс `api` | `/api/fsp-mock/oidc` |
| Реестр ФСП | демо-реестр, тот же процесс | `/api/fsp-mock/registry/v1` |
| Работодатель | читает только сохранённый платформой сигнал | реестр не вызывается |

Границы демо-сборки, которые важно знать при чтении схем:

- У демо-провайдера нет HTTP-эндпоинта token, ID-токена и JWT. Обмен кода выполняется вызовом внутри процесса, «токен пользователя» — служебная строка, которая нигде не сохраняется.
- Обращения платформы к реестру в режиме `mock` тоже идут внутри процесса. HTTP-методы реестра существуют и описаны в `docs/fsp-registry-openapi.json`. Выгрузка (R3) и снятие разрешения (R4) по HTTP принимают только служебный заголовок `X-Admin-Token`; доступность, словари и календарь (R1, R2, R5, R6) открыты.
- Демо-ФСП монтируется при `FSP_MOCK_ENABLED=true`; по умолчанию он включён везде, кроме `APP_ENV=production`.
- Режим `FSP_MODE=keycloak` не реализован: шлюз возвращает 503 `fsp_unavailable`.

## 2. Привязка ФСП ID

Привязка — поток OIDC Authorization Code с PKCE (S256). Она отделена от входа в платформу: аккаунт создаётся по e-mail, ФСП ID подключается позже и по отдельному согласию.

### 2.1 Отказы на старте

Запрос `POST /fsp/link/start` отклоняется до обращения к провайдеру в следующих случаях.

| Код | Причина |
|---|---|
| 422 `fsp_consent_required` | согласие не отмечено |
| 409 `fsp_consent_outdated` | версия согласия устарела |
| 409 `fsp_link_exists` | привязка уже есть |
| 429 `fsp_too_many_attempts` | больше 5 попыток за 10 минут |
| 503 `fsp_unavailable` | провайдер недоступен или адаптер не реализован |

### 2.2 Последовательность

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 840" width="700" font-family="Inter, system-ui, sans-serif" role="img" aria-label="Привязка ФСП ID: Authorization Code с PKCE">
<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L9,4 L0,8 z" fill="#402FFF"/></marker></defs>
<rect x="0" y="0" width="700" height="840" fill="#ffffff"/>
<line x1="75" y1="50" x2="75" y2="832" stroke="#c9cbd3" stroke-width="1"/>
<line x1="265" y1="50" x2="265" y2="832" stroke="#c9cbd3" stroke-width="1"/>
<line x1="455" y1="50" x2="455" y2="832" stroke="#c9cbd3" stroke-width="1"/>
<line x1="625" y1="50" x2="625" y2="832" stroke="#c9cbd3" stroke-width="1"/>
<rect x="7" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="75" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Кандидат</text>
<text x="75" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">браузер, SPA</text>
<rect x="197" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="265" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Платформа</text>
<text x="265" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">web + api</text>
<rect x="387" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="455" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">ФСП ID</text>
<text x="455" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">OIDC-провайдер</text>
<rect x="557" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="625" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Реестр ФСП</text>
<text x="625" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">REST, R1–R6</text>
<text x="179.0" y="74" font-size="12" fill="#14151a" text-anchor="middle">POST /fsp/link/start</text>
<circle cx="101.0" cy="70" r="8.5" fill="#402FFF"/><text x="101.0" y="74" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">1</text>
<line x1="75" y1="84" x2="263" y2="84" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<rect x="120.0" y="104" width="290" height="60" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="122" font-size="12" fill="#14151a" text-anchor="middle">согласие fsp-data-1 принято; state, nonce,</text>
<text x="265.0" y="138" font-size="12" fill="#14151a" text-anchor="middle">code_verifier → code_challenge (S256);</text>
<text x="265.0" y="154" font-size="12" fill="#14151a" text-anchor="middle">попытка привязки живёт 10 минут</text>
<text x="179.0" y="188" font-size="12" fill="#14151a" text-anchor="middle">authorize_url</text>
<circle cx="123.75" cy="184" r="8.5" fill="#402FFF"/><text x="123.75" y="188" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">2</text>
<line x1="265" y1="198" x2="77" y2="198" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<text x="111" y="228" font-size="12" fill="#14151a" text-anchor="start">GET /oidc/authorize: state, nonce, code_challenge</text>
<circle cx="97" cy="224" r="8.5" fill="#402FFF"/><text x="97" y="228" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">3</text>
<line x1="75" y1="238" x2="453" y2="238" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<rect x="335.0" y="258" width="240" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="455.0" y="276" font-size="12" fill="#14151a" text-anchor="middle">проверка client_id и redirect_uri;</text>
<text x="455.0" y="292" font-size="12" fill="#14151a" text-anchor="middle">вход и разрешение доступа</text>
<text x="441" y="326" font-size="12" fill="#14151a" text-anchor="end">302 на callback: code, state</text>
<circle cx="246.0" cy="322" r="8.5" fill="#402FFF"/><text x="246.0" y="326" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">4</text>
<line x1="455" y1="336" x2="77" y2="336" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<text x="179.0" y="366" font-size="12" fill="#14151a" text-anchor="middle">GET /fsp/link/callback</text>
<circle cx="94.5" cy="362" r="8.5" fill="#402FFF"/><text x="94.5" y="366" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">5</text>
<line x1="75" y1="376" x2="263" y2="376" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<rect x="120.0" y="396" width="290" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="414" font-size="12" fill="#14151a" text-anchor="middle">state и сессия сверены, попытка погашена,</text>
<text x="265.0" y="430" font-size="12" fill="#14151a" text-anchor="middle">code_verifier затёрт</text>
<text x="369.0" y="464" font-size="12" fill="#14151a" text-anchor="middle">обмен: code, code_verifier</text>
<circle cx="271.5" cy="460" r="8.5" fill="#402FFF"/><text x="271.5" y="464" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">6</text>
<line x1="265" y1="474" x2="453" y2="474" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<rect x="330.0" y="494" width="250" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="455.0" y="512" font-size="12" fill="#14151a" text-anchor="middle">код одноразовый (60 с), сверка PKCE;</text>
<text x="455.0" y="528" font-size="12" fill="#14151a" text-anchor="middle">разрешение access_grant</text>
<text x="369.0" y="562" font-size="12" fill="#14151a" text-anchor="middle">subject, fsp_id, токен</text>
<circle cx="284.5" cy="558" r="8.5" fill="#402FFF"/><text x="284.5" y="562" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">7</text>
<line x1="455" y1="572" x2="267" y2="572" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<rect x="120.0" y="592" width="290" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="610" font-size="12" fill="#14151a" text-anchor="middle">сверка nonce; subject и fsp_id не заняты</text>
<text x="265.0" y="626" font-size="12" fill="#14151a" text-anchor="middle">другим аккаунтом</text>
<text x="301" y="660" font-size="12" fill="#14151a" text-anchor="start">R3: GET /athletes/{fsp_id}/export</text>
<circle cx="287" cy="656" r="8.5" fill="#402FFF"/><text x="287" y="660" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">8</text>
<line x1="265" y1="670" x2="623" y2="670" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="611" y="700" font-size="12" fill="#14151a" text-anchor="end">выгрузка, ETag (ФИО не отдаются)</text>
<circle cx="390.0" cy="696" r="8.5" fill="#402FFF"/><text x="390.0" y="700" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">9</text>
<line x1="625" y1="710" x2="267" y2="710" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<rect x="110.0" y="730" width="310" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="748" font-size="12" fill="#14151a" text-anchor="middle">сохранены: external_identity, согласие fsp_data,</text>
<text x="265.0" y="764" font-size="12" fill="#14151a" text-anchor="middle">снимок и факты; токены не хранятся</text>
<text x="179.0" y="798" font-size="12" fill="#14151a" text-anchor="middle">302 …?result=linked</text>
<circle cx="104.25" cy="794" r="8.5" fill="#402FFF"/><text x="104.25" y="798" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">10</text>
<line x1="265" y1="808" x2="77" y2="808" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
</svg>
<figcaption>Рис. 1. Привязка ФСП ID. Сплошная стрелка — запрос, пунктирная — ответ или перенаправление.</figcaption>
</figure>

| Шаг | Что происходит |
|---|---|
| 1 | SPA заранее получает текст и версию согласия (`GET /fsp/consent`, версия `fsp-data-1`) и отправляет `POST /fsp/link/start` с отметкой о согласии. Платформа создаёт `state` (32 байта), `nonce` (16), `code_verifier` (64) и `code_challenge = base64url(sha256(code_verifier))`. В таблицу `fsp_link_attempt` пишутся хэш `state`, `nonce`, `code_verifier`, `redirect_uri`, версия и SHA-256 текста согласия; попытка живёт 10 минут |
| 2 | Ответ: `authorize_url` и срок действия попытки |
| 3 | Браузер открывает `/oidc/authorize` с параметрами `response_type=code`, `client_id=talent-platform`, `scope=openid fsp.achievements.read`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`. Провайдер принимает только `redirect_uri`, собранный из настройки `PUBLIC_BASE_URL`. В демо пароля нет: страница входа — выбор персонажа |
| 4 | После решения пользователя провайдер выдаёт одноразовый код (в базе только SHA-256, срок 60 секунд) и перенаправляет на callback с `code` и `state`. При отказе — с `error=access_denied` |
| 5 | Браузер приходит на `GET /fsp/link/callback`. Платформа ищет попытку по хэшу `state`, проверяет, что сессия принадлежит тому же кандидату, атомарно гасит попытку и затирает `code_verifier` |
| 6 | Шлюз обменивает код: провайдер гасит код, сверяет клиента, `redirect_uri` и PKCE, регистрирует разрешение `access_grant` |
| 7 | Возвращается идентичность: `issuer`, `subject`, `fsp_id`, токен пользователя. Шлюз сверяет `nonce`; платформа проверяет, что `subject` и `fsp_id` не привязаны к другому аккаунту |
| 8–9 | Первая выгрузка из реестра (метод R3). Если реестр недоступен, привязка всё равно создаётся — без снимка, со статусом `sync_failed` |
| 10 | Ответ callback — всегда 302: на `/candidate/settings/fsp?result=…`, а если сессии платформы нет — на `/login?next=/candidate/settings/fsp` (попытка при этом не гасится, привязку нужно начать заново после входа). Затем SPA читает `GET /fsp/link`; пока идёт синхронизация, опрашивает раз в 2 секунды, не дольше 30 секунд |

**Что сохраняется:** запись `external_identity` (`issuer`, `subject`, `fsp_id`, режим провайдера, утверждения по белому списку `iss`, `sub`, `fsp_id`, версия согласия), согласие `fsp_data`, запись о синхронизации и запись аудита `fsp.linked` с маской `fsp_id` (последние 4 символа). Токены не сохраняются.

### 2.3 Исходы привязки

| Исход привязки | Когда |
|---|---|
| `linked` | привязка создана |
| `cancelled` | кандидат отказал на странице ФСП ID |
| `already_linked` | тот же `subject` или `fsp_id` уже у другого аккаунта |
| `minor` | реестр вернул `is_adult=false`: разрешение снимается, данные не сохраняются, согласие на публикацию отзывается |
| `error` | причина в параметре `reason`: `state`, `expired`, `auth`, `unavailable` |

## 3. Данные реестра, обновление, отвязка

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 916" width="700" font-family="Inter, system-ui, sans-serif" role="img" aria-label="Обновление данных, подбор, отвязка и отзыв">
<defs><marker id="ah" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L9,4 L0,8 z" fill="#402FFF"/></marker></defs>
<rect x="0" y="0" width="700" height="916" fill="#ffffff"/>
<rect x="4" y="62" width="692" height="204" rx="6" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<rect x="4" y="280" width="692" height="164" rx="6" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<rect x="4" y="458" width="692" height="84" rx="6" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<rect x="4" y="556" width="692" height="164" rx="6" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<rect x="4" y="734" width="692" height="164" rx="6" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<line x1="75" y1="50" x2="75" y2="908" stroke="#c9cbd3" stroke-width="1"/>
<line x1="265" y1="50" x2="265" y2="908" stroke="#c9cbd3" stroke-width="1"/>
<line x1="455" y1="50" x2="455" y2="908" stroke="#c9cbd3" stroke-width="1"/>
<line x1="625" y1="50" x2="625" y2="908" stroke="#c9cbd3" stroke-width="1"/>
<rect x="4" y="62" width="164.0" height="22" rx="6" fill="#ebecf0"/>
<text x="14" y="77" font-size="12" font-weight="700" fill="#14151a">А. Обновление данных</text>
<rect x="4" y="280" width="120.8" height="22" rx="6" fill="#ebecf0"/>
<text x="14" y="295" font-size="12" font-weight="700" fill="#14151a">Б. Истории нет</text>
<rect x="4" y="458" width="84.8" height="22" rx="6" fill="#ebecf0"/>
<text x="14" y="473" font-size="12" font-weight="700" fill="#14151a">В. Подбор</text>
<rect x="4" y="556" width="171.20000000000002" height="22" rx="6" fill="#ebecf0"/>
<text x="14" y="571" font-size="12" font-weight="700" fill="#14151a">Г. Отвязка кандидатом</text>
<rect x="4" y="734" width="185.6" height="22" rx="6" fill="#ebecf0"/>
<text x="14" y="749" font-size="12" font-weight="700" fill="#14151a">Д. Отзыв на стороне ФСП</text>
<rect x="7" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="75" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Кандидат</text>
<text x="75" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">браузер, SPA</text>
<rect x="197" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="265" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Платформа</text>
<text x="265" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">web + api</text>
<rect x="387" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="455" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">ФСП ID</text>
<text x="455" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">OIDC-провайдер</text>
<rect x="557" y="6" width="136" height="44" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.4"/>
<text x="625" y="25" font-size="13" font-weight="700" fill="#14151a" text-anchor="middle">Реестр ФСП</text>
<text x="625" y="41" font-size="11" fill="#5b5e6b" text-anchor="middle">REST, R1–R6</text>
<text x="101" y="104" font-size="11" fill="#14151a" text-anchor="start">GET /fsp/link, POST /fsp/sync</text>
<circle cx="88" cy="100" r="8.5" fill="#402FFF"/><text x="88" y="104" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">1</text>
<line x1="75" y1="114" x2="263" y2="114" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="301" y="144" font-size="12" fill="#14151a" text-anchor="start">R3: export, If-None-Match: ETag</text>
<circle cx="287" cy="140" r="8.5" fill="#402FFF"/><text x="287" y="144" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">2</text>
<line x1="265" y1="154" x2="623" y2="154" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="611" y="184" font-size="12" fill="#14151a" text-anchor="end">200 выгрузка или 304 без изменений</text>
<circle cx="377.0" cy="180" r="8.5" fill="#402FFF"/><text x="377.0" y="184" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">3</text>
<line x1="625" y1="194" x2="267" y2="194" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<rect x="115.0" y="214" width="300" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="232" font-size="12" fill="#14151a" text-anchor="middle">нормализация → факты → fsp_signal от 0 до 1;</text>
<text x="265.0" y="248" font-size="12" fill="#14151a" text-anchor="middle">хранятся два последних снимка</text>
<text x="301" y="322" font-size="12" fill="#14151a" text-anchor="start">R3: export</text>
<circle cx="287" cy="318" r="8.5" fill="#402FFF"/><text x="287" y="322" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">4</text>
<line x1="265" y1="332" x2="623" y2="332" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="611" y="362" font-size="12" fill="#14151a" text-anchor="end">404 athlete_not_found или пустой список</text>
<circle cx="344.5" cy="358" r="8.5" fill="#402FFF"/><text x="344.5" y="362" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">5</text>
<line x1="625" y1="372" x2="267" y2="372" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<rect x="110.0" y="392" width="310" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="410" font-size="12" fill="#14151a" text-anchor="middle">снимок без фактов, fsp_signal = 0, штрафа нет;</text>
<text x="265.0" y="426" font-size="12" fill="#14151a" text-anchor="middle">работодателю — нейтральный текст</text>
<rect x="75.0" y="490" width="380" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="508" font-size="12" fill="#14151a" text-anchor="middle">работодатель запрашивает подборку: читается сохранённый</text>
<text x="265.0" y="524" font-size="12" fill="#14151a" text-anchor="middle">сигнал (до 30 из 100 баллов силы), реестр не вызывается</text>
<text x="179.0" y="598" font-size="12" fill="#14151a" text-anchor="middle">DELETE /fsp/link</text>
<circle cx="114.0" cy="594" r="8.5" fill="#402FFF"/><text x="114.0" y="598" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">6</text>
<line x1="75" y1="608" x2="263" y2="608" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<rect x="120.0" y="628" width="290" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="646" font-size="12" fill="#14151a" text-anchor="middle">данные ФСП удалены в одной транзакции,</text>
<text x="265.0" y="662" font-size="12" fill="#14151a" text-anchor="middle">согласие получает revoked_at</text>
<text x="301" y="696" font-size="12" fill="#14151a" text-anchor="start">R4: DELETE /athletes/{fsp_id}/grant</text>
<circle cx="287" cy="692" r="8.5" fill="#402FFF"/><text x="287" y="696" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">7</text>
<line x1="265" y1="706" x2="623" y2="706" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="301" y="776" font-size="12" fill="#14151a" text-anchor="start">R3: export (очередная синхронизация)</text>
<circle cx="287" cy="772" r="8.5" fill="#402FFF"/><text x="287" y="776" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">8</text>
<line x1="265" y1="786" x2="623" y2="786" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah)"/>
<text x="611" y="816" font-size="12" fill="#14151a" text-anchor="end">403 grant_revoked или grant_required</text>
<circle cx="364.0" cy="812" r="8.5" fill="#402FFF"/><text x="364.0" y="816" font-size="10.5" font-weight="700" fill="#ffffff" text-anchor="middle">9</text>
<line x1="625" y1="826" x2="267" y2="826" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah)"/>
<rect x="155.0" y="846" width="220" height="44" rx="5" fill="#f5f4ff" stroke="#402FFF" stroke-width="0.8"/>
<text x="265.0" y="864" font-size="12" fill="#14151a" text-anchor="middle">автоматическая отвязка,</text>
<text x="265.0" y="880" font-size="12" fill="#14151a" text-anchor="middle">уведомление кандидату</text>
</svg>
<figcaption>Рис. 2. Жизненный цикл данных ФСП после привязки: обновление, отсутствие истории, подбор, отвязка и отзыв.</figcaption>
</figure>

### 3.1 Контракт реестра

Контракт придуман командой и зафиксирован в `docs/fsp-registry-openapi.json`. Ошибки отдаются как `application/problem+json` с полем `code`.

| Метод | Путь (от `/registry/v1`) | Назначение |
|---|---|---|
| R1 | `GET /health` | доступность |
| R2 | `GET /dictionaries` | словари |
| R3 | `GET /athletes/{fsp_id}/export` | выгрузка участника; поддерживает `ETag` и `If-None-Match` (304) |
| R4 | `DELETE /athletes/{fsp_id}/grant` | снятие разрешения |
| R5 | `GET /competitions` | календарь соревнований |
| R6 | `GET /competitions/{competition_id}` | одно соревнование |

Состав выгрузки R3 (поля, которые читает платформа):

| Блок | Поля |
|---|---|
| корень | `schema_version`, `generated_at`, `athlete`, `participations[]`, `ranks[]` |
| `athlete` | `fsp_id`, `is_adult`, `region_code`, `status` |
| `participations[]` | `entry_id`, `member_role`, `is_captain`; заявка (`kind`, `team_name`, `team_size`); соревнование (дисциплина, уровень, вид, этап, серия, статус протокола, даты, число заявок); результат (`status`, `place`, `place_to`, `score`, `solved`); параметры анонимности |
| `ranks[]` | `rank_id`, `rank_code`, `discipline_code`, `assigned_on`, `valid_until`, `revoked_on`, `order_number`, `assigned_by` |

В контракте есть также блоки `source`, `norm`, `judge`, `national_team`, `rating` — платформа их не читает.

ФИО, дата рождения и пол реестром не отдаются. `region_code` в снимок платформы не попадает.

### 3.2 Синхронизация

- Попытка записывается до запроса; сам запрос идёт вне транзакции и несёт `ETag` текущего снимка.
- Ответ 304 или тот же хэш содержимого — данные не меняются, обновляется только время проверки.
- Иначе создаётся новый снимок, факты пересоздаются с детерминированными идентификаторами (`uuid5`). Хранятся два последних снимка.
- При сбое сохранённые данные не меняются.

| Когда обновляется | Условие |
|---|---|
| при привязке | первая выгрузка в callback |
| лениво | при `GET /fsp/link`, если снимка нет или последняя проверка была больше 24 часов назад, а прошлая попытка завершилась больше 10 минут назад; обновление идёт фоном, ответ отдаёт уже сохранённые данные |
| вручную | `POST /fsp/sync`, не чаще раза в 60 секунд (429 `fsp_sync_too_frequent`) |
| пакетно | `python -m app.scripts.fsp_resync` |

Запросы работодателя реестр не вызывают: подбор читает сохранённые факты. Календарь R5 кэшируется на 6 часов. Признак «данные устарели» на экране кандидата появляется, если последняя проверка была больше 30 дней назад.

### 3.3 Согласие, отвязка, отзыв

Согласие платформы (`fsp_data`) и разрешение реестра (`access_grant`) — две отдельные записи.

- **Отвязка кандидатом:** `DELETE /fsp/link` → 204, операция идемпотентна. В одной транзакции удаляются достижения, подтверждения, снимки, записи синхронизации и попыток, `external_identity`. Запись согласия остаётся с отметкой `revoked_at`. После фиксации платформа вызывает R4 (две попытки); сбой реестра отвязку не блокирует.
- **Отзыв на стороне ФСП:** очередная синхронизация получает 403 `grant_required` или `grant_revoked`, платформа выполняет ту же отвязку и показывает кандидату уведомление.
- **Удаление аккаунта** вызывает ту же отвязку.

## 4. От выгрузки к подбору

### 4.1 Нормализация

- Дубли по паре (`entry_id`, `member_role`) — берётся последняя запись.
- Факт не зачитывается, если роль не `athlete`, результат аннулирован, соревнование не завершено или протокол не официальный, статус `dsq` или `dns`, уровень неизвестен, даты нет или она в будущем.
- В одной серии соревнований зачитывается один лучший факт.

### 4.2 Сигнал `fsp_signal`

| Величина | Как считается |
|---|---|
| вес результата | произведение шести коэффициентов: уровень, вид, этап, место, размер поля и размер команды |
| уровень | международный 1.0, всероссийский 0.8, окружной 0.45, региональный 0.25, муниципальный 0.1 |
| место | призёры (место 1–3 в верхней половине поля либо при неизвестном размере поля): 1-е — 1.0, 2-е — 0.85, 3-е — 0.75; остальные места — от 0.25 до 0.6 линейно по положению в поле (0.25, если размер поля неизвестен); без места — 0.25 |
| размер поля | `clip(число заявок / 8, 0.5, 1.0)`; 0.5, если число заявок неизвестно |
| команда | `1 / (1 + 0.1 · (размер − 1))` |
| вклад факта `p` | вес результата · близость дисциплины к специализации (по умолчанию 0.5) · `0.5^(лет / 2)` |
| сумма `S` | факты по убыванию `p`, каждый следующий с множителем 0.6 |
| насыщение | `F = 1 − exp(−S / 0.4)` |
| итог | `fsp_signal = max(F, нижняя граница по действующему разряду)`, значение от 0 до 1 (не включая 1) |
| полосы | `none`, `low` (меньше 0.3), `medium` (меньше 0.6), `high` |

Роли капитана и тренера в сигнал не входят: они дают отдельный признак лидерства и подтверждения навыков.

**Вклад в подбор.** В силе профиля слагаемое ФСП равно `0.30 · fsp_signal`, то есть до 30 баллов из 100. Сила — третий ключ порядка внутри раздела подборки, после закрытых обязательных навыков и подтверждённого покрытия. Категорию ФСП не присваивает и не меняет.

### 4.3 Что видит работодатель

| Режим | Когда | Содержание |
|---|---|---|
| нейтральный | достижений нет, либо кандидат их скрыл | «Подтверждённых достижений ФСП в профиле нет. На оценку по тесту это не влияет» |
| обобщённый | до принятия приглашения, а также после него, если кандидат не разрешил раскрывать детали | дисциплина, огрублённый уровень, период и корзина результата; без названия, года, точного места, команды, роли и разряда. Степень обобщения задаёт порог анонимности 20 |
| подробный | приглашение принято и кандидат разрешил раскрывать детали | список достижений, разряды, лидерство, источник |

Настройка кандидата «не показывать сводку ФСП» обнуляет сигнал и убирает кандидата из фильтра «есть достижения ФСП».

## 5. Кандидат без привязки и без истории

| Ситуация | Что хранит платформа | Сигнал |
|---|---|---|
| ФСП ID не привязан | ничего, статус `not_linked` | 0 |
| привязан, в реестре участника нет (404 `athlete_not_found`) | снимок с отметкой «не зарегистрирован», фактов нет | 0 |
| привязан, результатов нет или ни один не зачтён | снимок, причина `no_results` или `no_counted_results` | 0 |
| реестр недоступен при первой выгрузке | привязка без снимка, `history_status = sync_failed` | 0 |
| реестр недоступен при обновлении | прежний снимок и прежний статус; в `refresh.last_outcome` — `failed_unavailable` | по прежним данным |

- Штрафа нет: слагаемое ФСП равно нулю, остальные слагаемые силы не меняются. Профиль, тест, категория и приглашения от привязки не зависят.
- Кандидат на своём экране видит точную причину. Работодателю при отсутствии достижений («не привязал», «истории нет», «скрыл») отдаётся один и тот же нейтральный блок, поэтому по карточке нельзя отличить одно от другого.

## 6. Шов адаптера и подключение настоящего ФСП ID

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 300" width="700" font-family="Inter, system-ui, sans-serif" role="img" aria-label="Шов адаптера FspGateway">
<defs><marker id="ah2" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L9,4 L0,8 z" fill="#402FFF"/></marker></defs>
<rect x="0" y="0" width="700" height="300" fill="#ffffff"/>
<rect x="6" y="8" width="236" height="284" rx="8" fill="#fafafc" stroke="#ebecf0" stroke-width="1.2"/>
<text x="124" y="28" font-size="12" font-weight="700" fill="#14151a" text-anchor="middle">Модуль fsp (не меняется)</text>
<rect x="22" y="40" width="204" height="50" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="124.0" y="61.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">linking.py</text>
<text x="124.0" y="77.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">привязка, согласие, отвязка</text>
<rect x="22" y="102" width="204" height="50" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="124.0" y="123.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">sync.py</text>
<text x="124.0" y="139.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">снимки и факты</text>
<rect x="22" y="164" width="204" height="50" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="124.0" y="185.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">signal.py</text>
<text x="124.0" y="201.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">нормализация, fsp_signal</text>
<rect x="22" y="226" width="204" height="50" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="124.0" y="247.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">views.py</text>
<text x="124.0" y="263.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">что видит работодатель</text>
<rect x="290" y="110" width="150" height="80" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="365.0" y="138.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">FspGateway</text>
<text x="365.0" y="154.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">Protocol:</text>
<text x="365.0" y="170.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">6 методов</text>
<line x1="226" y1="65" x2="288" y2="132" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah2)"/>
<line x1="226" y1="127" x2="288" y2="146" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah2)"/>
<rect x="490" y="30" width="200" height="62" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3"/>
<text x="590.0" y="49.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">MockFspGateway</text>
<text x="590.0" y="65.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">FSP_MODE=mock, вызовы</text>
<text x="590.0" y="81.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">в процессе</text>
<rect x="490" y="208" width="200" height="62" rx="6" fill="#ffffff" stroke="#402FFF" stroke-width="1.3" stroke-dasharray="6 4"/>
<text x="590.0" y="227.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">Адаптер Keycloak</text>
<text x="590.0" y="243.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">FSP_MODE=keycloak —</text>
<text x="590.0" y="259.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">не реализован, 503</text>
<line x1="440" y1="135" x2="488" y2="75" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah2)"/>
<line x1="440" y1="165" x2="488" y2="225" stroke="#402FFF" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ah2)"/>
<rect x="490" y="118" width="200" height="62" rx="6" fill="#ffffff" stroke="#9a9dab" stroke-width="1.3"/>
<text x="590.0" y="137.0" font-size="12.5" font-weight="700" fill="#14151a" text-anchor="middle">fsp_mock</text>
<text x="590.0" y="153.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">демо ФСП ID и реестр</text>
<text x="590.0" y="169.0" font-size="11.5" fill="#5b5e6b" text-anchor="middle">/api/fsp-mock</text>
<line x1="590" y1="92" x2="590" y2="116" stroke="#402FFF" stroke-width="1.4" marker-end="url(#ah2)"/>
</svg>
<figcaption>Рис. 3. Единственная точка замены — реализация FspGateway. Пунктиром показано то, чего в сборке нет.</figcaption>
</figure>

`FspGateway` — интерфейс из шести методов: `authorization_url`, `exchange_code`, `fetch_export`, `revoke_grant`, `list_competitions`, `health`, плюс свойства `issuer` и `registry_url`. Файл `gateway/mock.py` — единственное место платформы, которое импортирует демо-провайдер.

### 6.1 Что заменится при подключении ФСП ID на Keycloak

| Часть | Сейчас (демо) | С настоящим ФСП ID |
|---|---|---|
| адреса провайдера | фиксированный путь `/api/fsp-mock/oidc` | discovery-документ, настройка `FSP_OIDC_DISCOVERY_URL` |
| клиент | `client_id=talent-platform`, без секрета | `FSP_OIDC_CLIENT_ID`, `FSP_OIDC_CLIENT_SECRET` |
| обмен кода | вызов внутри процесса | HTTP-запрос к эндпоинту token |
| идентичность | объект из демо-провайдера, издатель `urn:fsp-mock` | ID-токен с проверкой подписи по ключам провайдера, издатель `FSP_OIDC_ISSUER` |
| доступ к реестру | вызов внутри процесса | HTTP-клиент по `FSP_REGISTRY_URL` с токеном доступа |
| формат выгрузки | собственный контракт R1–R6 | отображение фактического формата ФСП в те же структуры шлюза |

Не меняются: поток привязки и его проверки (`state`, `nonce`, PKCE, согласие), синхронизация и снимки, нормализация, расчёт сигнала, представления для кандидата и работодателя, таблицы базы. Перечисленные настройки уже объявлены в конфигурации, но адаптер, который их читает, не написан.

### 6.2 Сопоставление отказов реестра

| Ответ реестра | Исход синхронизации |
|---|---|
| 429, 5xx, таймаут | `failed_unavailable`, данные не меняются |
| 403 `grant_required` или `grant_revoked` | автоматическая отвязка |
| прочие 401 и 403 | `failed_auth` |
| ответ не по схеме или тело больше 2 МБ | `failed_contract` |
| попытка не закрыта за 30 секунд | `failed_timeout` |

Демо-реестр умеет имитировать отказы (`unavailable`, `slow`, `malformed`) через служебный метод `POST /api/fsp-mock/admin/control` (нужны `FSP_MOCK_ADMIN=true` и заголовок `X-Admin-Token`). Режим `slow` задерживает HTTP-ответ на 10 секунд; для вызовов платформы внутри процесса он сразу отвечает 503, как `unavailable`.

## 7. Что не сделано

- Адаптер настоящего ФСП ID (`FSP_MODE=keycloak`): проверка подписи ID-токена, обмен кода по HTTP, клиент реестра.
- Сверка с реальным форматом данных ФСП: контракт реестра и веса сигнала — допущения команды, на реальных данных не проверялись.
- Вход в платформу через ФСП ID: сейчас это только привязка к существующему аккаунту.
