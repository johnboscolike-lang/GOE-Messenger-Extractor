# -*- coding: utf-8 -*-
"""GOE메신저 추출기 Store 로고 생성 (1080x1080 PNG)"""

from PIL import Image, ImageDraw, ImageFont
import os

W = 1080
cx, cy = W // 2, W // 2
OUT = os.path.join(os.path.dirname(__file__), "GOE메신저추출기_logo_1080.png")


def rounded_rect(draw, xy, radius, fill):
    x0, y0, x1, y1 = xy
    r = radius
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.pieslice([x0, y0, x0 + 2 * r, y0 + 2 * r], 180, 270, fill=fill)
    draw.pieslice([x1 - 2 * r, y0, x1, y0 + 2 * r], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - 2 * r, x0 + 2 * r, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - 2 * r, y1 - 2 * r, x1, y1], 0, 90, fill=fill)


def make_gradient(size, c1, c2, direction="diagonal"):
    """Simple two-color gradient image."""
    img = Image.new("RGBA", (size, size))
    for y in range(size):
        for x in range(size):
            if direction == "diagonal":
                t = (x + y) / (2 * size)
            else:
                t = y / size
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            img.putpixel((x, y), (r, g, b, 255))
    return img


def add_glow(img, center, radius, color, alpha=30):
    """Add a soft radial glow."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(radius, 0, -2):
        a = int(alpha * (i / radius))
        draw.ellipse(
            [center[0] - i, center[1] - i, center[0] + i, center[1] + i],
            fill=(color[0], color[1], color[2], a),
        )
    return Image.alpha_composite(img, overlay)


def _paste_at(src, x, y, canvas_size):
    """Place a small RGBA image at (x, y) on a transparent canvas."""
    tmp = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    tmp.paste(src, (x, y))
    return tmp


def main():
    # Background
    print("배경 생성 중...")
    bg = make_gradient(W, (15, 23, 42), (30, 41, 59), "diagonal")

    # Clip to rounded rect
    mask = Image.new("L", (W, W), 0)
    md = ImageDraw.Draw(mask)
    rounded_rect(md, (0, 0, W, W), 160, fill=255)

    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    canvas.paste(bg, mask=mask)

    # Glows
    print("광효과 추가 중...")
    canvas = add_glow(canvas, (int(W * 0.75), int(W * 0.2)), 380, (37, 99, 235), 25)
    canvas = add_glow(canvas, (int(W * 0.25), int(W * 0.8)), 320, (124, 58, 237), 18)

    draw = ImageDraw.Draw(canvas)

    # ── Icon: blue-purple gradient rounded square ──
    print("아이콘 렌더링 중...")
    icon_size = 380
    icon_x = cx - icon_size // 2
    icon_y = cy - icon_size // 2 - 70
    icon_r = 70

    # Build icon with gradient as a separate RGBA image
    icon_img = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
    for y_off in range(icon_size):
        for x_off in range(icon_size):
            t = (x_off + y_off) / (2 * icon_size)
            r_c = int(37 + (124 - 37) * t)
            g_c = int(99 + (58 - 99) * t)
            b_c = int(235 + (237 - 235) * t)
            icon_img.putpixel((x_off, y_off), (r_c, g_c, b_c, 255))

    # Apply rounded rect mask to icon
    icon_mask = Image.new("L", (icon_size, icon_size), 0)
    imd = ImageDraw.Draw(icon_mask)
    rounded_rect(imd, (0, 0, icon_size, icon_size), icon_r, fill=255)
    icon_img.putalpha(icon_mask)

    # Add highlight on top third
    hd = ImageDraw.Draw(icon_img)
    for y_off in range(icon_size // 3):
        a = int(40 * (1 - y_off / (icon_size / 3)))
        hd.line([(0, y_off), (icon_size, y_off)], fill=(255, 255, 255, a))

    # Composite icon onto canvas
    canvas = Image.alpha_composite(canvas, _paste_at(icon_img, icon_x, icon_y, W))

    # ── "G" letter ──
    print("G 문자 렌더링 중...")
    g_font = None
    for fname in ["segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf", "calibrib.ttf"]:
        try:
            g_font = ImageFont.truetype(os.path.join("C:/Windows/Fonts", fname), 240)
            break
        except (OSError, IOError):
            pass
    if not g_font:
        g_font = ImageFont.load_default()

    # Draw G on a separate layer, then composite
    g_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g_layer)
    g_bbox = gd.textbbox((0, 0), "G", font=g_font)
    g_w = g_bbox[2] - g_bbox[0]
    g_h = g_bbox[3] - g_bbox[1]
    g_x = icon_x + (icon_size - g_w) // 2 - g_bbox[0]
    g_y = icon_y + (icon_size - g_h) // 2 - g_bbox[1] - 8
    gd.text((g_x, g_y), "G", fill=(255, 255, 255, 255), font=g_font)
    canvas = Image.alpha_composite(canvas, g_layer)
    draw = ImageDraw.Draw(canvas)

    # ── Envelope accent ──
    print("편지봉투 아이콘 추가 중...")
    env_cx, env_cy = cx + 130, icon_y + icon_size - 20
    env_w, env_h = 100, 72
    env_r = 12

    env_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ed = ImageDraw.Draw(env_layer)

    # Shadow
    for s in range(8, 0, -1):
        a = int(15 * s / 8)
        rounded_rect(ed,
                      (env_cx - env_w // 2 - s, env_cy - env_h // 2 - s + 4,
                       env_cx + env_w // 2 + s, env_cy + env_h // 2 + s + 4),
                      env_r + s, fill=(0, 0, 0, a))

    # Envelope body
    rounded_rect(ed,
                  (env_cx - env_w // 2, env_cy - env_h // 2,
                   env_cx + env_w // 2, env_cy + env_h // 2),
                  env_r, fill=(255, 255, 255, 255))

    # Envelope flap (V)
    ed.line(
        [(env_cx - env_w // 2 + 10, env_cy - env_h // 2 + 8),
         (env_cx, env_cy + 2),
         (env_cx + env_w // 2 - 10, env_cy - env_h // 2 + 8)],
        fill=(37, 99, 235, 255), width=5, joint="curve"
    )
    canvas = Image.alpha_composite(canvas, env_layer)
    draw = ImageDraw.Draw(canvas)

    # ── Text: GOE메신저 ──
    print("텍스트 렌더링 중...")
    kr_font_bold = None
    kr_font_reg = None
    for fname in ["malgunbd.ttf", "malgun.ttf", "NanumGothicBold.ttf"]:
        try:
            kr_font_bold = ImageFont.truetype(os.path.join("C:/Windows/Fonts", fname), 72)
            break
        except (OSError, IOError):
            pass
    for fname in ["malgun.ttf", "NanumGothic.ttf"]:
        try:
            kr_font_reg = ImageFont.truetype(os.path.join("C:/Windows/Fonts", fname), 42)
            break
        except (OSError, IOError):
            pass

    if not kr_font_bold:
        kr_font_bold = g_font
    if not kr_font_reg:
        kr_font_reg = g_font

    # "GOE메신저"
    title = "GOE메신저"
    tb = draw.textbbox((0, 0), title, font=kr_font_bold)
    tw = tb[2] - tb[0]
    draw.text((cx - tw // 2, cy + 240), title, fill=(255, 255, 255, 255), font=kr_font_bold)

    # "추출기"
    sub = "추출기"
    sb = draw.textbbox((0, 0), sub, font=kr_font_reg)
    sw = sb[2] - sb[0]
    draw.text((cx - sw // 2, cy + 328), sub, fill=(148, 163, 184, 230), font=kr_font_reg)

    # ── Version badge ──
    badge_font = None
    for fname in ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"]:
        try:
            badge_font = ImageFont.truetype(os.path.join("C:/Windows/Fonts", fname), 20)
            break
        except (OSError, IOError):
            pass
    if not badge_font:
        badge_font = ImageFont.load_default()

    badge_y = cy + 395
    rounded_rect(draw, (cx - 40, badge_y - 14, cx + 40, badge_y + 14), 12,
                  fill=(37, 99, 235, 70))
    vb = draw.textbbox((0, 0), "v3.0", font=badge_font)
    vw = vb[2] - vb[0]
    draw.text((cx - vw // 2, badge_y - 11), "v3.0", fill=(96, 165, 250, 230), font=badge_font)

    # ── Save ──
    # Re-apply rounded mask for final output
    final = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    final.paste(canvas, mask=mask)
    final.save(OUT, "PNG")
    size_kb = os.path.getsize(OUT) / 1024
    print(f"\n로고 저장 완료: {OUT}")
    print(f"크기: {W}x{W}px, 파일: {size_kb:.0f}KB")


if __name__ == "__main__":
    main()
