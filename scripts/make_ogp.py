#!/usr/bin/env python3
"""OGP 画像 1200×630（ライトテーマ・中央寄せ・文字大きく・マスコット入り）。

**件数を焼き込まない。** 収録件数は毎日変わるので、画像に入れると古い数字が
SNSのカードに残り続ける。

  /usr/bin/python3 scripts/make_ogp.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "static", "ogp.png")
MASCOT = "/home/kojima/work/kurage_web/images/kurage-mascot-cutout.png"
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

img = Image.new("RGB", (W, H), "#ffffff")
dr = ImageDraw.Draw(img, "RGBA")
dr.ellipse([-180, -240, 480, 380], fill=(230, 244, 242, 255))
dr.ellipse([W - 460, H - 330, W + 220, H + 240], fill=(240, 246, 246, 255))
mascot = None
if os.path.exists(MASCOT):
    mascot = Image.open(MASCOT).convert("RGBA")
    mh = 300
    mascot = mascot.resize((int(mascot.width * mh / mascot.height), mh))
cx = 520 if mascot else W // 2
f_badge = ImageFont.truetype(FM, 26)
f_h = ImageFont.truetype(FB, 60)
f_h2 = ImageFont.truetype(FB, 46)
f_s = ImageFont.truetype(FR, 28)
f_brand = ImageFont.truetype(FM, 30)

badge = "出典：Jグランツ（デジタル庁）"
bw = dr.textlength(badge, font=f_badge) + 40
dr.rounded_rectangle([cx - bw / 2, 92, cx + bw / 2, 140], radius=24, fill="#e6f4f2", outline="#bfe3de")
dr.text((cx, 116), badge, font=f_badge, fill="#0a726b", anchor="mm")
dr.text((cx, 220), "会社の条件を選ぶだけで、", font=f_h, fill="#12202f", anchor="mm")
dr.text((cx, 300), "いま出せる補助金が出る。", font=f_h2, fill="#0a9a8f", anchor="mm")
# マスコットに重ならない幅で切る。長い一文を入れると右端が隠れる。
dr.text((cx, 372), "地域・業種・人数・やりたいことで絞り込み。", font=f_s, fill="#5d6b7a", anchor="mm")
dr.text((cx, 412), "補助率・上限額・締切・公式ページまで出ます。", font=f_s, fill="#5d6b7a", anchor="mm")
dr.rounded_rectangle([cx - 200, 470, cx + 200, 530], radius=16, fill="#0a9a8f")
dr.text((cx, 500), "Kurage 補助金ナビ", font=f_brand, fill="#ffffff", anchor="mm")
if mascot:
    img.paste(mascot, (W - mascot.width - 40, H - mascot.height - 30), mascot)
dr.text((40, H - 40), "kurage.exbridge.jp/khojokin.php/", font=ImageFont.truetype(FR, 22),
        fill="#5d6b7a", anchor="lm")
img.save(OUT, optimize=True)
print(OUT, img.size)
