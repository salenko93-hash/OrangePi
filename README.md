# LyceumTV 3.7.2 — Orange Pi PC

[Проєкт](https://github.com/salenko93-hash/OrangePi) · [Інструкція](https://github.com/salenko93-hash/OrangePi/blob/main/docs/INSTALL_ORANGEPI.md) · [Перевірки](https://github.com/salenko93-hash/OrangePi/blob/main/reports/validation.json)

За повідомленням власника попередня 3.7.1 не відновила TV: журнал показував bwrap Unexpected capabilities. Сама властивість служби NoNewPrivileges=yes не є перевіркою фактичного permitted-набору браузера.

У 3.7.2 браузер до GI виконує capset/prctl, скидає effective/permitted/inheritable/ambient capabilities, встановлює no_new_privs і перевіряє стан /proc/self/status. При невідповідності не запускає GTK/WebKit. Sandbox і налаштування захисту ОС збережені.

## Виправлення встановленої 3.7.x

Відкрийте [FIX_KIOSK_ORANGEPI_372.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.2/FIX_KIOSK_ORANGEPI_372.ps1), натисніть **Download raw file** — стрілку вниз. Відкрийте PowerShell у папці цього файла:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\FIX_KIOSK_ORANGEPI_372.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Цей файл має нову назву 372. Він через SCP передає точний Linux-код, ремонтує права профілю, завершує старі сеанси лише окремого kiosk-користувача та атомарно замінює root-owned host зі збереженням попереднього before-3.7.2. Перевіряє privilege API на платі й очікує 20 секунд без зміни PID/NRestarts. При збої показує тільки свіжі service/PAM журнали й повертає помилку.

Backend, ключі, розклад і медіа не оновлюються цим окремим repair. Зображення після застосування ще має підтвердити власник — хмарні тести не замінюють цю перевірку.

## Повний проєкт 3.7.2

[Відкрити ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.2/LyceumTV-3.7.2-ORANGEPI-PC.zip) → **Download raw file** → розпакувати весь архів. У PowerShell біля INSTALL_TO_ORANGEPI.ps1:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Перевірено 99 Python-тестів, 8 JavaScript-сценаріїв, 16 JS-файлів, 16 браузерних перевірок (9 безпеки, 4 надійності/медіа, 3 профілю), nginx/TLS, 8 systemd-unit-ів, shell/три Python payload-и repair і ZIP після розпакування. Реальний Linux-child на x86_64 підтвердив capset/prctl та нульові capability-набори; ARM32/Cage/HDMI/звук після цього виправлення вимагають перевірки на пристрої.

SHA256 ZIP: `46a7a040ec5f5812f61ba9f1f2ca126b5b2697ff24b871f080dae556d69ad60c`.
