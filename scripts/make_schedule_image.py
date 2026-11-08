"""Renders docs/takvim.png — the weekly schedule (Turkish, TR times) to keep on the phone.

    PYTHONPATH=src python scripts/make_schedule_image.py
"""
from mad.config import ROOT
from mad.render.base import CREAM, INK, MAGENTA, TEAL, WHITE, YELLOW, Canvas, mix

DAYS = [
    ("PAZARTESİ", [("17:00", "Hikâye", "Günün animesi"), ("22:00", "Post", "Bu hafta yayınlananlar · carousel")]),
    ("SALI", [("17:00", "Hikâye", "Uygulama ipucu"), ("22:00", "Reel", "Guess the anime · quiz")]),
    ("ÇARŞAMBA", [("17:00", "Hikâye", "Hangisini izliyorsun? A / B"), ("22:00", "Post", "Uygulama özelliği · carousel")]),
    ("PERŞEMBE", [("17:00", "Hikâye", "Uygulamayı indir"), ("22:00", "Reel", "If you liked X / Hafta sonu bölümleri")]),
    ("CUMA", [("17:00", "Hikâye", "Hafta sonu binge önerisi")]),
    ("CUMARTESİ", [("22:00", "Post", "Top 5 · her hafta farklı lens")]),
    ("PAZAR", [("15:00", "Önizleme", "Gelecek hafta + performans raporu"), ("22:00", "Reel", "Tier list / Top 5 geri sayımı")]),
]
NOTES = [
    ("Facebook:", "Post ve Reel'ler sayfaya da gider (hikâye hariç)"),
    ("Durdurmak:", "GitHub > Settings > Variables > DRY_RUN = true"),
    ("Sorun olursa:", "GitHub e-posta atar, yarım paylaşım olmaz"),
    ("Her Pazar:", "Issue: önizleme, izlenme raporu, token"),
    ("Yeni token:", "Actions > Token check'i çalıştır"),
    ("Trend ses:", "Issue'daki sessiz Reel'i indir, telefondan at"),
    ("Zamanlama:", "Supabase pg_cron, dakikasında; 2 tekrar deneme"),
]
FB_BLUE = (24, 119, 242)
TYPE = {"Hikâye": (TEAL, INK), "Post": (YELLOW, INK), "Reel": (MAGENTA, WHITE), "Önizleme": (CREAM, INK)}

W = 1080
c = Canvas((W, 2600), INK)
c.halftone(mix(INK, TEAL, 0.28), origin="tr", max_r=11, spacing=30)
c.logo((60, 50), 120)
c.text((1020, 80), "OTOMASYON TAKVİMİ", "condensed", 58, fill=YELLOW, anchor="ra")
c.text((1020, 150), "@myanimedex · saatler Türkiye saati", "body_bold", 30, fill=CREAM, anchor="ra")


def fb_badge(cx, cy, r=24):
    c.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=FB_BLUE, outline=WHITE, width=3)
    c.text((cx + 2, cy + 2), "f", "body_xbold", int(r * 1.6), fill=WHITE, anchor="mm")


fb_badge(1000 - c.width_of("Instagram + Facebook", "body_bold", 26) - 26, 218, 18)
c.text((1020, 218), "Instagram + Facebook", "body_bold", 26, fill=mix(CREAM, INK, 0.25), anchor="rm")
y = 270
for name, items in DAYS:
    h = 70 + len(items) * 92
    c.panel((50, y, 1030, y + h), fill=mix(INK, WHITE, 0.07), border=4, shadow=10, radius=26,
            outline=mix(INK, WHITE, 0.25), shadow_color=mix(INK, MAGENTA, 0.5))
    c.text((80, y + 44), name, "display", 44, fill=YELLOW, anchor="lm")
    yy = y + 92
    for t, typ, desc in items:
        bg, fg = TYPE[typ]
        c.text((80, yy + 30), t, "display", 46, fill=WHITE, anchor="lm")
        box = c.chip((230, yy + 5), typ.upper(), size=28, fill=bg, fg=fg, shadow=0, border=3)
        room = (930 if typ in ("Post", "Reel") else 1000) - box[2] - 22
        size = 32
        while size > 24 and c.width_of(desc, "body_bold", size) > room:
            size -= 1
        c.text((box[2] + 22, yy + 30), desc, "body_bold", size, fill=CREAM, anchor="lm")
        if typ in ("Post", "Reel"):
            fb_badge(980, yy + 30)
        yy += 92
    y += h + 26
bh = 90 + len(NOTES) * 58
c.panel((50, y, 1030, y + bh), fill=CREAM, border=6, shadow=12, radius=26, shadow_color=TEAL)
c.text((80, y + 44), "BİLMEN GEREKENLER", "display", 40, fill=INK, anchor="lm")
yy = y + 110
for k, v in NOTES:
    c.text((80, yy), k, "body_xbold", 30, fill=MAGENTA, anchor="lm")
    c.text((330, yy), v, "body_bold", 28, fill=INK, anchor="lm")
    yy += 58
end = y + bh
c.text((540, end + 55), "github.com/hasankokes/myanimedex-social", "body_bold", 28, fill=mix(CREAM, INK, 0.3),
       anchor="mm")
c.im.crop((0, 0, W, end + 100)).save(ROOT / "docs" / "takvim.png", optimize=True)
print("docs/takvim.png written")
