/** Server messages are English (stable for logs/tests); users see Ukrainian. Unknown text passes through. */
const UA: Record<string, string> = {
  'Hermes bridge unavailable': 'Агент профілю зараз недоступний (перезапускається або зупинений). Спробуйте за кілька секунд.',
  'Owner bridge unavailable': 'Головний агент перезапускається. Спробуйте за кілька секунд.',
  'Profile has no running bridge': 'Агент цього профілю зупинений. Запустіть його в Профілі → Загальне.',
  'Start the profile bridge to list models': 'Запустіть агента профілю, щоб побачити список моделей.',
  'Invalid credentials': 'Невірний логін або пароль.',
  'Login required': 'Потрібно увійти.',
  'Admin only': 'Лише для адміністратора.',
  'CSRF token missing or invalid': 'Сторінка застаріла. Оновіть її (Ctrl+F5).',
  'Cross-origin request denied': 'Запит відхилено з міркувань безпеки. Відкрийте портал за його основною адресою.',
  'Too many failed attempts; try again later': 'Забагато невдалих спроб. Спробуйте пізніше.',
  'Old password is wrong': 'Старий пароль невірний.',
  'Wrong password': 'Невірний пароль.',
  'Invalid code': 'Невірний код.',
  'Not allowed for you': 'Вам це не дозволено. Зверніться до адміністратора.',
  'Model switching is not allowed for you': 'Зміна моделі вам не дозволена.',
  'Reasoning settings are not allowed for you': 'Налаштування міркувань вам не дозволені.',
  'Provider is not available to you': 'Цей провайдер вам недоступний.',
  'This model of the shared subscription is not allowed for you': 'Цю модель спільної підписки адміністратор вам не дозволив.',
  'Profile is shared; ask the administrator': 'Профіль спільний з іншими користувачами — зверніться до адміністратора.',
  'Own subscriptions are not enabled for you': 'Власні підписки вам не дозволені.',
  'Connect your own key for this provider first': 'Спершу підключіть власний ключ цього провайдера.',
  'Wait until the current response finishes': 'Дочекайтеся, поки агент завершить відповідь.',
  'Profile has an active response; wait or stop it first': 'Агент саме відповідає. Дочекайтеся або зупиніть відповідь.',
  'The agent is still answering in this chat; stop it first': 'Агент ще відповідає в цьому чаті — спершу зупиніть відповідь.',
  'One running turn at a time per profile': 'В одному профілі агент відповідає лише в одному чаті одночасно.',
  'Another turn is active; reconnect or stop it': 'Агент уже відповідає. Дочекайтеся або зупиніть відповідь.',
  'User has an active response; stop it first': 'У користувача триває відповідь агента — спершу зупиніть її.',
  'Username already exists': 'Такий логін уже існує.',
  'You cannot delete yourself': 'Не можна видалити себе.',
  'You cannot block or demote yourself': 'Не можна заблокувати себе чи зняти з себе роль адміністратора.',
  'Profile still has portal users; reassign them first': 'У профілі є користувачі — спершу перепризначте їх.',
  'Storage quota reached': 'Сховище файлів заповнене. Видаліть непотрібне в «Артефактах».',
  'File must be 1 byte–10 MiB': 'Файл має бути до 10 МБ.',
  'Text limit: 2 MiB': 'Текстовий файл — до 2 МБ.',
  'Allowed: UTF-8 text, PNG, JPEG, WebP': 'Підтримуються: текст (UTF-8), PNG, JPEG, WebP.',
  'Text must be UTF-8': 'Текст має бути в кодуванні UTF-8.',
  'Invalid image or >20 megapixels': 'Зображення пошкоджене або більше 20 мегапікселів.',
  'Dialog not found': 'Чат не знайдено (можливо, видалено).',
  'File not found': 'Файл не знайдено.',
  'No such user': 'Користувача не знайдено.',
  'Title is empty': 'Назва не може бути порожньою.',
  'Two-factor authentication is required for administrators': 'Для адміністраторів обовʼязковий двофакторний вхід.',
  'Enable two-factor authentication for your own account first': 'Спершу увімкніть двофакторний вхід для себе.',
};
export function humanize(msg: string): string {
  const m = msg.replace(/^Error: /, '').trim();
  if (UA[m]) return UA[m];
  if (/^Monthly limit|limit reached|ліміт/i.test(m)) return m;
  if (/Failed to fetch|NetworkError|Load failed/i.test(m)) return 'Немає звʼязку з сервером. Перевірте інтернет.';
  if (/^<!DOCTYPE|<html/i.test(m) || /^(502|503|504)\b/.test(m)) return 'Сервер тимчасово недоступний. Спробуйте за хвилину.';
  return m;
}
