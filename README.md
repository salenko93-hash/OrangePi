# LyceumTV 3.7.3 — Orange Pi PC

[Проєкт](https://github.com/salenko93-hash/OrangePi) · [Інструкція](https://github.com/salenko93-hash/OrangePi/blob/main/docs/INSTALL_ORANGEPI.md) · [Перевірки](https://github.com/salenko93-hash/OrangePi/blob/main/reports/validation.json)

Свіжий журнал підтвердив успішне скидання capabilities у 3.7.2 на фізичній ARM32-платі. Наступне падіння — Cage/wlroots: Assertion surface->initialized. У 3.7.3 прибрано ранній Gtk.Window.fullscreen: Cage сам розгортає вікно після initial commit. Capset/prctl і sandbox збережено. GTK_A11Y=none для окремого TV без accessibility bus.

## Виправлення встановленої 3.7.x

Відкрийте [FIX_KIOSK_ORANGEPI_373.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.3/FIX_KIOSK_ORANGEPI_373.ps1), натисніть **Download raw file** — стрілку вниз. PowerShell у папці цього файла:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\FIX_KIOSK_ORANGEPI_373.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Скрипт атомарно замінює root-owned browser host зі збереженням попереднього before-3.7.3, ремонтує права профілю, завершує старі сеанси лише kiosk-користувача й перевіряє 20 секунд стабільного PID/NRestarts. При збої показує тільки свіжі журнали та повертає помилку. Backend, ключі, розклад і медіа цим repair не оновлюються. Фізичне зображення/звук після 3.7.3 ще має підтвердити власник.

## Повний проєкт

[Відкрити ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.3/LyceumTV-3.7.3-ORANGEPI-PC.zip) → **Download raw file** → розпакувати весь архів. PowerShell біля INSTALL_TO_ORANGEPI.ps1:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Перевірено 100 Python-тестів, 8 JavaScript-сценаріїв, 16 JS-файлів, 16 браузерних перевірок, nginx/TLS, 8 systemd-unit-ів, три Python payload-и/синтаксис repair та ZIP після розпакування. Справжній headless Cage 0.2.0/wlroots0.18 і GTK4.18 розгорнув production-вікно 1280x720; Wayland trace нового варіанта не містить раннього fullscreen. Старіша локальна бібліотека не відтворила assertion 0.19; точне фізичне GTK4.22/Cage0.2.1/wlroots0.19 після цього виправлення очікує перевірки.

PowerShell repair має UTF-8 BOM для точного читання embedded коду у Windows PowerShell 5.1.

SHA256 ZIP: `ab2916583c118876db52c075cb553241e7e9bed66b651b374a28807f0b54efa5`.
