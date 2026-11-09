#!/usr/bin/env python3
"""Build three promo videos (960x540 @30fps): AI-polish demo, CLI demo, and the
dad/mail/internet-bill cartoon with a muxed panic line. PIL frames + ffmpeg."""
import subprocess, sys, os, textwrap
from PIL import Image, ImageDraw, ImageFont

FPS = 30
W, H = 960, 540
LIB = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
LIBB = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf"
MONO = "/usr/share/fonts/google-noto/NotoSansMono-CondensedMedium.ttf"

def F(size, bold=True): return ImageFont.truetype(LIBB if bold else LIB, size)
def M(size): return ImageFont.truetype(MONO, size)

DARK = (11, 10, 18)
SKY = (120, 170, 235)

def base(bg=DARK):
    return Image.new("RGB", (W, H), bg)

def rr(d, box, rad, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=rad, fill=fill, outline=outline, width=width)

def rtext(d, xy, text, font, fill, anchor="la"):
    d.text(xy, text, font=font, fill=fill, anchor=anchor)

def fade_to_black(frames, n=6):
    bl = Image.new("RGB", (W, H), DARK)
    for k in range(n):
        out = []
        src = frames[-1]
        t = k / max(1, n - 1)
        out.append(Image.blend(src.convert("RGB"), bl, t))
        frames.extend(out)

# ---------------------------------------------------------------- helpers: UI
def draw_bar(d, prompt, score, tok, note):
    # composer box
    rr(d, [40, 120, 920, 200], 14, fill=(26, 24, 42), outline=(60, 55, 90), width=1)
    rtext(d, (60, 140), prompt if prompt else "Type to ask Hermes anything…",
          F(22), (220, 216, 240), "la")
    rr(d, [760, 134, 902, 186], 10, fill=(139, 126, 240))
    rtext(d, (831, 160), "Send", F(18), DARK, "mm")
    # BetterPrompt bar
    rr(d, [40, 216, 920, 268], 10, fill=(18, 30, 32), outline=(125, 245, 176), width=1)
    rtext(d, (56, 230), "BetterPrompt", F(16, True), (125, 245, 176), "la")
    rtext(d, (180, 230), "force", F(14), (150, 148, 180), "la")
    # score bar
    rr(d, [240, 228, 420, 256], 8, fill=(40, 38, 60))
    rr(d, [240, 228, 240 + int(180 * score / 100), 256], 8, fill=(125, 245, 176))
    rtext(d, (436, 242), f"{score} · {tok} tok", F(16, True), (235, 232, 255), "lm")
    rtext(d, (560, 242), note, F(14), (140, 138, 170), "lm")
    # buttons
    btns = [("✨ AI polish", (139, 126, 240), True),
            ("🎯 Fine-tune", (30, 28, 48), False),
            ("🤖 AI generate", (139, 126, 240), False),
            ("✍️ Offline · 0 tokens", (30, 28, 48), False)]
    x = 700
    for label, col, filled in btns:
        w = 22 + len(label) * 8
        rr(d, [x, 226, x + w, 258], 7, fill=col, outline=(139, 126, 240) if not filled else None)
        rtext(d, (x + w / 2, 242), label, F(12), (240, 237, 255) if filled else (200, 196, 232), "mm")
        x += w + 8
    return

def draw_popup(d, title, body, sub=None, score=None):
    rr(d, [150, 80, 810, 470], 16, fill=(22, 20, 38), outline=(139, 126, 240), width=2)
    rtext(d, (180, 110), title, F(26, True), (240, 237, 255), "la")
    if sub:
        rtext(d, (180, 148), sub, F(13), (139, 126, 240), "la")
    rtext(d, (180, 178), body, F(17), (214, 210, 238), "la")
    for bx, lab, fill in [(560, "Close", False), (660, "Edit", True), (740, "Send", False)]:
        rr(d, [bx, 410, bx + 74, 444], 8, fill=(139, 126, 240) if fill else (34, 32, 54))
        rtext(d, (bx + 37, 427), lab, F(15, True), DARK if fill else (230, 226, 250), "mm")

# ---------------------------------------------------------------- video 1: AI polish demo (10s)
def vid1():
    frames = []
    prompt = "lets make a game about a dog"
    polished = ("I want to build a playable game about a dog. Let's plan it "
                "together: pick the genre (adventure, idle, clicker), the look "
                "(2D under the name), and a small first version I can ship in a day.")
    # S1 0-3s: typewriter
    for k in range(int(3 * FPS)):
        n = int(len(prompt) * k / (3 * FPS))
        im = base(); d = ImageDraw.Draw(im)
        rtext(d, (40, 40), "BetterPrompt — AI polish demo", F(18, True), (139, 126, 240))
        draw_bar(d, prompt[:n], 55, 7, "let the model tighten it")
        frames.append(im)
    fade_to_black(frames)
    # S2 3-5.2s: clicking polish
    for k in range(int(2.2 * FPS)):
        im = base(); d = ImageDraw.Draw(im)
        draw_bar(d, prompt, 55, 7, "✨ polishing…")
        frames.append(im)
    fade_to_black(frames)
    # S3 5.2-8.2s: popup with polished prompt, Edit primary
    for k in range(int(3 * FPS)):
        im = base(); d = ImageDraw.Draw(im)
        rtext(d, (40, 40), "BetterPrompt — AI polish demo", F(18, True), (139, 126, 240))
        draw_popup(d, "✨ AI polish", "\n".join(textwrap.wrap(polished, 56)),
                   sub="same ask, cleaned up", score=88)
        frames.append(im)
    fade_to_black(frames)
    # S4 8.2-10s: end card
    for k in range(int(1.8 * FPS)):
        im = base(); d = ImageDraw.Draw(im)
        rtext(d, (480, 210), "BetterPrompt", F(52, True), (240, 237, 255), "mm")
        rtext(d, (480, 275), "pre-audit your prompt before you send it", F(22), (160, 156, 195), "mm")
        rtext(d, (480, 330), "hermes plugins install shovexxx/Betterhermesprompt", F(16), (139, 126, 240), "mm")
        frames.append(im)
    return frames

# ---------------------------------------------------------------- video 2: CLI demo (10s)
def real_cli_out():
    r = subprocess.run([sys.executable, "cli.py", "lets make a game about a dog"],
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)) + "/..")
    return r.stdout.replace("\x1b[", "\nXX")  # naive ansi strip fallback below
def ansi_strip(s):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

def vid2():
    text = ansi_strip(subprocess.run([sys.executable, "cli.py", "lets make a game about a dog"],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)) + "/..").stdout)
    lines = [l for l in text.splitlines() if l.strip()]
    cmd = 'python3 cli.py "lets make a game about a dog"'
    frames = []
    # 0-2.6s typing
    for k in range(int(2.6 * FPS)):
        n = int(len(cmd) * k / (2.6 * FPS))
        im = base()
        d = ImageDraw.Draw(im)
        rr(d, [30, 60, 930, 500], 10, fill=(15, 14, 26), outline=(60, 55, 90), width=1)
        rr(d, [30, 60, 930, 92], 10, fill=(22, 20, 36))
        rtext(d, (54, 76), "shovex · BetterPrompt CLI demo", F(14), (150, 148, 180), "lm")
        rtext(d, (54, 130), "$ " + cmd[:n] + "▋", M(21), (125, 245, 176), "la")
        frames.append(im)
    fade_to_black(frames)
    # 2.6-9s reveal output
    for k in range(int(6.4 * FPS)):
        vis = 1 + int(len(lines) * k / (6.4 * FPS))
        im = base(); d = ImageDraw.Draw(im)
        rr(d, [30, 60, 930, 500], 10, fill=(15, 14, 26), outline=(60, 55, 90), width=1)
        rr(d, [30, 60, 930, 92], 10, fill=(22, 20, 36))
        rtext(d, (54, 76), "shovex · BetterPrompt CLI demo", F(14), (150, 148, 180), "lm")
        y = 120
        d.text((54, y), "$ " + cmd, font=M(18), fill=(125, 245, 176))
        y += 34
        for ln in lines[:vis]:
            d.text((54, y), ln[:58], font=M(16), fill=(206, 202, 232))
            y += 25
        frames.append(im)
    fade_to_black(frames)
    # 9-10s end card
    for k in range(int(1.0 * FPS)):
        im = base(); d = ImageDraw.Draw(im)
        rtext(d, (480, 240), "CLI · zero tokens", F(40, True), (240, 237, 255), "mm")
        rtext(d, (480, 290), "python3 cli.py \"<your prompt>\"", M(18), (125, 245, 176), "mm")
        frames.append(im)
    return frames

# ---------------------------------------------------------------- video 3: cartoon (15s)
def house(d):
    d.rectangle([60, 260, 300, 460], fill=(200, 120, 90), outline=(60, 40, 30), width=3)
    d.polygon([(40, 260), (180, 150), (320, 260)], outline=(60, 40, 30), fill=(150, 60, 60), width=3)
    d.rectangle([150, 350, 205, 460], fill=(120, 80, 50), outline=(60, 40, 30), width=3)
    d.rectangle([90, 300, 125, 340], fill=(180, 200, 230), outline=(60, 40, 30), width=2)
    d.rectangle([245, 300, 280, 340], fill=(180, 200, 230), outline=(60, 40, 30), width=2)

def mailbox(d, x, flag=True):
    d.line([(x, 450), (x, 330)], fill=(80, 70, 110), width=6)
    d.polygon([(x - 42, 330), (x + 42, 330), (x + 34, 300), (x - 34, 300)], outline=(60, 100, 60), fill=(70, 130, 70), width=3)
    if flag:
        d.polygon([(x + 34, 302), (x + 62, 296), (x + 34, 310)], fill=(220, 80, 70))

def dad(d, x, y, angry=False, shocked=False):
    d.ellipse([x - 26, y - 70, x + 26, y - 18], fill=(240, 190, 150), outline=(60, 40, 30), width=3)  # head
    d.ellipse([x - 30, y - 52, x + 30, y - 38], fill=(60, 60, 90), outline=(40, 40, 60), width=2)      # hat brim
    d.rectangle([x - 18, y - 78, x + 18, y - 54], fill=(60, 60, 90))                                   # hat top
    d.rectangle([x - 22, y - 16, x + 22, y + 60], fill=(70, 90, 150), outline=(50, 60, 100), width=3)  # body
    d.line([(x, y + 60), (x, y + 110)], fill=(50, 50, 80), width=6)                                    # legs
    d.line([(x - 12, y + 30), (x - 30, y + 60)], fill=(60, 60, 90), width=5)                           # arm
    if angry:
        d.line([(x - 12, y - 48), (x - 2, y - 42)], fill=(40, 30, 30), width=3)
        d.line([(x + 12, y - 48), (x + 2, y - 42)], fill=(40, 30, 30), width=3)
        d.polygon([(x - 8, y - 34), (x + 8, y - 34), (x, y - 20)], fill=(60, 40, 40))
    elif shocked:
        d.ellipse([x - 16, y - 50, x - 6, y - 40], fill=(60, 50, 50))
        d.ellipse([x + 6, y - 50, x + 16, y - 40], fill=(60, 50, 50))
        d.ellipse([x - 10, y - 30, x + 10, y - 12], fill=(60, 40, 40))
    else:
        d.ellipse([x - 16, y - 50, x - 6, y - 40], fill=(40, 30, 30))
        d.ellipse([x + 6, y - 50, x + 16, y - 40], fill=(40, 30, 30))
        d.arc([x - 10, y - 40, x + 10, y - 20], 200, 340, fill=(60, 40, 40), width=3)

def kid(d, x, y, panic=False):
    d.ellipse([x - 18, y - 50, x + 18, y - 14], fill=(240, 190, 150), outline=(50, 40, 30), width=3)
    d.rectangle([x - 14, y - 12, x + 14, y + 36], fill=(90, 140, 90), outline=(50, 80, 50), width=3)
    d.line([(x - 8, y + 36), (x - 16, y + 66)], fill=(50, 50, 70), width=5)
    d.line([(x + 8, y + 36), (x + 16, y + 66)], fill=(50, 50, 70), width=5)
    if panic:
        d.ellipse([x - 12, y - 36, x - 4, y - 28], fill=(50, 40, 40))
        d.ellipse([x + 4, y - 36, x + 12, y - 28], fill=(50, 40, 40))
        d.ellipse([x - 7, y - 20, x + 7, y - 6], fill=(70, 40, 40))
        d.line([(x - 18, y - 58), (x - 24, y - 70)], fill=(60, 60, 90), width=4)  # arms up
        d.line([(x + 18, y - 58), (x + 24, y - 70)], fill=(60, 60, 90), width=4)
    else:
        d.ellipse([x - 12, y - 36, x - 4, y - 28], fill=(50, 40, 40))
        d.ellipse([x + 4, y - 36, x + 12, y - 28], fill=(50, 40, 40))
        d.line([(x - 6, y - 20), (x + 6, y - 20)], fill=(60, 40, 40), width=3)

def pc_monitor(d, x, y, herm=True):
    d.rectangle([x + 6, y + 58, x + 74, y + 76], fill=(60, 60, 80), outline=(40, 40, 60), width=2)
    rr(d, [x, y, x + 80, y + 56], 6, fill=(18, 17, 30), outline=(120, 120, 150), width=2)
    d.rectangle([x + 6, y + 6, x + 74, y + 12], fill=(30, 28, 48))
    for i in range(3):
        rr(d, [x + 8, y + 18 + i * 12, x + 62, y + 26 + i * 12], 3, fill=(40, 38, 62))
    rr(d, [x + 8, y + 44, x + 40, y + 50], 3, fill=(139, 126, 240))

def vid3():
    frames = []
    # S1 0-3s dad to mailbox + envelope
    for k in range(int(3 * FPS)):
        im = Image.new("RGB", (W, H), SKY)
        d = ImageDraw.Draw(im)
        house(d); mailbox(d, 760)
        d.rectangle([0, 460, W, H], fill=(90, 140, 70), outline=(60, 100, 50), width=0)
        x = 180 + int(400 * k / (3 * FPS))
        dad(d, min(x, 640), 470)
        d.line([(0, 120), (W, 220)], fill=(250, 240, 200), width=2)
        frames.append(im)
    fade_to_black(frames)
    # S2 3-6s envelope → million-dollar internet token bill
    for k in range(int(3 * FPS)):
        im = Image.new("RGB", (W, H), (30, 26, 44))
        d = ImageDraw.Draw(im)
        dad(d, 200, 470, shocked=True)
        rx, ry = 420, 150
        rr(d, [rx, ry, rx + 380, ry + 230], 8, fill=(255, 252, 240), outline=(70, 60, 50), width=3)
        rtext(d, (rx + 190, ry + 40), "INTERNET TOKEN BILL", F(20, True), (200, 40, 40), "mm")
        rtext(d, (rx + 190, ry + 95), "$1,000,000", F(52, True), (40, 40, 60), "mm")
        rtext(d, (rx + 190, ry + 150), "due now · tokens exceeded", F(14), (90, 90, 110), "mm")
        frames.append(im)
    fade_to_black(frames)
    # S3 6-9s dad yells at son
    for k in range(int(3 * FPS)):
        im = Image.new("RGB", (W, H), (222, 214, 190))
        d = ImageDraw.Draw(im)
        dad(d, 260, 460, angry=True)
        rtext(d, (260, 300), "WHAT?!", F(60, True), (200, 40, 40), "mm")
        d.line([(340, 250), (450, 180)], fill=(200, 200, 190), width=8)
        kid(d, 700, 460)
        rr(d, [520, 380, 880, 460], 6, fill=(150, 140, 120), outline=(90, 80, 60), width=3)
        frames.append(im)
    fade_to_black(frames)
    # S4 9-13s zoom to kid at Hermes Desktop in panic
    for k in range(int(4 * FPS)):
        im = Image.new("RGB", (W, H), (36, 32, 52))
        d = ImageDraw.Draw(im)
        # desk + hermes screen filling frame
        rr(d, [120, 250, 840, 350], 6, fill=(90, 80, 70), outline=(60, 55, 45), width=3)
        pc_monitor(d, 320, 170)  # small monitor version
        rr(d, [430, 160, 730, 400], 10, fill=(18, 17, 30), outline=(139, 126, 240), width=3)
        rtext(d, (580, 180), "◆ Hermes Desktop", F(18, True), (139, 126, 240), "mm")
        for i in range(4):
            rr(d, [460, 210 + i * 34, 700 if i % 2 else 640, 234 + i * 34], 4, fill=(40, 38, 62))
        rr(d, [460, 360, 700, 392], 6, fill=(26, 24, 42), outline=(90, 86, 120), width=1)
        rtext(d, (580, 376), "BetterPrompt bar ►", F(12), (125, 245, 176), "mm")
        kid(d, 200, 470, panic=True)
        d.line([(250, 360), (330, 300)], fill=(60, 60, 90), width=5)
        rtext(d, (200, 240), "!!", F(60, True), (220, 200, 60), "mm")
        frames.append(im)
    fade_to_black(frames)
    # S5 13-15s speech bubble
    for k in range(int(2 * FPS)):
        im = Image.new("RGB", (W, H), (36, 32, 52))
        d = ImageDraw.Draw(im)
        rr(d, [120, 250, 840, 350], 6, fill=(90, 80, 70), outline=(60, 55, 45), width=3)
        pc_monitor(d, 320, 170)
        rr(d, [430, 160, 730, 400], 10, fill=(18, 17, 30), outline=(139, 126, 240), width=3)
        kid(d, 200, 470, panic=True)
        # big speech bubble
        rr(d, [180, 120, 780, 330], 26, fill=(255, 255, 250), outline=(40, 40, 60), width=4)
        d.polygon([(300, 330), (340, 330), (290, 380)], fill=(255, 255, 250), outline=(40, 40, 60))
        rtext(d, (480, 225), "IT'S PORN DAD I SWEAR!", F(42, True), (200, 40, 60), "mm")
        frames.append(im)
    return frames

def encode(frames, path, num):
    out = f"/tmp/vid{num}/%05d.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    for i, f in enumerate(frames):
        f.convert("RGB").save(out % i)
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", out, "-frames:v", "999999",
                    "-c:v", "libx264rgb", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", path],
                   capture_output=True, text=True)
    print("encoded", path, len(frames), "frames")

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir + "/..")  # so cli.py path works
    if which in ("all", "1"):
        encode(vid1(), f"{base_dir}/demo-ai-polish.mp4", 1)
    if which in ("all", "2"):
        encode(vid2(), f"{base_dir}/demo-cli.mp4", 2)
    if which in ("all", "3"):
        encode(vid3(), f"{base_dir}/dad-internet-bill.mp4", 3)
        subprocess.run(["ffmpeg", "-y", "-i", f"{base_dir}/dad-internet-bill.mp4",
                        "-i", "/tmp/panic.mp3",
                        "-filter_complex", "[1:a]adelay=13000|13000[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest",
                        f"{base_dir}/dad-internet-bill-audio.mp4"], capture_output=True, text=True)
        print("muxed audio")
