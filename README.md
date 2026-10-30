# LyceumTV 3.7.2 — Orange Pi PC

Окрема версія для **Orange Pi PC / Allwinner H3 / 1 ГБ RAM / armhf**. Основа — захищена LyceumTV 3.6.1. Сервер працює на самій Orange Pi; Raspberry Pi для цієї збірки не потрібна.

Розклад, оголошення, тривоги, хвилина мовчання, фото по 3 секунди, відео й музика збережені. Графічний екран: **Cage + WebKitGTK 6.0 / GTK4**, без робочого столу та Snap/Chromium. Медіа відтворюються через GStreamer і окремий PulseAudio користувача kiosk.

**[Завантажити готовий ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.2/LyceumTV-3.7.2-ORANGEPI-PC.zip)** — на сторінці файла натисніть стрілку **Download raw file**. Для приватного репозиторію потрібен вхід у GitHub. Розпакуйте весь архів.

## Виправлення чорного екрана у встановленій 3.7.x

За журналом власника у 3.7.1 WebKit продовжував падати з `bwrap: Unexpected capabilities`, хоча service показував NoNewPrivileges=yes. У 3.7.2 сам процес браузера виконує capset: скидає permitted/effective/inheritable/ambient права, задає no_new_privs і перевіряє фактичний стан до завантаження GTK/WebKit. Sandbox збережено; файл bwrap і налаштування захисту ОС не змінюються.

Завантажте [FIX_KIOSK_ORANGEPI_372.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.2/FIX_KIOSK_ORANGEPI_372.ps1) через **Download raw file**. У PowerShell у папці цього файла:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\FIX_KIOSK_ORANGEPI_372.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Скрипт атомарно оновлює root-owned браузерний host, зберігає попередній файл як kiosk_browser.py.before-3.7.2, ремонтує права профілю, перевіряє privilege API на платі та спостерігає за PID/перезапусками 20 секунд. При збої повертає помилку й показує свіжі журнали. Backend, ключі, розклад і медіа не змінюються. Фізична поява зображення після цього виправлення ще потребує перевірки власником.

## 1. Під’єднайте Orange Pi до мережі

Підтримувана база: Armbian з Ubuntu 24.04+ або Debian 13+, Python 3.10+, systemd. На фото власника: Armbian Community 26.11 rolling, Ubuntu Resolute, armv7; 960 МіБ доступної пам’яті. Фактичні apt-пакети залежать від репозиторіїв цієї ОС. Потрібен доступ до Інтернету для встановлення пакетів.

На самій платі:

```bash
ip -br addr
```

Якщо `end0` має `DOWN`, під’єднайте Ethernet до роутера/комутатора та виконайте:

```bash
sudo ip link set end0 up
ip -br addr
```

Потрібна IPv4-адреса біля `end0`, а не `127.0.0.1`. Якщо адреси немає, дивіться [мережу та встановлення](docs/INSTALL_ORANGEPI.md). Orange Pi PC не має вбудованого Wi-Fi. Проєкт не змінює IP ОС; зарезервуйте видану адресу в DHCP роутера. Не використовуйте адресу іншої працюючої Raspberry Pi.

## 2. Встановіть із Windows

У розпакованій папці відкрийте PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1
```

Поточна адреса плати власника — **192.168.0.160**. Установник запитає IP Orange Pi. SSH-користувач за замовчуванням — `admin`; вводьте його пароль SSH і sudo. Інший користувач: `-BoardUser "ім’я"`. Інший спосіб задати адресу: `-BoardHost "ваша_IP"`. `-NoReboot` пропускає фінальне перезавантаження.

Установник перевіряє модель/ОС, ставить нативні пакети, створює окремих користувачів сервера й екрана, налаштовує HTTPS та автозапуск. Публічний CA-сертифікат передається через SSH і додається до довірених для поточного користувача Windows. Якщо з’явиться вікно Windows про довіру до **LyceumTV Local CA**, воно стосується сертифіката вашої плати; за потреби знайдіть його через Alt+Tab.

Після успішної перевірки серверної частини плата перезавантажиться й запустить TV. Наявні робочі дані/медіа/токени зберігаються. Перш ніж оновлювати діючий пристрій, створіть backup через адмінпанель.

## 3. Відкрийте керування

Установник надрукує повні адреси:

- `https://IP_ПЛАТИ/` — TV;
- `/admin` — адміністрація;
- `/ops` — медіа й оголошення;
- `/teacher` — учитель;
- `/mobile/` — мобільний розклад;
- `/slideshow-preview` — перевірка фото/відео навіть у вихідні та канікули;
- `/api/health` — стан сервера.

Ключі генеруються на платі. Отримайте їх у PowerShell, вказавши фактичну адресу:

```powershell
$boardIP = Read-Host "Orange Pi IP"
ssh -t "admin@$boardIP" "sudo /usr/local/sbin/lyceumtv-show-keys"
```

Використовуйте `admin_key` для `/admin`. Не публікуйте ключі чи API-токени. Власні ключі при оновленні зберігаються, відомі старі типові значення замінюються випадковими.

## Особливості Orange Pi PC

- Легкий профіль `?lite=1` прибирає розмиті фони й постійне масштабування фото, зберігаючи читабельність і тривоги.
- Спроба перейти на HDMI 1280×720 виконується лише для режиму, який повідомляє монітор, і лише коли Cage підтримує керування виходами. Інакше лишається штатна роздільність.
- Сервер: MemoryHigh 128 МіБ / MemoryMax 256 МіБ. Увесь kiosk разом із браузерними процесами та звуком: 384 / 576 МіБ. Це пороги cgroup, а не вимір фактичного споживання.
- Збережено налаштування Armbian boot, zram і мережі. GPU/відеоприскорення не обіцяється без перевірки плати; GTK використовує Cairo, WebKit — програмне компонування та SHM через обмеження Mali-400/GLES2.
- Починайте з JPG до 1920×1080 та MP4 H.264/AAC **720p, 25–30 кадрів/с**. Файли не перекодовуються. Важкі 1080p/4K можуть гальмувати.
- Тривоги потребують власного токена alerts.in.ua в адмінпанелі. У чистій збірці секрети порожні; старі демонстраційні Google Sheets/manifest URL відключені.

## Перевірка й обслуговування

```powershell
.\CHECK_ORANGEPI.ps1
.\CHECK_SECURITY_ORANGEPI.ps1
```

Це перевірки стану без зміни налаштувань. Повні інструкції: [встановлення, мережа, звук](docs/INSTALL_ORANGEPI.md), [адміністрація](docs/ADMIN.md), [слайдшоу](docs/AFTER_SCHOOL_SLIDESHOW.md), [безпека](docs/SECURITY.md), [backup/OTA](docs/RELIABILITY.md).

## Розробка та збирання

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python VERIFY_PROJECT.py
.venv/bin/python tools/build_release.py
```

Після зміни scripts/kiosk_profile.py перегенеруйте окремий repair: `python tools/build_kiosk_repair.py`. Node.js потрібен для JavaScript-перевірок. GUI-пакети ставляться через apt на Orange Pi; локальні Python/HTTP-тести не потребують GTK. Браузерні тести: `tests/browser_safety.py`, `tests/browser_security.py`. Вони використовують тимчасові копії; результати цього релізу — [reports/validation.json](reports/validation.json).

**Фізичний запуск Orange Pi, її HDMI/звук, продуктивність та виконання Windows-інсталятора потребують перевірки на вашому пристрої.** Архів містить вихідний код та установник, це не образ SD-картки й не набір офлайн-пакетів ОС.
