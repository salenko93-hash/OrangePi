# LyceumTV 3.7.4 — Orange Pi PC

Чистий проєкт для **Orange Pi PC / Allwinner H3 / 1 ГБ RAM / armhf**. Сервер, розклад, оголошення, тривоги, фото по 3 секунди, відео та музика працюють на самій платі. Екран: Cage + WebKitGTK 6.0 / GTK4, медіа через GStreamer і окремий PulseAudio.

**[Завантажити готовий ZIP](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/LyceumTV-3.7.4-ORANGEPI-PC.zip)** → **Download raw file** → розпакуйте весь архів. Для приватного репозиторію потрібен вхід у GitHub.

## Доповнення для Sharp HDMI після випуску ZIP

Журнал плати підтвердив 3.7.4, відсутність перезапусків та фактичні налаштування cursor fix v3. Після стартового перемикання на 720p HDMI двічі від'єднався/під'єднався сам; власник підтвердив, що телевізор не перемикав. Поточний режим після цих подій — EDID-preferred 1920×1080/50 Гц. Це обґрунтовує відмову від автоматичного 720p; остаточний фізичний результат ще перевіряється.

Завантажте поточний [FIX_KIOSK_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/main/FIX_KIOSK_ORANGEPI.ps1) через **Download raw file** та замініть попередній файл. У PowerShell біля нього:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\FIX_KIOSK_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

На початку має бути **Native HDMI + GTK cursor**. Скрипт установлює нативний режим без стартового перемикання на 720p, ховає курсор також на рівні GTK-вікна/GTK-теми, зберігає попередні службові файли й перевіряє стабільність 20 секунд. У журналі очікуються `no startup resolution change` і `GTK cursor: window=none theme=lyceumtv-invisible`. Backend/дані залишаються на місці. Цей патч додано після ZIP 3.7.4; попередній архів не змінювався.

## Оновлення встановленої 3.7.x

У PowerShell біля `INSTALL_TO_ORANGEPI.ps1`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1 -BoardHost "192.168.0.160" -BoardUser "admin"
```

Повне встановлення оновлює сервер і службові файли; зберігає ключі, налаштовані інтеграції, локальні розклади, календар та медіа. Скрипти ремонту екрана окремо не оновлюють сервер: саме тому панель могла продовжувати показувати 3.7.0.

## Що виправлено

- Без адрес зовнішніх джерел синхронізація має статус **ЛОКАЛЬНО**, не створює помилку Health Alerts, не звертається до мережі й не переписує локальні дані. Помилки налаштованого джерела залишаються видимими.
- Cage використовує один вихід (`-m last`) замість розтягування вікна на віртуальний firmware-вихід і HDMI; показ сторінки «Канікули» підтверджено фото власника.
- Прозора тема курсора враховує `default` у Cage 0.2.1. Налаштування задаються перед кожним запуском Cage; `WLR_NO_HARDWARE_CURSORS=1` обходить апаратний курсор. Результат після ввімкнення живлення ще перевіряється на платі.
- Збережено виправлення профілю, скидання успадкованих capabilities до GTK і показ вікна без раннього fullscreen; WebKit sandbox залишається ввімкненим.

## Окремі скрипти екрана

Для встановленої системи: [FIX_KIOSK_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/FIX_KIOSK_ORANGEPI.ps1) ремонтує browser host/профіль, [HIDE_CURSOR_ORANGEPI.ps1](https://github.com/salenko93-hash/OrangePi/blob/download-3.7.4/HIDE_CURSOR_ORANGEPI.ps1) застосовує cursor fix v3. В обох місцях — усередині ZIP і як окремі файли — назви однакові. Запускайте у PowerShell у папці файла з `-BoardHost "192.168.0.160" -BoardUser "admin"`.

Cursor fix зберігає змінений launcher як `launch-kiosk.sh.before-cursor-v3`. Для повернення звичайного курсора видаліть із `/usr/local/lib/lyceumtv/launch-kiosk.sh` блок між `BEGIN LyceumTV cursor environment` і `END LyceumTV cursor environment` включно та `/etc/systemd/system/lyceumtv-kiosk.service.d/50-cursor.conf`; виконайте `sudo systemctl daemon-reload` і `sudo systemctl restart lyceumtv-kiosk.service`.

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
- Поточний запуск зберігає основний режим EDID телевізора. Режим 720p у `display_mode.py` доступний лише через явний `--prefer-720p`, а не під час звичайного запуску.
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
