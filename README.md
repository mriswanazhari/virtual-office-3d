<!-- README.md - konversi dokumen Word V16 untuk GitHub. -->

# Virtual Office 3D

**DOKUMENTASI TEKNIS & PANDUAN INSTALASI SERVER BARU**

Versi V16 — Grid Editor Denah & Device List Search/Filter

11 Oktober 2026

Dokumentasi mencakup fitur aplikasi, arsitektur, instalasi dari nol pada Armbian/Ubuntu/Debian, login Admin/Viewer, integrasi Kaspersky Security Center dan Home Assistant, migrasi SQLite, pemeliharaan, serta troubleshooting.

> Keterangan: Panduan berdasarkan rekap proyek V16. Beberapa pengaturan seperti lokasi library Kaspersky, akses jaringan, TLS, dan kompatibilitas paket harus disesuaikan dengan server tujuan.

# Daftar Isi

1. Ringkasan Sistem

2. Rekap Fitur Sampai V16

3. Arsitektur dan Struktur Folder

4. Instalasi dari Nol

5. Konfigurasi Kaspersky Security Center

6. Konfigurasi Home Assistant

7. Database SQLite dan Migrasi

8. Backup, Update dan Rollback

9. Troubleshooting

10. Checklist Go-Live

# 1. Ringkasan Sistem

| Komponen | Spesifikasi |
| --- | --- |
| Aplikasi | Virtual Office 3D — V16 |
| Frontend / 3D | HTML5, CSS3, Vanilla JavaScript; Three.js; GLB/glTF |
| Backend / Database | Python; SQLite |
| Integrasi | Kaspersky Security Center Open API; Home Assistant REST API |
| Akun | Admin dan Viewer, keduanya wajib login password |
| Proxy / Service | Nginx port 8088; backend internal port 8080; systemd |
| Platform | Armbian, Ubuntu, Debian Linux |

# 2. Rekap Fitur Sampai V16

## 2.1 Visualisasi 3D dan navigasi

- Dua lantai dengan denah, objek dan konfigurasi tersendiri.
- Kamera isometrik: orbit, zoom dan pan; memilih perangkat melalui klik.
- Lantai parquet kayu pada kedua lantai, tanpa overlay putih dekoratif.
- Partisi putih gading dengan aksen charcoal dan taman luar lengkap dengan pohon low-poly.
- Pilihan tampil/sembunyikan label ruangan, label perangkat dan garis Smart AP Signals.
- Popup detail perangkat yang dapat dibuka dari tampilan 3D dan Device List.
## 2.2 Perangkat dan avatar

| Jenis | Kemampuan |
| --- | --- |
| Workstation/Laptop | Model meja/PC/laptop, posisi, nama, hostname, IP, AnyDesk |
| Avatar | Original/Cartoon; Office Worker 1, 2, 5, 6 (GLB animasi) |
| Skala | Default 60%, dapat diubah pada masing-masing workstation |
| Server | Model server_rack.glb |
| Pohon | Model low-poly bawaan; tree.glb besar tidak dipakai |
| Access Point/Printer | Monitoring dan pemetaan posisi |

## 2.3 Integrasi monitoring

- KSC membaca endpoint, hostname, alamat IP dan kondisi koneksi; query bersifat read-only.
- Pengambilan data KSC berkala; nilai awal backend V16 sekitar 60 detik dan dapat dikonfigurasi 30–900 detik.
- Home Assistant membaca state berdasarkan Entity ID dan cache sekitar 20 detik.
- Status yang digunakan: Online, Offline dan Unknown; jika integrasi tidak tersambung, tampilkan ketidakpastian.
- Smart AP Signals menghubungkan workstation Online dengan AP Online terdekat secara visual, bukan asosiasi Wi-Fi yang terukur.
## 2.4 Device List dan Editor Denah

- Pencarian Device List berdasarkan nama, ID, hostname, IP, AnyDesk dan Home Assistant Entity ID.
- Filter Online/Offline/Unknown, tipe perangkat, urutan hasil, penghitung hasil, tombol Reset.
- Pencarian/filter berlaku pada lantai aktif; klik baris untuk melihat detail.
- Editor Denah 2D untuk menambah, mengedit, menghapus, menggeser objek, rotasi dan penamaan area.
- Grid biru mengikuti bidang lantai, fitur snap ke pusat sel, termasuk bentuk menjorok pada kedua denah.
- V16 menampilkan indikator “V16 · GRID + FILTER” untuk memastikan versi halaman aktif.
## 2.5 Keamanan dan data

| Fitur | Admin | Viewer |
| --- | --- | --- |
| Login password | Ya | Ya |
| Visualisasi & monitoring | Ya | Ya |
| Device List & filter | Ya | Ya |
| Edit perangkat dan denah | Ya | Tidak |
| Ubah avatar / orientasi | Ya | Tidak |
| Ganti password melalui web | Ya | Tidak |
| Logout | Ya | Ya |

Autentikasi memakai password yang disimpan sebagai hash, sesi login berbatas waktu, dan pembatasan percobaan login. Pengaturan perangkat menggunakan SQLite terpusat dan sistem revisi untuk mendeteksi konflik penyimpanan (HTTP 409).

# 3. Arsitektur dan Struktur Folder

```text
Browser Operator (Admin/Viewer; Three.js)
                |
         Nginx :8088
                |
     Python Backend :8080
          /           \
    SQLite / Auth    KSC + Home Assistant
```

| Path | Fungsi |
| --- | --- |
| /opt/virtual-office/current | Symlink ke rilis aplikasi aktif |
| /opt/virtual-office/venv | Python virtual environment |
| /opt/virtual-office-grid-filters-visible-v16 | Source rilis V16 |
| /var/lib/virtual-office/config.db | Konfigurasi denah dan perangkat |
| /var/lib/virtual-office/admin-auth.json | Hash password Admin |
| /var/lib/virtual-office/viewer-auth.json | Hash password Viewer |
| /var/lib/virtual-office/ksc.json | Konfigurasi KSC |
| /var/lib/virtual-office/ha.json | URL dan token Home Assistant |
| /etc/virtual-office/ksc.env | Username dan password KSC |
| /etc/systemd/system/virtual-office.service | Service Python |
| /etc/nginx/sites-available/virtual-office | Reverse proxy |

> Catatan keamanan: direktori /var/lib/virtual-office berisi data operasional dan kredensial; jangan memasukkannya ke ZIP source yang dibagikan publik.

# 4. Instalasi dari Nol pada Server Baru

## 4.1 Persyaratan

- Server Armbian, Ubuntu atau Debian dengan akses root/sudo dan jaringan ke KSC dan Home Assistant.
- CPU awal 2–4 core, RAM disarankan 4 GB, dan setidaknya 10 GB ruang kosong untuk program, aset, log dan backup.
- Browser Chrome/Edge modern dengan WebGL2; browser membutuhkan akses ke CDN Three.js jika dependensi belum di-host secara lokal.
- Port web 8088 sebaiknya dibatasi LAN/Tailscale/VPN; gunakan HTTPS jika aplikasi diakses melalui jaringan tak terpercaya.
## 4.2 Instal paket sistem

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip nginx unzip curl ca-certificates openssl
python3 --version
nginx -v
```

## 4.3 Siapkan akun layanan dan direktori

```bash
useradd --system --home-dir /var/lib/virtual-office --create-home --shell /usr/sbin/nologin vo-monitor
mkdir -p /opt/virtual-office /var/lib/virtual-office /etc/virtual-office
python3 -m venv /opt/virtual-office/venv
chown -R vo-monitor:vo-monitor /var/lib/virtual-office
chmod 750 /var/lib/virtual-office /etc/virtual-office
```

Jika user vo-monitor sudah ada, perintah useradd tidak perlu diulang.

## 4.4 Instal KlAkOAPI

Library KlAkOAPI harus diperoleh dari paket Open API Kaspersky yang kompatibel dengan versi KSC. Cara pemasangannya bergantung pada distribusi pustaka tersebut. Setelah terpasang, verifikasi:

```bash
/opt/virtual-office/venv/bin/python -c "from KlAkOAPI.AdmServer import KlAkAdmServer; print('KSC API OK')"
```

## 4.5 Ekstrak source V16 dan aktifkan symlink

Upload ZIP V16 melalui WinSCP ke /tmp/virtual-office-grid-filters-visible-v16.zip.

```bash
unzip -o /tmp/virtual-office-grid-filters-visible-v16.zip -d /opt/
test -f /opt/virtual-office-grid-filters-visible-v16/backend/server.py && echo "Backend OK"
ln -sfnT /opt/virtual-office-grid-filters-visible-v16 /opt/virtual-office/current
readlink -f /opt/virtual-office/current
```

Pastikan “Backend OK” tampil sebelum symlink diaktifkan. Jika tidak, periksa nama folder hasil ekstraksi.

## 4.6 Buat systemd service

```bash
nano /etc/systemd/system/virtual-office.service
```

```ini
[Unit]
Description=Virtual Office 3D Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vo-monitor
Group=vo-monitor
WorkingDirectory=/opt/virtual-office/current
Environment=PYTHONUNBUFFERED=1
Environment=VO_HOST=127.0.0.1
Environment=VO_PORT=8080
Environment=VO_PRIVATE_DIR=/var/lib/virtual-office
Environment=VO_DB_PATH=/var/lib/virtual-office/config.db
EnvironmentFile=-/etc/virtual-office/ksc.env
ExecStart=/opt/virtual-office/venv/bin/python /opt/virtual-office/current/backend/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now virtual-office
systemctl status virtual-office --no-pager -l
```

## 4.7 Buat password Admin dan Viewer

```bash
runuser -u vo-monitor -- /opt/virtual-office/venv/bin/python \
  /opt/virtual-office/current/backend/server.py --set-admin-password

runuser -u vo-monitor -- /opt/virtual-office/venv/bin/python \
  /opt/virtual-office/current/backend/server.py --set-viewer-password

systemctl restart virtual-office
ls -l /var/lib/virtual-office/*auth.json
```

Username akun adalah admin dan viewer. Buat password berbeda, masing-masing minimal 10 karakter. Jangan menggunakan password contoh statis.

## 4.8 Konfigurasi Nginx

```bash
nano /etc/nginx/sites-available/virtual-office
```

```nginx
server {
    listen 8088;
    server_name _;
    client_max_body_size 10M;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
    }
    location = /index.html {
        proxy_pass http://127.0.0.1:8080;
        add_header Cache-Control "no-store, max-age=0" always;
    }
}
```

```bash
ln -sfn /etc/nginx/sites-available/virtual-office /etc/nginx/sites-enabled/virtual-office
nginx -t
systemctl reload nginx
```

## 4.9 Verifikasi layanan

```bash
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8088/
curl -s http://127.0.0.1:8088/ | grep -o 'V16 · GRID + FILTER'
```

Buka http://IP-SERVER:8088 dari browser operator, login sebagai admin atau viewer, lalu uji tampilan 3D, Device List, dan Editor Denah.

# 5. Konfigurasi Kaspersky Security Center

KSC Open API menggunakan port HTTPS 13299. Contoh host di bawah adalah alamat KSC yang sebelumnya dipakai; ganti jika topologi berubah.

## 5.1 Sertifikat

```bash
# Salin sertifikat Administration Server yang benar ke:
/etc/virtual-office/klserver.cer

chown root:vo-monitor /etc/virtual-office/klserver.cer
chmod 640 /etc/virtual-office/klserver.cer
```

## 5.2 File konfigurasi KSC

```bash
nano /var/lib/virtual-office/ksc.json
```

```json
{
  "server_url": "https://10.126.200.52:13299",
  "cert_file": "/etc/virtual-office/klserver.cer",
  "filter": "",
  "max_hosts": 3000,
  "poll_seconds": 60
}
```

```bash
chown vo-monitor:vo-monitor /var/lib/virtual-office/ksc.json
chmod 600 /var/lib/virtual-office/ksc.json
```

## 5.3 Kredensial KSC

```bash
nano /etc/virtual-office/ksc.env
```

```bash
KSC_USERNAME='DOMAIN\akun-monitoring'
KSC_PASSWORD='GANTI_DENGAN_PASSWORD_ASLI'
```

```bash
chown root:root /etc/virtual-office/ksc.env
chmod 600 /etc/virtual-office/ksc.env
systemctl restart virtual-office
journalctl -u virtual-office -n 80 --no-pager
```

Gunakan akun layanan dengan hak baca inventaris. Periksa koneksi ke port 13299, sertifikat, kredensial, dan kemampuan library KlAkOAPI bila status KSC Disconnected.

# 6. Konfigurasi Home Assistant

1. Buat Long-Lived Access Token di profil akun Home Assistant yang berwenang membaca entity.
1. Buat file ha.json pada server, isi URL HA dan token, lalu amankan permission file.
1. Restart Virtual Office dan isi Home Assistant Entity ID pada tiap AP, printer atau server yang ingin dimonitor.
```bash
nano /var/lib/virtual-office/ha.json
```

```json
{
  "url": "http://192.168.1.50:8123",
  "token": "GANTI_DENGAN_LONG_LIVED_TOKEN"
}
```

```bash
chown vo-monitor:vo-monitor /var/lib/virtual-office/ha.json
chmod 600 /var/lib/virtual-office/ha.json
systemctl restart virtual-office
```

Contoh Entity ID: binary_sensor.access_point_01, binary_sensor.printer_online, sensor.server_status. Gunakan entity yang benar-benar tersedia. Status sensor di luar pola yang dikenali dapat tampil sebagai Unknown.

# 7. Database SQLite dan Migrasi

## 7.1 Instalasi baru

Pada instalasi baru, backend membuat SQLite dan data awal lantai berdasarkan JSON bawaan bila database belum tersedia. Pastikan layanan berjalan dan file dibuat:

```bash
systemctl restart virtual-office
ls -lh /var/lib/virtual-office/config.db
```

## 7.2 Pindah server lama ke server baru

Agar posisi perangkat, avatar, serta konfigurasi tetap sama, pindahkan direktori data persisten. Jalankan backup saat service lama dihentikan demi konsistensi file SQLite dan autentikasi.

```bash
# SERVER LAMA
systemctl stop virtual-office
tar -C /var/lib -czf /root/virtual-office-data-backup.tar.gz virtual-office
```

Salin file backup dengan WinSCP/SCP ke /root/ server baru.

```bash
# SERVER BARU
systemctl stop virtual-office
# Backup dulu isi /var/lib/virtual-office jika ada
tar -C /var/lib -xzf /root/virtual-office-data-backup.tar.gz
chown -R vo-monitor:vo-monitor /var/lib/virtual-office
chmod 750 /var/lib/virtual-office
systemctl start virtual-office
```

Bila server lama masih digunakan, aktifkan kembali secara terencana; hindari pengeditan pada dua database SQLite terpisah tanpa sinkronisasi.

# 8. Backup, Update dan Rollback

## 8.1 Backup SQLite konsisten

```bash
python3 - <<'PY_BACKUP'
import sqlite3
from datetime import datetime
src = '/var/lib/virtual-office/config.db'
dst = '/var/lib/virtual-office/config-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db'
with sqlite3.connect(src) as source:
    with sqlite3.connect(dst) as target:
        source.backup(target)
print('Backup:', dst)
PY_BACKUP
```

Backup pula admin-auth.json, viewer-auth.json, ksc.json, ha.json, ksc.env dan sertifikat bila diperlukan. Simpan kredensial secara terenkripsi dan batasi akses file backup.

## 8.2 Update rilis

```bash
unzip -o /tmp/NAMA-RILIS-BARU.zip -d /opt/
test -f /opt/NAMA-RILIS-BARU/backend/server.py || exit 1
ln -sfnT /opt/NAMA-RILIS-BARU /opt/virtual-office/current
systemctl restart virtual-office
```

## 8.3 Rollback

```bash
# Ganti NAMA-RILIS-SEBELUMNYA dengan direktori yang masih ada
ln -sfnT /opt/NAMA-RILIS-SEBELUMNYA /opt/virtual-office/current
systemctl restart virtual-office
```

Jangan hapus /opt/virtual-office/venv atau /var/lib/virtual-office ketika membersihkan versi rilis lama.

# 9. Troubleshooting

| Masalah | Pemeriksaan |
| --- | --- |
| 502 Bad Gateway | Backend mati, salah symlink, port 8080 atau Nginx |
| Login gagal | Akun belum dibuat, auth JSON tidak terbaca, password salah |
| KSC Disconnected | KlAkOAPI, TLS/sertifikat, port 13299, hak akun |
| Home Assistant Disconnected | URL, token, sertifikat/koneksi, state entity |
| Model 3D tidak muncul | Three.js CDN, WebGL, aset GLB, console JS |
| Grid/filter V16 belum berubah | Cache browser, sumber HTML yang salah, symlink belum aktif |
| Edit tidak tersimpan | Permission SQLite, sesi habis, konflik revisi HTTP 409 |

## 9.1 Perintah diagnosis

```bash
systemctl status virtual-office --no-pager -l
journalctl -u virtual-office -n 100 --no-pager
readlink -f /opt/virtual-office/current
ss -lntp | grep -E ':8080|:8088'
nginx -t
curl -s http://127.0.0.1:8088/ | grep -o 'V16 · GRID + FILTER'
```

Endpoint monitoring V16 mensyaratkan sesi login: respons HTTP 401 tanpa autentikasi tidak otomatis menandakan layanan rusak.

# 10. Checklist Go-Live

☐  Website dapat diakses dari LAN/Tailscale

☐  Admin login dengan password

☐  Viewer login dan tidak dapat mengedit

☐  Lantai 1 dan Lantai 2 tampil

☐  Editor Denah memperlihatkan grid biru kedua lantai

☐  Device List: pencarian, filter, sorting dan Reset

☐  Server rack GLB serta avatar Office Worker dimuat

☐  KSC menampilkan status endpoint

☐  HA menampilkan kondisi entity

☐  Data konfigurasi bertahan sesudah restart

☐  Backup SQLite serta file auth/integrasi tersedia

# Catatan penutup

Paket V16 merupakan hasil pengembangan bertahap Virtual Office 3D. Saat penerapan pada server baru, lakukan verifikasi UI dan koneksi ke sistem asli sebelum dipakai sebagai dashboard operasional. Dokumentasi ini dimaksudkan sebagai panduan instalasi dan inventaris fitur, bukan pengganti pengujian keamanan dan performa produksi.
