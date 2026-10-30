# Установлення на Orange Pi PC

Це повний сервер LyceumTV і телевізійний екран на одній платі. Потрібні Orange Pi PC H3 / armhf, Armbian Ubuntu 24.04+ або Debian 13+, справна microSD, живлення, HDMI та мережа. Ціль власника — Armbian Community 26.11 / Ubuntu Resolute. Пакети завантажуються з репозиторіїв установленої ОС, не з випадкових PPA чи іншої дистрибуції.

## Мережа перед встановленням

Orange Pi PC не має вбудованого Wi-Fi. Під’єднайте Ethernet до роутера/комутатора з DHCP. На самій платі виконайте:

```bash
sudo ip link set end0 up
ip -br addr
ip -br link
```

Потрібна IPv4 біля `end0`. `127.0.0.1` — адреса лише всередині плати. `NO-CARRIER` після ввімкнення означає відсутність фізичного з’єднання: перевірте кабель, порт і живлення.

Якщо фізичний зв’язок є, а адреси немає, визначте мережеву службу:

```bash
systemctl is-active NetworkManager systemd-networkd
```

Лише якщо активний NetworkManager:

```bash
sudo nmcli device connect end0
ip -br addr
```

Лише якщо активний systemd-networkd і для `end0` уже є конфігурація DHCP:

```bash
networkctl status end0 --no-pager
sudo networkctl reconfigure end0
sudo networkctl renew end0
ip -br addr
```

Якщо `end0` має `unmanaged`, спочатку потрібно налаштувати мережу Armbian; не створюйте паралельно конфігурації кількох мережевих менеджерів. Налаштування проєкту не замінює налаштування ОС. Після отримання адреси зарезервуйте її в DHCP роутера й перевірте з Windows:

```powershell
$boardIP = Read-Host "Orange Pi IP"
Test-NetConnection $boardIP -Port 22
ssh "admin@$boardIP"
```

Якщо порт 22 закритий, на самій платі перевірте SSH: `sudo systemctl enable --now ssh`. Пароль береться від облікового запису `admin` цієї Orange Pi.

## З Windows

Завантажте ZIP за посиланням у README, натисніть **Download raw file** і розпакуйте весь архів. Відкрийте PowerShell у папці з `INSTALL_TO_ORANGEPI.ps1`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\INSTALL_TO_ORANGEPI.ps1
```

Адреса запитується під час запуску, користувач за замовчуванням — `admin`. Параметри: `-BoardHost`, `-BoardUser`, `-NoReboot`. Установник використовує `ssh -t`, тому sudo може запросити пароль у терміналі. Команди встановлювача вводяться у Windows, команди Linux — лише після входу через SSH або на самій платі.

Після копіювання публічного CA Windows може показати окреме вікно підтвердження довіри до сертифіката вашої плати. Знайдіть його через Alt+Tab. Перевірка HTTPS не вимикається. Успішна перевірка `/api/health` підтверджує сервер; її результат ще не доводить роботу HDMI/звуку.

## Безпосередньо на Orange Pi

З розпакованого проєкту, від звичайного користувача із sudo:

```bash
chmod +x scripts/*.sh
read -r -p "Orange Pi IPv4: " board_ip
./scripts/install.sh "$board_ip"
sudo reboot
```

Не запускайте весь install.sh через sudo: він сам підвищує права лише для потрібних операцій. Без адреси або на неправильній архітектурі встановлення зупиниться до зміни служб. Помилка відсутнього apt-пакета також зупиняє встановлення до заміни застосунку. Для Ubuntu потрібен компонент `universe`; якщо він вимкнений, увімкніть його штатними засобами Ubuntu та повторіть встановлення.

## Що встановлюється

- `/opt/lyceumtv` — сервер і робочі дані, користувач `lyceumtv` без SSH/sudo.
- `/var/lib/lyceumtv-kiosk` — приватний профіль WebKit користувача `lyceumtv-kiosk`.
- `/usr/local/lib/lyceumtv` — root-owned watchdog, launcher, браузерний host і налаштування HDMI; вебсервер не має права їх змінювати.
- `/etc/lyceumtv/tls` — приватні TLS-ключі, доступні root. Клієнтам передається лише `ca.crt`.
- `lyceumtv.service`, `lyceumtv-kiosk.service`, watchdog/backup/mirror timers і nginx.

Головний TV автоматично отримує свій токен через loopback. У браузер не передається ключ адміністратора. Інші TV підключаються через АДМІН → ЕКРАНИ → ПІДКЛЮЧИТИ, після імпорту публічного CA плати.

Armbian boot-файли, zram, IP-адреса, пароль SSH і власні дані не переписуються. Активний робочий стіл вимикається на наступне завантаження, щоб Cage отримав tty1/HDMI. Це призначено для окремого інформаційного телевізора.

## Перевірка після перезавантаження

З Windows:

```powershell
.\CHECK_ORANGEPI.ps1
.\CHECK_SECURITY_ORANGEPI.ps1
```

Або на Orange Pi/через SSH:

```bash
systemctl status lyceumtv lyceumtv-kiosk lyceumtv-watchdog.timer nginx --no-pager
sudo journalctl -u lyceumtv-kiosk -n 40 --no-pager
sudo journalctl -b _COMM=cage -n 40 --no-pager
```

CHECK_ORANGEPI додатково читає журнали UID kiosk: помилки GTK/WebKit можуть потрапляти в PAM-session, а не в журнал самої служби. Перевірте на TV розклад або штатне повідомлення «канікули», потім фото/відео та звук. У вихідний/канікули звичайний післяурочний показ не вмикається; для перевірки відкрийте `/slideshow-preview` на комп’ютері. Це окремий передперегляд, який не перемикає фізичний TV.

## Якщо немає звуку

На Orange Pi спочатку перевірте наявність аудіокарти:

```bash
aplay -l
```

Перелік виходів PulseAudio kiosk:

```bash
kiosk_uid=$(id -u lyceumtv-kiosk)
sudo -u lyceumtv-kiosk env XDG_RUNTIME_DIR="/run/user/$kiosk_uid" pactl list short sinks
```

Якщо є HDMI-вихід, виберіть його за точною назвою з переліку через `pactl set-default-sink НАЗВА`. Якщо HDMI-карти немає в `aplay -l`, потрібне налаштування драйвера/образу Armbian, а не зміна гучності в застосунку. Перевірте також гучність телевізора й панелі LyceumTV. Апаратне декодування відео залежить від ядра/GStreamer; почніть із H.264/AAC 720p.

## Повернення текстової консолі

З SSH:

```bash
sudo /usr/local/sbin/lyceumtv-console
```

Скрипт зупиняє лише kiosk/watchdog і повертає tty1; сервер і дані залишаються. Для повторного ввімкнення TV:

```bash
sudo systemctl disable --now getty@tty1.service
sudo systemctl enable --now lyceumtv-kiosk.service lyceumtv-watchdog.timer
```

## Довіра іншого Windows-комп’ютера

```powershell
$boardIP = Read-Host "Orange Pi IP"
scp "admin@${boardIP}:lyceumtv-ca.crt" .\lyceumtv-ca.crt
Import-Certificate -FilePath .\lyceumtv-ca.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Імпортуйте CA саме своєї плати через перевірений SSH. Приватні `.key` не копіюйте. Для видалення довіри використовуйте `certmgr.msc` і видаліть відповідний `LyceumTV Local CA`. Сертифікат сервера чинний 825 днів; повторний повний установник оновлює його, коли до завершення лишилося менше 30 днів, зберігаючи CA.

## Armbian: bwrap завершується з Unexpected capabilities

Це відмова sandbox helper при отриманні capabilities звичайним користувачем. У 3.7.1 kiosk має NoNewPrivileges=true та AmbientCapabilities=. File capabilities не надають йому додаткових прав. Штатний sandbox WebKit зберігається.

Для вже встановленої 3.7.0 використайте FIX_KIOSK_ORANGEPI.ps1 із README або повний установник 3.7.1. Виправлення також задає власника/0700 усім батьківським каталогам профілю. Наявні файли профілю не видаляються; symlink замість очікуваного каталогу зупиняє операцію.

Якщо зображення все ще немає, запустіть CHECK_ORANGEPI.ps1 із нової версії. Він показує NoNewPrivs/CapEff фактичного процесу та лічильник перезапусків, а також журнал. Результат active під час циклу перезапусків не означає, що WebKit встиг запуститися.

Bounding set залишено типовим: порожній набір може спричинити EPERM при execve capability-marked системного бінарника ще до застосування обмеження no_new_privs. NoNewPrivileges не дозволяє набуття нових прав через file capabilities; ambient-набір порожній. Очікуваний фактичний стан kiosk — NoNewPrivs: 1 і нульові CapEff/CapPrm.
