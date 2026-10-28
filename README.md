# MyAnimeDex · Instagram otomasyonu

[@myanimedex](https://instagram.com/myanimedex) için ücretsiz ve tam otomatik paylaşım sistemi. Python + Pillow ile marka şablonlarından görsel üretir, GitHub Pages'te barındırır ve Instagram Graph API ile paylaşır. GitHub Actions cron'u ile çalışır. Ücretli servis veya yapay zekâ API'si kullanmaz.

| Gün (UTC) | TR saati | İçerik | Format |
|---|---|---|---|
| Pzt 19:00 | 22:00 | **Airing this week**: bu hafta yayınlanan öne çıkan 5 anime | Carousel (kapak + 5 + kapanış) |
| Çar 19:00 | 22:00 | **App feature**: `content/features.yaml` sırasıyla | Tek görsel |
| Cmt 19:00 | 22:00 | **Top 5 this season**: puana göre, az üyeli olanlar elenmiş | Carousel (kapak + 5 + kapanış) |
| Pzt 14:00 | 17:00 | Hikâye: Anime of the day | Story |
| Sal 14:00 | 17:00 | Hikâye: App tip (`content/tips.yaml`) | Story |
| Çar 14:00 | 17:00 | Hikâye: "Which one are you watching?" (A/B, yanıtla) | Story |
| Per 14:00 | 17:00 | Hikâye: Uygulamayı indir | Story |
| Cum 14:00 | 17:00 | Hikâye: Weekend binge pick | Story |
| Sal 19:00 | 22:00 | **Reel: App demo**: uygulama ekran kaydı + hook (`content/reels.yaml` sırasıyla) | Reel ~8 sn |
| Per 19:00 | 22:00 | **Reel: Episodes this weekend**: Cuma–Pazar yayınlanan 5 anime, posterli | Reel ~13 sn |
| Paz 19:00 | 22:00 | **Reel: Top 5 countdown**: Cumartesi Top 5'in videosu (#5 → #1) | Reel ~15 sn |
| **Paz 12:00** | 15:00 | Haftanın planını kilitler, önizleme Issue'su + artifact | — |

Örnek çıktılar `samples/` klasöründe, örnek açıklamalar `samples/captions.md` dosyasında.

---

## İçindekiler

1. [Nasıl çalışır](#1-nasıl-çalışır)
2. [Meta Developer App kurulumu](#2-meta-developer-app-kurulumu)
3. [Gerekli izinler](#3-gerekli-izinler)
4. [Token alma (süresiz System User token)](#4-token-alma)
5. [Secrets ve ayarlar](#5-secrets-ve-ayarlar)
6. [DRY_RUN ile test ve ilk canlı paylaşım](#6-dry_run-ile-test-ve-ilk-canlı-paylaşım)
7. [Haftalık önizleme ve planı düzenleme](#7-haftalık-önizleme-ve-planı-düzenleme)
8. [features.yaml, metinler ve şablonları düzenleme](#8-içerik-ve-şablonları-düzenleme)
9. [Güvenilirlik ve hata mesajları](#9-güvenilirlik-ve-hata-mesajları)
10. [Lokal geliştirme](#10-lokal-geliştirme)
11. [Bilinen sınırlar ve kurallar](#11-bilinen-sınırlar-ve-kurallar)

---


## Reels

- Videolar Python'da kare kare çizilir (Pillow) ve ffmpeg ile H.264/AAC 1080×1920 30 fps olarak kodlanır (`src/mad/render/reels.py`). GitHub Actions'ta ffmpeg hazır gelir.
- **Müzik**: teaser için Python'da sentezlenmiş özgün müzikten (`assets/audio/`, tamamen sizin) her hafta farklı bir bölüm. Instagram'ın müzik kütüphanesi API ile eklenemez.
- **Trend ses için**: Pazar önizleme Issue'sunda her Reel için 🔇 *sessiz versiyon* linki var. İndirip telefondan Instagram'da trend bir ses ekleyerek paylaşabilirsiniz (o zaman o haftanın otomatik Reel'ini planda `"skip": true` yapın).
- **Kapak**: her Reel'in ilk saniyelerinden bir kare `cover.jpg` olarak üretilir ve kapak olarak gönderilir.
- **App demo** sırası `content/reels.yaml` → `demos`. Yeni klip eklemek için dikey ekran kaydını `assets/clips/` altına koyup listeye `hook`, `title`, `sub`, `clip` ile ekleyin.
- **Teaser** elle: *Actions → Reel → Run workflow → type: reel_teaser*.
- Reels hem Reels sekmesinde hem ana akışta görünür (`share_to_feed=true`).

## 1. Nasıl çalışır

```
AniList GraphQL ──► planner (seçim + açıklama) ──► plans/2026-W45.json  (Pazar kilitlenir)
                                                        │
                       Pillow şablonları ◄──────────────┘
                              │ JPEG
                              ▼
               gh-pages dalı ──► GitHub Pages (herkese açık URL)
                              │
                              ▼
     Instagram Graph API: container oluştur → FINISHED bekle → media_publish
                              │
                              ▼
               state/posted_state.json (main dalına commit)
```

- **Veri: AniList.** Jikan (MyAnimeList'in gayriresmî API'si) 2026'da kapandı. AniList ücretsizdir, anahtar istemez ve MAL ID'lerini de içerir. İstemci istekleri ~2,1 sn aralıkla gönderir, 429 ve 5xx hatalarında artan aralıklarla tekrar dener, yanıtları 6 saat diskte cache'ler (`.cache/anilist`, Actions'ta da cache'lenir). Özet metni (synopsis) **hiç çekilmez**; kapak görselleri `.cache/covers` altına indirilip görsele işlenir.
- **"Üye sayısı"**: AniList `popularity` alanı, yani animeyi listesine eklemiş kullanıcı sayısı. Görsellerde "ON LISTS" olarak gösterilir.
- **Görseller**: JPEG. Instagram API yalnızca JPEG kabul eder. Postlar 1080×1350, hikâyeler 1080×1920. Hikâyelerde üst ve alt 250 px boş bırakılır.
- **Barındırma**: GitHub Pages, `gh-pages` dalı. Dal her seferinde tek bir commit olarak yeniden yazılır, böylece repo şişmez. 30 günden eski medya silinir.

```
.github/workflows/  post.yml · story.yml · weekly-preview.yml
.github/actions/setup/       Python + pip + AniList cache
src/mad/
  __main__.py      komut satırı: run | plan | preview | check | samples
  anilist.py       GraphQL istemcisi (throttle, retry, cache)
  planner.py       takvim, seçim kuralları, haftalık plan
  captions.py      açıklama şablonları + etiket kuralları
  render/base.py   çizgi roman primitive'leri, palet, fontlar
  render/templates.py  tüm post/hikâye şablonları
  hosting.py       gh-pages'e yükleme + URL'nin açılmasını bekleme
  instagram.py     Graph API: tekli, carousel, STORIES
  state.py         posted_state.json
content/  features.yaml · tips.yaml · captions.yaml · hashtags.yaml
assets/   logo.png · fonts/ (OFL) · screenshots/
config.yaml        eşikler, cooldown, URL'ler, API sürümü
state/posted_state.json   plans/   samples/
```

---

## 2. Meta Developer App kurulumu

**Ön koşullar** (sizde zaten var, sadece kontrol edin):
- @myanimedex bir **Instagram İşletme (Business)** hesabı ve "Myanimedex" Facebook sayfasına bağlı.
- Sayfa ve Instagram hesabı bir **Meta Business portföyünde** (business.facebook.com) duruyor. Bu, süresiz token için gerekli.

**Adımlar:**

1. <https://developers.facebook.com/apps> → **Create app**.
2. Use case olarak **Other**'ı seçin → **Next** → app type **Business** → **Next**.
3. Uygulama adı: `MyAnimeDex Publisher`, iletişim e-postası: `support@myanimedex.com`. **Business portfolio** olarak MyAnimeDex portföyünü seçin → **Create app**.
4. App Dashboard → **Add product** bölümünden şunları ekleyin:
   - **Instagram** → *API setup with Facebook login*
   - **Facebook Login for Business** (token üretimi için)
5. **App settings → Basic**:
   - Privacy Policy URL: `https://myanimedex.com/privacy.html`
   - Terms of Service URL: `https://myanimedex.com/terms.html`
   - Category: *Entertainment*. İsterseniz logo yükleyin. **Save changes**.
6. **App Mode** Development'ta kalabilir. Kendi portföyünüzdeki sayfa ve hesap için *Standard Access* yeterli, **App Review gerekmez**. Token üretirken izin hatası alırsanız uygulamayı **Live** moda alın (Privacy Policy URL bunun için gerekli).

---

## 3. Gerekli izinler

| İzin | Neden |
|---|---|
| `instagram_basic` | IG hesabını ve medya bilgisini okumak |
| `instagram_content_publish` | Container oluşturmak ve paylaşmak (post, carousel, story) |
| `pages_show_list` | Bağlı sayfayı ve IG hesabını bulmak |
| `pages_read_engagement` | Sayfa üzerinden IG hesabına erişim (Meta bunu birlikte ister) |
| `business_management` | System User token'ının portföy varlıklarına erişimi |

`python -m mad check` komutu (ve her Pazar önizleme workflow'u) token'daki izinleri listeler ve eksik varsa hata verir.

---

## 4. Token alma

### Önerilen yol: System User token (süresi dolmaz)

1. <https://business.facebook.com/settings> → **Users → System users** → **Add**.
   Ad: `myanimedex-bot`, rol: **Admin** → **Create system user**.
2. Uygulamayı portföye bağlayın: **Accounts → Apps**. 3. adımda portföy seçtiyseniz uygulama zaten listededir. Değilse **Add → Connect an app ID**.
3. System user seçiliyken **Assign assets**:
   - **Pages → Myanimedex** → *Full control* (en azından *Content* izni)
   - **Instagram accounts → @myanimedex** → *Full control*
   - **Apps → MyAnimeDex Publisher** → *Develop app* / *Full control*
4. **Generate new token**:
   - App: `MyAnimeDex Publisher`
   - **Token expiration: Never**
   - İzinler: 3. bölümdeki beş izin
   - **Generate token** → token'ı kopyalayın. Bir daha gösterilmez.
5. Kontrol: <https://developers.facebook.com/tools/debug/accesstoken/> sayfasına yapıştırın. **Expires: Never** yazmalı.
6. **IG_USER_ID**'yi bulun. Bu, Instagram işletme hesabının ID'sidir; kullanıcı adı değildir:
   ```bash
   curl -s "https://graph.facebook.com/v24.0/me/accounts?fields=name,instagram_business_account&access_token=TOKEN_BURAYA"
   ```
   Çıktıdaki `instagram_business_account.id` değeri (ör. `17841400000000000`) IG_USER_ID'dir.

> Token'ı hiçbir dosyaya, issue'ya veya commit'e yazmayın. Sadece GitHub Secrets'ta durmalı.

### Alternatif: Page token (System User kullanmadan, yine süresiz)

1. [Graph API Explorer](https://developers.facebook.com/tools/explorer/)'da uygulamanızı seçin, 3. bölümdeki izinlerle **User token** üretin (kısa ömürlü, ~1 saat).
2. Bu token'ı 60 günlük token ile değiştirin (App ID ve App Secret, *App settings → Basic* sayfasında):
   ```bash
   curl -s "https://graph.facebook.com/v24.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=KISA_TOKEN"
   ```
3. 60 günlük token ile `GET /me/accounts?fields=access_token,instagram_business_account` çağrısını yapın. Buradan dönen **Page access token**'ın süresi dolmaz (Debugger'da *Expires: Never*). Bunu `ACCESS_TOKEN` olarak kaydedin.
4. Şifrenizi değiştirirseniz veya uygulamanın iznini kaldırırsanız token geçersiz olur. Bu yüzden System User yöntemi daha sağlamdır.

**Token bozulursa:** Pazar önizleme workflow'u her hafta token'ı kontrol eder. Sorun olursa Issue'nun en üstünde 🔴 görünür ve workflow kırmızı biter (GitHub size e-posta gönderir). Paylaşım sırasında token geçersizse log şöyle der: `ACCESS_TOKEN is invalid or expired. Generate a new token (see README → Token)`. Bu durumda yeni bir token üretip secret'ı güncelleyin.

---

## 5. Secrets ve ayarlar

Repo → **Settings → Secrets and variables → Actions**:

| Tür | Ad | Değer |
|---|---|---|
| Secret | `IG_USER_ID` | 4. bölüm, 6. adımdaki ID |
| Secret | `ACCESS_TOKEN` | System User token |
| Variable | `DRY_RUN` | Başlangıçta `true`. Canlıya geçince `false` |

`DRY_RUN=true` iken zamanlanmış işler görselleri ve açıklamaları üretir (artifact olarak indirilebilir) ama **paylaşmaz**. Kurulumda bu değişken `true` olarak ayarlandı.

**GitHub Pages**: *Settings → Pages → Build and deployment → Deploy from a branch → `gh-pages` / `(root)`*. Kurulumda bu da ayarlandı. Görseller `https://hasankokes.github.io/myanimedex-social/media/...` altında yayınlanır.

**Actions izinleri**: *Settings → Actions → General → Workflow permissions* altında **Read and write permissions** seçili olmalı. Bot, `state/` ve `plans/` klasörlerini commit'ler ve `gh-pages`'e push eder.

---

## 6. DRY_RUN ile test ve ilk canlı paylaşım

1. **Actions → Post → Run workflow**:
   - `type`: `top5` (veya `scheduled`)
   - `dry_run`: ✅ (varsayılan)
   → Çalışma bitince **Artifacts → post-…** zip'ini indirin. Görseller ve `caption.txt` içinde.
   Açıklama ayrıca job özetinde (Summary) görünür.
2. Aynısını **Story** workflow'u için de yapın (`story_your_pick` vb.).
3. **Token kontrolü**: Actions → *Weekly preview* → Run workflow. Issue'nun en üstünde `🟢 Token OK` görünmeli.
4. **İlk canlı deneme (önerilen: hikâye)**: Actions → Story → Run workflow → `type: story_download`, `dry_run`: ☐ (işareti kaldırın).
   Log sırası: `Publishing quota` → `Pushed … gh-pages` → `All image URL(s) are live` → `Created story container` → `FINISHED` → `Published`.
   Hikâye 24 saat sonra kendiliğinden kaybolur. Bu yüzden ilk deneme için en güvenli seçenek budur.
5. Sorun yoksa **Variables → `DRY_RUN` = `false`**. Bundan sonra cron otomatik paylaşır.

Elle tetiklemede `dry_run` kutusu, `DRY_RUN` değişkeninden bağımsızdır. Yani değişken `true` iken de tek bir canlı deneme yapabilirsiniz. Zamanlanmış işler ise yalnızca değişkene bakar.

Ek girdiler: `date` (o UTC günüymüş gibi çalıştırır), `force` (o slot daha önce paylaşıldıysa bile tekrar paylaşır).

---

## 7. Haftalık önizleme ve planı düzenleme

Her **Pazar 12:00 UTC**'de *Weekly preview* workflow'u şunları yapar:

1. Ertesi haftanın planını üretir ve `plans/2026-W45.json` olarak commit'ler. Plan seçilen animeleri, o anki verilerini (puan, üye sayısı…) ve açıklamaları dondurur.
2. Bütün görselleri bu plandan üretir. Pazartesi–Cumartesi paylaşımları **aynı plandan** üretildiği için önizlemede gördüğünüz neyse o paylaşılır.
3. `Weekly preview · 2026-W45` başlıklı bir Issue açar: küçük resimler (Pages'ten) ve açılır açıklamalar. Geçen haftanın Issue'sunu kapatır.
4. Tam boy görselleri **artifact** olarak yükler (30 gün saklanır).
5. Instagram token'ını kontrol eder.

**Değişiklik yapmak için** `plans/<hafta>.json` dosyasını GitHub üzerinde düzenleyin:
- Açıklamayı değiştirmek: ilgili slotun `"caption"` alanını düzenleyin.
- Bir paylaşımı atlamak: slota `"skip": true` ekleyin.
- Haftayı baştan seçmek: *Weekly preview → Run workflow → force* ✅. Önizleme yeniden üretilir ve Issue güncellenir.
- Anime değiştirmek: en kolay yol `force` ile yeniden üretmek. Ya da `config.yaml` eşiklerini değiştirip yeniden üretin.

Plan yoksa (ör. ilk hafta), günlük iş planı o anda kendisi üretir ve logda uyarı verir.

---

## 8. İçerik ve şablonları düzenleme

### `content/features.yaml` (Çarşamba postu)
```yaml
features:
  - id: airing-calendar             # benzersiz, bir daha değiştirmeyin
    title: Never miss a new episode # görseldeki başlık (~40 karakter)
    description: The airing calendar shows every episode ...  # 1–2 cümle (~160 karakter)
    kicker: APP FEATURE             # opsiyonel küçük etiket
    screenshot: assets/screenshots/calendar-myweek.webp   # opsiyonel, dikey PNG/JPG/WebP
    mask:                           # opsiyonel: gizlenecek alanlar [x0, y0, x1, y1] (nadiren gerekir)
    caption: |                      # opsiyonel: hazır açıklama yerine kendi metniniz
      ...
    enabled: true                   # false = atla
```
- Liste yukarıdan aşağıya sırayla döner. Son paylaşılan `id` state'te tutulur. Araya yeni özellik ekleyebilirsiniz, sıra korunur.
- **Ekran görüntüsü varsa** post 2 slaytlık bir carousel olur: 1. slayt tipografik kart ("SEE IT →"), 2. slayt telefon çerçevesinde uygulama ekranı ("IN THE APP"). Açıklamaya "👉 Swipe to see it in the app." satırı eklenir. Ekran görüntüsü yoksa tek görsel paylaşılır.
- Ekran görüntüleri uygulamanın **güncel** hâlini göstermeli. Uygulama ekranlarındaki anime kapakları görünür kalır. `mask` alanı yalnızca bir şeyi gizlemek gerektiğinde (ör. kişisel bilgi) kullanılır.
- Şu anki girdiler **örnektir**. Kendi metinlerinizle değiştirin.

### Ekran görüntüsü kütüphanesi (`assets/screenshots/app/`)
Simülatörde (iPhone 17 Pro, uygulama 1.0.16, İngilizce arayüz, 9:41 durum çubuğu) çekilmiş güncel ekranlar. Genişlik 900 px. `features.yaml` ve `tips.yaml` dosyalarındaki `screenshot:` alanında doğrudan kullanılabilir.

| Klasör | İçerik |
|---|---|
| `dark/`, `light/` | home, calendar, my_week, anime_detail, discover, for_you, this_season, arena, language, premium, profile, watching, favorites, lists, list_detail, stats, top10, reviews |
| `themes/` | `<tema>_<dark|light>_<home|profile>.jpg`: sakura, midnight, matcha, crimson, violet |

Örnek: `screenshot: assets/screenshots/app/light/for_you.jpg`. Uygulama değiştikçe ekranları yeniden çekin (eski görsel kullanmayın).

### `content/tips.yaml` (Salı hikâyesi)
Alanlar `id`, `title`, `text`, opsiyonel `screenshot` ve `enabled`. Sıralı döner.

### `content/captions.yaml`
Her içerik türü için birden fazla İngilizce şablon var. Varyant her hafta değişir (hafta numarası mod şablon sayısı). Kullanılabilen yer tutucular dosyanın başında listelenmiştir. İlk satırda doğal arama ifadeleri kullanın ("new anime this season", "what to watch this week", "best anime of Fall 2026"). Etiketleri buraya **yazmayın**, otomatik eklenir.

### `content/hashtags.yaml`
- Sıra: `#anime #animerecommendations` + sezon etiketi (`#fall2026anime`) + anime adı etiketi + `#myanimedex`. Toplam 3–5 etiket.
- Anime adı etiketi başlıktan otomatik üretilir (`The Apothecary Diaries Season 3` → `#theapothecarydiaries`). 24 karakterden uzunsa eklenmez. Elle belirlemek için `name_overrides` alanına AniList ID'si ile yazın.
- `banned_substrings`: korsanla ilişkilendirilen veya "ücretsiz izle" türü etiketler (`izle`, `free`, `download`, `stream`, `9anime`…). Bu listeye takılan etiket sabit bir etiketse paylaşım **hiç başlamaz**. Anime adından üretilmiş bir etiketse sadece o etiket atlanır.

### `config.yaml`
Popülerlik eşikleri (`top5_min_popularity` = Top 5'e girmek için gereken minimum üye sayısı), tekrar paylaşmama süresi (`anime_cooldown_days`, varsayılan 21 gün), ülke ve format filtreleri, hariç tutulan türler, mağaza linkleri, Graph API sürümü.

### Şablonlar ve renkler
- Palet ve fontlar: `src/mad/render/base.py` dosyasının başında (`YELLOW #FACC15`, `TEAL`, `MAGENTA`, `INK`, `CREAM`).
- Her şablon `src/mad/render/templates.py` içinde ayrı bir fonksiyon (`_airing_cover`, `_top5_slide`, `render_story_weekend`…). Koordinatlar piksel cinsinden.
- Fontlar (`assets/fonts/`, hepsi SIL OFL): **Bangers** (çizgi roman başlıkları), **Anton** (anime adları ve rakamlar), **Barlow / Barlow Condensed** (metin).
- Logo: `assets/logo.png` (şeffaf PNG). Değiştirirseniz kenar boşlukları otomatik kırpılır.
- Değişiklikten sonra örnekleri yeniden üretin: `python -m mad samples`.

---

## 9. Güvenilirlik ve hata mesajları

- **Yarım paylaşım olmaz.** Sıra şöyledir:
  1. Önce bütün görseller üretilir ve yüklenir, URL'lerin gerçekten açıldığı doğrulanır.
  2. Sonra tüm container'lar oluşturulur ve hepsinin `FINISHED` olması beklenir.
  3. `media_publish` ancak bundan sonra **bir kez** çağrılır.

  Arada herhangi bir hata olursa log `... Nothing was published.` der ve iş kırmızı biter. Hesapta hiçbir şey görünmez; yayınlanmayan container'lar 24 saatte kendiliğinden silinir.
- **Çift paylaşım olmaz.** Paylaşılan her slot (`2026-11-02:post`) `posted_state.json`'a yazılır. Aynı iş tekrar çalışırsa `already published` der ve çıkar (`force` ile aşılabilir). `media_publish` zaman aşımına uğrarsa tekrar denemeden önce container'ın `PUBLISHED` olup olmadığı kontrol edilir.
- **Aynı anime kısa sürede tekrar gelmez.** Paylaşılan animeler tarihleriyle state'e yazılır ve 21 gün boyunca seçilmez (Top 5 hariç: o gerçek sıralamayı gösterir ve geçen haftaya göre ▲/▼/NEW hareketini işaretler).
- **Tekrar denemeler**: AniList (429 / 5xx), Graph API'nin geçici hata kodları (rate limit, medya indirilemedi), GitHub Pages yayını (en fazla 10 dk bekler), state push'u (5 deneme).
- Üç workflow aynı `concurrency` grubunda sırayla çalışır, birbirlerinin state commit'lerini ve `gh-pages` push'larını ezmez. GitHub bir grupta yalnızca **bir** bekleyen iş tutar: elle art arda üç iş başlatırsanız ortadaki iptal olabilir (zamanlanmış saatler çakışmadığı için cron'u etkilemez). Gerekirse iptal olanı yeniden çalıştırın.

| Log mesajı | Ne yapmalı |
|---|---|
| `Missing secret(s): IG_USER_ID, ACCESS_TOKEN` | 5. bölüm |
| `ACCESS_TOKEN is invalid or expired` | 4. bölüm, yeni token |
| `Missing permission ...` | Token'ı 3. bölümdeki izinlerle yeniden üretin |
| `GitHub Pages did not serve ... within 600s` | Settings → Pages kaynağı `gh-pages` mi? Repo public mi? |
| `Instagram could not download the image URL` | Aynı. Ayrıca URL'yi tarayıcıda açıp kontrol edin |
| `Instagram publishing limit reached` | 24 saatlik API kotası doldu, ertesi gün tekrar deneyin |
| `AniList unavailable after 5 attempts` | AniList geçici olarak kapalı, işi yeniden çalıştırın |
| `... only N eligible anime (need 5)` | `config.yaml` eşiklerini düşürün (sezon başında olabilir) |
| `Could not push state/plans` | Paylaşım yapıldıysa `state/posted_state.json`'ı elle güncelleyin |

---

## 10. Lokal geliştirme

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export PYTHONPATH=src

python -m mad run --slot post --type top5 --dry-run       # tek bir içerik üret → out/
python -m mad run --slot story --date 2026-11-04 --dry-run  # o günün planlı hikâyesi
python -m mad preview --next                                # gelecek haftanın planı + önizleme → out/preview/
python -m mad samples                                       # samples/ klasörünü yeniden üret
IG_USER_ID=... ACCESS_TOKEN=... python -m mad check         # token kontrolü
```

Lokal `--dry-run` çalıştırmaları hiçbir şey yüklemez veya paylaşmaz. Plan dosyasını yazabilir; bunu commit'lemek isteyip istemediğinize siz karar verin.

---

## 11. Bilinen sınırlar ve kurallar

- **Hikâye çıkartmaları**: Anket, quiz, soru ve link çıkartmaları API ile eklenemiyor. Hikâyeler bu yüzden "Reply with A or B" (yanıtlar DM'e düşer) ve "Link in bio" ile tasarlandı. İsterseniz paylaşımdan sonra uygulamadan elle anket ekleyebilirsiniz.
- **Hikâyelerin açıklaması yoktur.** Etiketler sadece postlarda bulunur.
- **Zamanlama (tick)**: GitHub zamanlanmış işleri saatlerce geç başlatabiliyor (Ekim 2026'da 5 saate kadar). Bu yüzden her içerik için ayrı cron yok; `tick.yml` her 10 dakikada bir çalışır ve vakti gelmiş, henüz paylaşılmamış slotları yayınlar (hikâye 14:00, post/reel 19:00 UTC). Bir tick gecikirse ya da düşerse sonraki yakalar. Hata olursa 30 dakika arayla en fazla 3 kez denenir; e-posta sadece son denemede gelir. Slot 6 saat içinde çıkamazsa gece yarısı paylaşım olmasın diye atlanır (`config.yaml` → `schedule`). Post/Story/Reel workflow'ları artık sadece elle çalıştırmak içindir.
- **60 gün kuralı**: GitHub, 60 gün commit almayan public repolarda cron'u durdurur. Bot her hafta plan ve state commit'lediği için bu olmaz.
- **Telif**: MyAnimeList veya AniList özet metinleri kullanılmaz; sadece puan, tarih, tür, bölüm sayısı ve stüdyo gibi olgusal veriler kullanılır. Anime gösteren şablonlarda (bu haftanın yayınları, Top 5, anime of the day, weekend pick, A/B) AniList'teki resmî kapak görseli kullanılır; kapak indirilemezse o görsel tipografik düzene düşer, paylaşım durmaz. Uygulama ekran görüntülerindeki kapaklar da olduğu gibi görünür. Görsellerde küçük bir "Data: AniList" kaynak notu var.
- **Korsan etiketleri** (`#animeizle` vb.) yasak listesindedir ve yayını engeller.
- Graph API sürümü `config.yaml` → `instagram.graph_version`. Meta sürümleri yaklaşık 2 yıl destekler; yılda bir güncellemek yeterli.
