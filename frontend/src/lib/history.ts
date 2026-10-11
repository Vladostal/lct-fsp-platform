/**
 * История браузера без повторов. Обычный переход на адрес, который уже есть позади в истории вкладки,
 * не добавляет запись, а возвращает к существующей: «Войти → Регистрация → Войти → …» оставляет две записи,
 * и «Назад» выводит туда, откуда пришли, а не прокручивает все переключения. То же с пунктами меню,
 * вкладками и фильтрами в адресе.
 *
 * След адресов хранится в памяти: после перезагрузки страницы он пуст, и переходы идут обычным образом.
 */
import { createBrowserHistory, type RouterHistory } from '@tanstack/react-router'

/** Пока браузер не сообщил о возврате, индекс записи прежний: повторные переходы в это окно пропускаем. */
const RETURN_WINDOW_MS = 1000

export function createTrailHistory(): RouterHistory {
  const history = createBrowserHistory()
  // trail[i] — адрес записи с индексом i; записи, открытые до загрузки страницы, неизвестны (пропуски).
  const trail: (string | undefined)[] = []
  const index = () => history.location.state.__TSR_index
  trail[index()] = history.location.href
  let returningSince = 0

  history.subscribe(({ location, action }) => {
    returningSince = 0
    const at = location.state.__TSR_index
    if (action.type === 'PUSH') trail.length = at
    // Запись, созданная в обход роутера (обычная ссылка `#якорь`), приходит без индекса и сбивает нумерацию.
    // След расходится с историей — забываем его: дальше переходы идут обычным образом.
    else if (action.type !== 'REPLACE' && trail[at] !== undefined && trail[at] !== location.href) trail.length = 0
    trail[at] = location.href
  })

  const push = history.push
  history.push = (path, state, opts) => {
    if (Date.now() - returningSince < RETURN_WINDOW_MS) return
    const current = index()
    const at = current > 0 ? trail.lastIndexOf(path, current - 1) : -1
    if (at < 0) {
      push(path, state, opts)
      return
    }
    returningSince = Date.now()
    // Возврат идёт через popstate: блокировки несохранённых форм срабатывают как при кнопке «Назад».
    history.go(at - current, opts)
  }

  return history
}
