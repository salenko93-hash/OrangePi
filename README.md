# LyceumTV 3.7.0 — Orange Pi PC

[Вихідний код](https://github.com/salenko93-hash/OrangePi/tree/main) · [Повна інструкція](https://github.com/salenko93-hash/OrangePi/blob/main/docs/INSTALL_ORANGEPI.md) · [Перевірки](https://github.com/salenko93-hash/OrangePi/blob/main/reports/validation.json)

Готовий ZIP для Orange Pi PC H3, 1 ГБ, armhf, Armbian Ubuntu 24.04+ / Debian 13+. Це застосунок із установником, не образ SD-картки.

[Відкрити ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.0/LyceumTV-3.7.0-ORANGEPI-PC.zip), потім натиснути **Download raw file** — стрілку вниз. Для приватного репозиторію ввійдіть у GitHub. Розпакуйте весь архів і відкрийте PowerShell у папці з INSTALL_TO_ORANGEPI.ps1.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Це поточна адреса плати власника. Якщо DHCP змінить адресу, вкажіть актуальну. Після встановлення: **https://192.168.0.160/admin**. Windows отримує публічний CA через SSH та додає довіру поточному користувачеві. Приватні TLS-ключі залишаються на платі.

Ключі ролей створюються окремо на пристрої:

```powershell
ssh -t admin@192.168.0.160 "sudo /usr/local/sbin/lyceumtv-show-keys"
```

Збережено розклад, оголошення, тривоги, фото по 3 секунди, відео й музику. Новий kiosk: Cage + WebKitGTK 6.0, програмне компонування для Mali-400, легкий профіль, обмеження пам’яті. Починайте з H.264/AAC 720p.

Перевірено: 88 Python-тестів, 8 JavaScript-сценаріїв, 16 JS-файлів, 16 браузерних перевірок застосунку (9 безпеки, 4 медіа/надійності, 3 профілю), справжній nginx/TLS, 8 unit-файлів systemd і ZIP після розпакування. Імпорти та налаштування GI перевірені з реальними GTK4/WebKitGTK бібліотеками на x86_64. Фізичний запуск Orange Pi/Cage/WebKit, HDMI/звук/швидкість відео та Windows-установник ще потребують перевірки на пристрої.

SHA256: `ac2b67297c5e12d4c0ced1997562171505d97eec66db37a08dc05331c2a45581`.
