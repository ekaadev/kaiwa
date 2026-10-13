# Kaiwa mobile

Aplikasi percakapan suara dengan UI dan orkestrasi panggilan bersama (Compose Multiplatform,
Material 3 Expressive) untuk Android dan iOS. Target utama: ponsel potret 412×892 dp.
Milestone saat ini adalah Android; eksekusi iOS native ditunda.

## Fitur

- **Home / Practice**: panggilan latihan anonim; backend menetapkan metode adaptive dan data
  tidak masuk data penelitian.
- **Testing**: membaca persetujuan, mendaftar sebagai peserta, lalu menjalani Sesi 1 dan 2.
  Token pemulihan disimpan aman di perangkat. Persetujuan saat ini masih **draf pengembangan**.
- **Panggilan**: izin mikrofon diperiksa pada setiap percobaan. Hang Up meminta pengakhiran
  normal ke server; panggilan berhenti jika aplikasi masuk background (dicatat terputus).
- **Session**: riwayat transkrip lokal (cari, baca, unduh ulang, hapus). Menghapus riwayat
  lokal tidak menghapus evidence di server.
- **Settings**: izin mikrofon dan informasi partisipasi; tidak ada input alamat server atau token.

Selesainya sesi studi ditentukan server, bukan timer atau tombol di klien.

## Struktur

| Folder | Isi |
|---|---|
| `shared/src/commonMain` | Tema, layar, state, Ktor API, Room, DataStore, kontrak platform |
| `shared/src/androidMain` | LiveKit Android, izin mikrofon, kredensial Keystore, jalur Room/DataStore |
| `shared/src/iosMain`, `iosApp/` | Persistensi bersama dan jembatan Swift LiveKit/Keychain |
| `shared/src/commonTest`, `androidHostTest` | Tes logika bersama dan tes host Robolectric |
| `androidApp/` | Host aplikasi Android |
| `licenses/` | Lisensi font dan ikon yang dibundel (Roboto, Material Symbols Rounded) |

## Alamat server

Alamat control API ditanam saat build, dengan prioritas:

1. `-PconversationServerUrl=...`
2. variabel lingkungan `CONVERSATION_SERVER_URL`
3. `conversationServerUrl=...` di `mobile/local.properties` (diabaikan Git; dipakai tombol
   **Run** Android Studio)

Build tanpa alamat menampilkan pesan tidak tersedia dan tidak membuat peserta. Build release
hanya menerima HTTPS; build development mengizinkan HTTP.

Ponsel USB dengan backend lokal di port 8000:

```sh
adb reverse tcp:8000 tcp:8000
./gradlew :androidApp:assembleDebug -PconversationServerUrl=http://127.0.0.1:8000
```

Build debug memakai package `com.ai.mobile.debug` sehingga dapat berdampingan dengan rilis.
Backend GPU yang dideploy: lihat [docs/deployment-gpu.md](../docs/deployment-gpu.md); gunakan
base URL HTTPS lengkap, tanpa `/v1`. Jangan memasukkan LiveKit API secret ke mobile.

## Build dan pengecekan

```sh
./gradlew :shared:testAndroidHostTest :androidApp:lintRelease :androidApp:assembleDebug
```

Untuk rilis: `:androidApp:assembleRelease -PconversationServerUrl=https://backend-anda`.
Kompilasi Kotlin iOS dapat dicek di Linux (`:shared:compileKotlinIosArm64`,
`:shared:compileKotlinIosSimulatorArm64`); Swift/Xcode dan tes simulator memerlukan macOS
(`iosApp/iosApp.xcodeproj`).

Jika memori terbatas:

```sh
./gradlew :androidApp:assembleDebug --max-workers=1 --no-daemon \
  '-Dorg.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8' \
  -Pkotlin.compiler.execution.strategy=in-process
```

Tes host dan build tidak membuktikan kualitas inferensi, pengiriman audio jaringan, atau apa
yang benar-benar terdengar di ponsel.

## Penandatanganan rilis

Kunci rilis RSA-3072 PKCS12 berada di `.signing/conversation-release.p12` dengan konfigurasi
privat `.signing/release.properties`. Keduanya diabaikan Git dan harus dicadangkan aman;
pembaruan APK berikutnya wajib memakai kunci yang sama. Pada checkout lain, pulihkan kedua
berkas dan sesuaikan `storeFile`. Rilis diminify dan resource-shrunk.

Arsip hasil build (APK, checksum, laporan validasi) disimpan di `deliverables/`, yang
diabaikan Git; jangan di-commit.
