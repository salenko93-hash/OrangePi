# LyceumTV 3.7.4 — Orange Pi PC

[Вихідний код](https://github.com/salenko93-hash/OrangePi/tree/f7e4d2fa94399a0983322fa2ec53c94e6f968472) · [Інструкція](https://github.com/salenko93-hash/OrangePi/blob/f7e4d2fa94399a0983322fa2ec53c94e6f968472/docs/INSTALL_ORANGEPI.md) · [Перевірки](https://github.com/salenko93-hash/OrangePi/blob/f7e4d2fa94399a0983322fa2ec53c94e6f968472/reports/validation.json)

Без зовнішніх джерел синхронізація працює в локальному режимі й не створює помилку Health Alerts. Збережено попередження про справжні помилки налаштованого джерела. Архів включає всі виправлення Cage/WebKit, вибір одного HDMI-виходу та cursor fix v3 для запуску без успадкованих налаштувань і з програмним курсором.

## Завантажити та встановити

[Відкрити ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/LyceumTV-3.7.4-ORANGEPI-PC.zip) → **Download raw file** → розпакуйте весь архів. У PowerShell біля INSTALL_TO_ORANGEPI.ps1:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Оновлення зберігає ключі, локальні розклади/календар, медіа та налаштовані інтеграції. Якщо редагуєте дані лише в адмінпанелі, у «Система» → «Синхронізація та джерела» обидві адреси мають бути порожніми.

## Окремі скрипти екрана

[FIX_KIOSK_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/FIX_KIOSK_ORANGEPI.ps1) і [HIDE_CURSOR_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/HIDE_CURSOR_ORANGEPI.ps1). Назви такі самі, як усередині ZIP. Вони змінюють екран, але не оновлюють сервер. Повне встановлення вже містить обидва виправлення.

Перевірено 109 Python-тестів, 8 JavaScript-сценаріїв, 16 JS-файлів, 17 браузерних перевірок, nginx/TLS, 8 systemd-unit-ів, payload-и repair і ZIP після розпакування. Наявність cursor fix v3 окремо перевірено в архіві. Запуск без курсора після ввімкнення живлення та HDMI/звук ще потребують перевірки на фізичній Orange Pi; показ сторінки «Канікули» раніше підтверджено власником.

SHA256 ZIP: `8c54d3e587f0e3029c13a4aeb6fabb92d3d19302bcd539b10920f97f6b45070b`.
