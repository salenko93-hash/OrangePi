# LyceumTV 3.7.1 — Orange Pi PC

[Проєкт](https://github.com/salenko93-hash/OrangePi) · [Інструкція](https://github.com/salenko93-hash/OrangePi/blob/main/docs/INSTALL_ORANGEPI.md) · [Перевірки](https://github.com/salenko93-hash/OrangePi/blob/main/reports/validation.json)

У журналі плати 3.7.0 HDMI й Mali400 працюють, але WebKit перезапускається з `bwrap: Unexpected capabilities but not setuid`. Виправлено запуск kiosk із NoNewPrivileges та порожнім ambient-набором; відновлюються власники всіх батьківських каталогів кешу/профілю. Штатний sandbox WebKit збережено.

## Для вже встановленої 3.7.0

Відкрийте [FIX_KIOSK_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.1/FIX_KIOSK_ORANGEPI.ps1), натисніть **Download raw file** — стрілку вниз. PowerShell у папці цього файла:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\FIX_KIOSK_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Скрипт через SCP передає точний Linux-код із збереженням лапок, застосовує параметри служби/права кешу та перезапускає kiosk/watchdog. Серверні дані, ключі й медіа не замінюються; backend залишається 3.7.0. Після завершення перевірте зображення на TV; фізичне підтвердження ще потрібне.

## Повне встановлення 3.7.1

[Відкрити ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.1/LyceumTV-3.7.1-ORANGEPI-PC.zip) → **Download raw file** → розпакувати весь архів. У PowerShell біля INSTALL_TO_ORANGEPI.ps1:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

92 Python-тести, 8 JavaScript-сценаріїв, 16 JS syntax, 16 браузерних перевірок (9 безпеки, 4 надійності/медіа, 3 профілю), nginx/TLS, 8 unit-файлів, синтаксис embedded repair та ZIP після розпакування. Повний Windows/Armbian/Cage/WebKit/HDMI/звук після виправлення на фізичній Orange Pi не перевірені в хмарі.

SHA256 ZIP: `8ffdc369bafc6a9c4abcbe74d3c1fc9110893c22a639dc79aa0f132084316374`.
