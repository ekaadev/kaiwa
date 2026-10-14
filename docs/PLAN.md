# Rencana Pengembangan Sistem AI Conversation

Acuan: *System Requirements Document* (FR-01–19). Ini rencana **membangun sistem**, bukan menjalankan atau menganalisis penelitian. **Aplikasi** berarti klien mobile Android/iOS; **backend** berarti server; **sistem** berarti keduanya. `[x]` berarti tepat hal yang tertulis sudah berfungsi; `[ ]` berarti belum.

## Prioritas 1 — Pengguna bisa masuk ke alur yang tepat

### Fitur 1 — Pilih latihan atau pengujian (FR-01/02)

- [x] Aplikasi berbasis **Compose Multiplatform** menyediakan pilihan latihan **AI Conversation** melalui Home / Practice Call dan **Ikut Pengujian** melalui Testing / Testing Call.
- [x] Jalur latihan meminta satu panggilan tanpa mendaftar sebagai peserta; backend menetapkan **adaptive**, dan data latihan tidak masuk data pengujian.
- [x] Panggilan latihan nyata di Android berhasil dengan audio dua arah melalui LiveKit ke backend Runpod; pengguna berbicara dan jawaban tutor terdengar di ponsel pada uji coba 1 Oktober 2026.
- [ ] Verifikasi panggilan latihan di Android berakhir normal dan transkrip final tersimpan di riwayat lokal.

**Status:** alur pemilihan dan pemisahan latihan/pengujian sudah diimplementasikan; audio dua arah pada latihan Android sudah dicoba. Akhir panggilan dan riwayat final di ponsel masih perlu diverifikasi. Menjalankan aplikasi native iOS ditunda dan tidak menjadi syarat penyelesaian Fitur 1 saat ini.

### Fitur 2 — Daftar sebagai peserta pengujian (FR-03/04)

- [x] Backend hanya menerima pendaftaran yang menyatakan setuju, lalu membuat ID tanpa nama serta mencatat versi dan waktu persetujuan.
- [x] Backend membagi urutan fixed/adaptive secara seimbang dan membuat dua sesi awal. Urutan metode tidak dikirim dalam respons peserta.
- [x] Aplikasi menampilkan penjelasan dan teks persetujuan sebelum mengirim pendaftaran. Menolak tidak mendaftar atau memulai rekaman; menyetujui meminta izin mikrofon, lalu mendaftar jika izin diberikan. Pendaftaran tidak otomatis memulai panggilan.
- [ ] Teks dan versi persetujuan disahkan sebelum digunakan peserta nyata; teks di aplikasi saat ini masih draf pengembangan.
- [x] Aplikasi menahan ketukan daftar berulang selama proses berjalan. Jika penyimpanan token gagal setelah respons diterima, percobaan ulang menyimpan peserta yang sama selama state aplikasi masih tersedia.
- [x] Pengiriman ulang permintaan pendaftaran ke backend tidak membuat dua peserta, termasuk saat respons jaringan hilang. Backend mewajibkan `Idempotency-Key` dan mengembalikan peserta/token yang sama untuk kunci yang sama; aplikasi membuat satu kunci per percobaan, menyimpannya di penyimpanan aman, dan memakainya ulang setelah retry atau restart sampai kredensial tersimpan. Diuji dengan SQLite dan tes host; jalur Postgres dan jaringan nyata belum diuji.

**Status:** alur pendaftaran backend dan mobile sudah diimplementasikan, termasuk idempotensi pendaftaran. Fitur 2 belum selesai karena teks dan versi persetujuan belum disahkan.

### Fitur 3 — Kembali tanpa kehilangan peserta (FR-05/06)

- [x] Backend memberikan token sekali saat pendaftaran. Dengan token itu, peserta dapat membaca kembali ID dan status kedua sesinya.
- [x] Aplikasi menyimpan token dengan aman dan membuka progres peserta yang sama saat dijalankan lagi.
- [x] Pergantian peserta pada ponsel bersama dan tes ulang setelah selesai memerlukan tindakan petugas; data peserta sebelumnya tidak tertimpa.

## Prioritas 2 — Panggilan suara bisa digunakan

### Fitur 4 — Mulai panggilan (FR-07–09)

- [ ] Sebelum menelepon, aplikasi memberi petunjuk singkat bahwa pengguna boleh memilih topik sendiri, tanpa skenario tetap. Petunjuk sudah tersedia di Testing, tetapi belum di Home untuk latihan. SRD FR-07 masih meminta skenario tertentu dan perlu diselaraskan dengan keputusan ini.
- [x] Backend dapat memeriksa koneksi database. **Ini belum berarti layanan panggilan siap.**
- [x] Aplikasi memeriksa izin mikrofon sebelum setiap percobaan; backend memeriksa konfigurasi, ketersediaan model/layanan tutor, dan kapasitas panggilan. Jika pemeriksaan atau persiapan gagal, panggilan tidak dimulai dan aplikasi menampilkan pesan masalah.
- [x] Backend menyiapkan ruang LiveKit dan token sementara khusus ruang; pipeline tutor disiapkan dan Pipecat bergabung sebelum akses diberikan ke aplikasi. Rahasia layanan tetap di backend.
- [x] Adapter LiveKit mobile menggunakan URL dan token dari backend untuk bergabung ke ruang panggilan dan mengaktifkan mikrofon.
- [x] Koneksi latihan nyata di Android berhasil: aplikasi dan tutor terhubung melalui ruang LiveKit yang sama, mikrofon mengirim suara, dan audio jawaban tutor diterima di ponsel.
- [ ] Verifikasi penanganan kegagalan layanan/koneksi pada panggilan nyata di Android, termasuk saat koneksi terputus.

**Status:** koneksi latihan nyata di Android sudah berhasil. Fitur 4 masih memerlukan petunjuk latihan di Home, penyelarasan FR-07, dan verifikasi penanganan kegagalan layanan/koneksi. Menjalankan aplikasi native iOS tetap ditunda.

### Fitur 5 — Tutor mendengar dan menjawab (FR-10/11)

- [x] Pipeline backend menyediakan penerimaan audio pengguna melalui LiveKit/Pipecat dan menyiapkannya untuk pemrosesan suara pada 16 kHz.
- [x] Aturan akhir giliran dikonfigurasi: fixed memakai 700 ms diam; adaptive memakai Smart Turn v3.2 dengan batas diam 3.000 ms bila ujaran terus dinilai belum selesai.
- [x] Pipeline menghubungkan Whisper multilingual untuk transkripsi, Qwen3-1.7B untuk jawaban, dan Kokoro untuk suara Jepang. Kedua kondisi memakai alur yang sama kecuali aturan akhir giliran.
- [x] Prompt tutor mengarahkan jawaban dalam bahasa Jepang, 1–3 kalimat dan maksimal satu pertanyaan, serta menerima ujaran pengguna dalam bahasa Inggris/Jepang.
- [x] Alur suara latihan dengan inferensi nyata berhasil: ujaran dari Android diproses oleh Whisper, Qwen menghasilkan jawaban, dan suara Kokoro dikirim melalui LiveKit serta terdengar di ponsel.
- [ ] Verifikasi akurasi transkripsi ujaran Inggris/Jepang, perilaku fixed/adaptive, serta kepatuhan jawaban terhadap batas bahasa, kalimat, dan pertanyaan pada panggilan nyata.
- [ ] Ukur latensi setiap tahap dan kurangi jeda dari pengguna selesai berbicara sampai jawaban tutor terdengar; jeda masih terasa lama pada uji coba Android. Pengukuran awal pada GPU RTX 4090 (uji sintetis, bukan percakapan nyata): Whisper dan Kokoro masing-masing di bawah 0,2 detik per inferensi setelah warm-up; jeda dari ujaran selesai sampai audio tutor pertama sekitar 1,4–5,6 detik, dengan jeda terlama disebabkan Smart Turn menilai ujaran belum selesai lalu menunggu batas hening 3 detik; audio tutor pertama pada smoke test LiveKit 8,0 detik setelah panggilan dimulai. Pada dua percakapan nyata adaptive di Android (pod baru menyala), ujaran selesai sampai audio tutor pertama di server 1,5 dan 4,1 detik, dengan tahap setelah keputusan EOT (STT, LLM, TTS) terlama 3,9 detik; belum ada data fixed.

**Status:** alur suara latihan Android sudah berjalan dengan inferensi nyata. Fitur 5 masih memerlukan validasi perilaku akhir giliran, akurasi transkripsi, kepatuhan jawaban, serta pengukuran dan perbaikan latensi.

### Fitur 6 — Layar panggilan dan riwayat (FR-12–16)

- [x] Latihan dan pengujian memakai satu layar panggilan dengan ikon utama, tombol akhiri, dan kontrol mute/unmute.
- [ ] Layar panggilan menampilkan avatar tutor dan status panggilan. Saat ini visual utama berupa ikon mikrofon/gelombang suara; status sudah dikelola aplikasi tetapi belum ditampilkan di layar panggilan.
- [x] Backend menyediakan transkrip final pengguna dan teks tutor setelah pemrosesan keluaran suara. Mobile mengambil dan menyimpan transkrip; setelah panggilan, riwayat lokal dapat dibaca menurut urutan giliran, dicari, dan dihapus.
- [ ] Teks ditampilkan di layar panggilan setelah giliran selesai. Saat ini teks dapat dibaca di riwayat setelah panggilan, tetapi belum ditampilkan selama panggilan.
- [ ] Teks tutor yang ditampilkan hanya bagian yang benar-benar terdengar di ponsel, termasuk saat jawaban terpotong. Teks setelah keluaran suara di server belum membuktikan audio terdengar di ponsel.
- [ ] Verifikasi bahwa saat pengguna menyela, tutor menghentikan jawaban yang belum terdengar dan kembali mendengarkan. Mekanisme interupsi Pipecat tersedia, tetapi perilakunya pada panggilan nyata belum tervalidasi.
- [ ] Jika panggilan gagal, aplikasi menampilkan pilihan langsung **Ulangi sesi** atau **Akhiri**. Saat ini kegagalan menampilkan pesan; panggilan yang sudah dibuat disimpan sebagai terputus, dengan akses mencoba lagi melalui riwayat/Home/Testing.

**Status:** Fitur 6 sebagian selesai. Layar bersama, kontrol panggilan, dan riwayat transkrip tersedia; avatar/status, teks selama panggilan, pilihan saat gagal, serta validasi interupsi dan kesesuaian teks dengan audio yang terdengar masih diperlukan.

## Prioritas 3 — Dua sesi pengujian selesai dengan benar

### Fitur 7 — Progres, durasi, dan pengulangan (FR-05/06/16)

- [x] Backend menyimpan setiap panggilan pengujian yang sudah dialokasikan sebagai percobaan tersendiri, termasuk kegagalan persiapan dan panggilan terputus, beserta waktu dan alasan berakhirnya. Percobaan sebelumnya tidak ditimpa saat mengulang.
- [x] Backend menerapkan syarat sesi selesai: berakhir normal, sedikitnya **120 detik (2 menit)** audio mikrofon diterima server, dan bukti panggilan berhasil disimpan. Durasi dihitung dari frame audio yang diterima, bukan waktu sejak ruang dibuka atau penghitung durasi di mobile; waktu tanpa frame audio tidak dihitung.
- [x] Backend mengunci Sesi 2 sampai Sesi 1 valid. Mobile mengikuti status backend dan menampilkan **Testing complete. Thank you!** setelah kedua sesi selesai, tanpa membuat pengujian baru otomatis.
- [x] Mengulang panggilan gagal mempertahankan peserta dan metode sesi yang sama. Backend memakai kunci idempotensi khusus mulai/ulang panggilan: kunci yang sama tidak membuat percobaan kedua; percobaan baru setelah gagal memakai kunci baru. Mobile menyimpan kunci percobaan dan menahan ketukan mulai berulang.
- [ ] Verifikasi dua sesi lengkap di Android dengan panggilan nyata: perhitungan 120 detik saat media terputus, kegagalan penyimpanan bukti, sesi terkunci, retry tanpa hasil ganda, dan tampilan selesai setelah Sesi 2 valid.

**Status:** aturan progres, durasi, dan pengulangan sudah diimplementasikan. Fitur 7 masih memerlukan verifikasi alur nyata di Android bersama Fitur 4–6 dan 8; menjalankan aplikasi native iOS tetap ditunda.

### Fitur 8 — Simpan bukti panggilan (FR-17/18)

- [x] Pada panggilan pengujian setelah persetujuan, backend menyediakan perekaman audio pengguna dan tutor ke dua berkas WAV terpisah. Audio pengguna ditangkap sebelum pemrosesan akhir giliran; latihan tidak memakai penyimpanan bukti penelitian.
- [x] Rekaman, transkrip, waktu, posisi audio, interupsi, dan hasil dihubungkan ke ID percobaan. Berkas audio disimpan terpisah dari database; database menyimpan referensi bukti dan checksum manifest.
- [x] Finalisasi bukti memeriksa keberadaan kedua jalur audio dan menyimpan manifest beserta checksum. Kegagalan perekaman atau penyimpanan bukti tidak menyelesaikan sesi pengujian.
- [x] Mobile mengirim catatan langganan/pelepasan audio tutor beserta urutan dan waktu kejadian; backend memeriksa kepemilikan panggilan dan menahan kejadian duplikat.
- [ ] Aplikasi melaporkan kapan suara tutor benar-benar mulai terdengar di ponsel. Aplikasi sudah melaporkan mulai/berhenti audio tutor terdekode (Fitur 10), tetapi belum divalidasi sesuai suara yang keluar dari speaker.
- [ ] Verifikasi rekaman panggilan nyata, termasuk suara pengguna yang terus berbicara setelah backend terlalu cepat mengambil giliran, interupsi, dan kesesuaian rekaman dengan catatan waktu.

**Status:** Fitur 8 sebagian selesai. Penyimpanan dan pengaitan bukti tersedia; waktu pemutaran tutor di ponsel dan kelengkapan rekaman pada panggilan nyata masih perlu ditangani dan diverifikasi.

### Fitur 9 — Akses data dan kesiapan sistem (FR-19)

- [x] Backend mensyaratkan direktori bukti privat dan tidak menyediakan unduhan rekaman publik. Akses transkrip peserta memerlukan token dan pemeriksaan kepemilikan panggilan.
- [ ] Akses pengambilan rekaman dan catatan oleh petugas berwenang ditetapkan dan diverifikasi. Saat ini pemeriksaan rekaman melalui akses filesystem server; API akses/ekspor petugas belum tersedia.
- [x] Backend mensyaratkan konfigurasi masa retensi dan menyediakan penghapusan berkas bukti yang kedaluwarsa, termasuk rekaman yang belum selesai.
- [ ] Kebijakan penyimpanan, masa retensi, dan penghapusan data disahkan serta diterapkan pada penyimpanan deployment. Penghapusan berkas otomatis belum mencakup penghapusan metadata peserta/percobaan di database.
- [x] Struktur database diperbarui melalui migrasi Alembic. Server memeriksa revisi yang diperlukan saat menyala dan tidak membuat tabel deployment secara otomatis.
- [x] Tes backend dan host mobile tersedia untuk aturan sesi, retry/idempotensi panggilan, izin mikrofon, pemulihan peserta, transkrip, serta penyimpanan bukti.
- [ ] Alur Android diuji menyeluruh dengan layanan dan audio nyata: izin mikrofon, dua kondisi, panggilan gagal, retry, sesi terkunci, interupsi, dan pemisahan latihan dari pengujian. Menjalankan aplikasi native iOS ditunda.

**Status:** Fitur 9 sebagian selesai. Pembatasan dasar akses, mekanisme retensi berkas, migrasi, dan tes komponen tersedia; panggilan latihan Android sudah berhasil pada deployment Runpod. Akses petugas, kebijakan penyimpanan/penghapusan, serta pengujian menyeluruh dua sesi pengujian masih belum selesai.

## Prioritas 4 — Monitoring pengujian

### Fitur 10 — Pantau dan ukur panggilan pengujian

- [x] Backend mencatat event VAD, keputusan akhir giliran (metode, sumber, probabilitas), TTFB STT/LLM/TTS, dan mulai/akhir bicara tutor ke bukti panggilan study. Latihan tidak mencatatnya.
- [x] Aplikasi Android melaporkan mulai/berhenti audio tutor terdekode di ponsel; backend menambahkan waktu terima server untuk estimasi selisih jam.
- [x] Skrip analisis menghasilkan latensi per giliran, batas bawah false cut-off (T = 1/2/3 s), dan sampel anotasi manual.
- [x] Dashboard operator langsung (`/monitor`, dilindungi `MONITOR_TOKEN`) tanpa teks transkrip atau audio.
- [ ] Verifikasi pada panggilan nyata dua metode (panggilan ≥120 detik dengan banyak giliran): kecocokan event dan waktu dengan rekaman, serta ketepatan sumber `timeout`. Dua panggilan pendek adaptive pada pod GPU sudah mencatat event dan menghasilkan `turns.csv`; fixed belum dicoba.
- [ ] Ambang dan kalibrasi deteksi mulai putar di ponsel divalidasi pada perangkat nyata.

**Status:** pencatatan, dashboard, dan skrip analisis sudah diimplementasikan, dideploy, dan dicoba pada dua panggilan adaptive pendek. Fitur 10 belum selesai sampai diverifikasi pada panggilan ≥120 detik untuk kedua metode.

**Batas rencana:** sistem menyediakan panggilan dan data yang dibutuhkan. Rekrutmen peserta, anotasi rekaman, perhitungan statistik, dan UAT penelitian bukan fitur sistem. Sebelum dipakai peserta nyata, teks persetujuan dan kebijakan privasi harus disahkan.
