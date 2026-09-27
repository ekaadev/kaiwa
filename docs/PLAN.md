# Rencana Pengembangan Sistem AI Conversation

Acuan: *System Requirements Document* (FR-01–19). Ini rencana **membangun sistem**, bukan menjalankan atau menganalisis penelitian. **Aplikasi** berarti klien mobile Android/iOS; **backend** berarti server; **sistem** berarti keduanya. `[x]` berarti tepat hal yang tertulis sudah berfungsi; `[ ]` berarti belum. Saat ini baru sebagian backend tersedia: aplikasi mobile dan panggilan suara belum ada.

## Prioritas 1 — Pengguna bisa masuk ke alur yang tepat

### Fitur 1 — Pilih latihan atau pengujian (FR-01/02)

- [ ] Aplikasi Android/iOS menampilkan pilihan **AI Conversation** dan **Ikut Pengujian**.
- [ ] AI Conversation membuka satu panggilan latihan tanpa mendaftar sebagai peserta. Sistem memakai adaptive sebagai pilihan awal; data latihan tidak masuk data pengujian.

### Fitur 2 — Daftar sebagai peserta pengujian (FR-03/04)

- [x] Backend hanya menerima pendaftaran yang menyatakan setuju, lalu membuat ID tanpa nama serta mencatat versi dan waktu persetujuan.
- [x] Backend membagi urutan fixed/adaptive secara seimbang dan membuat dua sesi awal. Urutan metode tidak dikirim dalam respons peserta.
- [ ] Aplikasi menampilkan penjelasan dan teks persetujuan yang disahkan sebelum mengirim pendaftaran; menolak berarti tidak mendaftar atau direkam.
- [ ] Pengiriman formulir dua kali tidak membuat dua peserta.

### Fitur 3 — Kembali tanpa kehilangan peserta (FR-05/06)

- [x] Backend memberikan token sekali saat pendaftaran. Dengan token itu, peserta dapat membaca kembali ID dan status kedua sesinya.
- [ ] Aplikasi menyimpan token dengan aman dan membuka progres peserta yang sama saat dijalankan lagi.
- [ ] Pergantian peserta pada ponsel bersama dan tes ulang setelah selesai memerlukan tindakan petugas; data peserta sebelumnya tidak tertimpa.

## Prioritas 2 — Panggilan suara bisa digunakan

### Fitur 4 — Mulai panggilan (FR-07–09)

- [ ] Sebelum menelepon, aplikasi memberi petunjuk singkat bahwa pengguna boleh memilih topik sendiri, tanpa skenario tetap. SRD FR-07 masih meminta skenario tertentu dan perlu diselaraskan dengan keputusan ini.
- [x] Backend dapat memeriksa koneksi database. **Ini belum berarti layanan panggilan siap.**
- [ ] Aplikasi memeriksa izin mikrofon; backend memeriksa kesiapan layanan. Jika ada masalah, panggilan tidak dimulai dan penyebabnya ditampilkan.
- [ ] Backend menyiapkan ruang LiveKit dan akses sementara; aplikasi dan tutor AI melalui Pipecat bergabung ke ruang yang sama. Rahasia layanan tetap di backend.

### Fitur 5 — Tutor mendengar dan menjawab (FR-10/11)

- [ ] Backend menerima audio pengguna dan menyiapkannya untuk pemrosesan suara.
- [ ] Backend mendeteksi akhir giliran: fixed setelah 700 ms diam; adaptive memakai Smart Turn v3.2, dengan batas 3.000 ms bila ujaran terus dinilai belum selesai.
- [ ] Whisper mengubah ujaran menjadi teks, Qwen menyusun jawaban, dan Kokoro membacakannya. Tutor menjawab dalam bahasa Jepang, 1–3 kalimat dan maksimal satu pertanyaan. Kedua kondisi memakai alur yang sama kecuali aturan akhir giliran.

### Fitur 6 — Layar panggilan dan riwayat (FR-12–16)

- [ ] Satu layar panggilan menampilkan avatar, status, dan tombol akhiri untuk latihan maupun pengujian.
- [ ] Teks muncul setelah giliran selesai; teks tutor yang ditampilkan hanya bagian yang benar-benar terdengar. Setelah panggilan, pengguna bisa membaca riwayat berurutan.
- [ ] Jika pengguna menyela, tutor menghentikan jawaban yang belum terdengar dan kembali mendengarkan.
- [ ] Jika panggilan gagal, aplikasi menampilkan **Ulangi sesi** atau **Akhiri**.

## Prioritas 3 — Dua sesi pengujian selesai dengan benar

### Fitur 7 — Progres, durasi, dan pengulangan (FR-05/06/16)

- [ ] Backend mencatat setiap panggilan sebagai percobaan, termasuk yang gagal, beserta waktu dan alasan berakhirnya.
- [ ] Backend menandai sesi selesai hanya jika panggilan berakhir normal, media suara tersambung sedikitnya **120 detik (2 menit)**, dan bukti panggilan yang diperlukan tersimpan. Waktu sebelum tersambung atau saat koneksi terputus tidak dihitung.
- [ ] Sesi 2 hanya terbuka setelah Sesi 1 valid. Setelah Sesi 2 valid, aplikasi menampilkan **Pengujian selesai** tanpa membuat tes baru otomatis.
- [ ] Mengulang panggilan gagal mempertahankan peserta dan metode sesi yang sama. Permintaan mulai/ulang yang terkirim dua kali tidak membuat hasil ganda.

### Fitur 8 — Simpan bukti panggilan (FR-17/18)

- [ ] Setelah persetujuan, backend mengelola rekaman suara pengguna dan tutor secara terpisah; suara pengguna tetap tercatat saat ia melanjutkan bicara setelah backend terlalu cepat mengambil giliran.
- [ ] Backend menghubungkan rekaman, teks, waktu, gangguan, dan hasil tiap percobaan. Aplikasi melaporkan kapan suara tutor mulai terdengar di ponsel; berkas suara disimpan terpisah dari database.

### Fitur 9 — Akses data dan kesiapan sistem (FR-19)

- [ ] Hanya petugas berwenang dapat mengambil rekaman dan catatan terkait; aturan penyimpanan serta penghapusannya ditetapkan.
- [ ] Struktur database bisa diperbarui tanpa mengandalkan pembuatan tabel otomatis saat server menyala.
- [ ] Alur Android/iOS diuji menyeluruh: izin mikrofon, dua kondisi, panggilan gagal, retry, sesi terkunci, interupsi, dan pemisahan latihan dari pengujian.

**Batas rencana:** sistem menyediakan panggilan dan data yang dibutuhkan. Rekrutmen peserta, anotasi rekaman, perhitungan statistik, dan UAT penelitian bukan fitur sistem. Sebelum dipakai peserta nyata, teks persetujuan dan kebijakan privasi harus disahkan.
