#!/usr/bin/env python3
"""Render the BetterPrompt demo video frames (1200x675 @30fps) with PIL,
then encode with ffmpeg. Uses the REAL CLI output from /tmp/cli_*.txt."""
import os, sys, glob
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
FPS = 30
OUT = "/tmp/bp_frames"
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(OUT + "/*.png"):
    os.remove(f)

BG = (11, 10, 18)
MONO = "/usr/share/fonts/google-noto/NotoSansMono-CondensedMedium.ttf"
MONOL = "/usr/share/fonts/google-noto/NotoSansMono-SemiCondensedLight.ttf"
SANS = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
SANSB = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf"

def reg(font): return ImageFont.truetype(font, 22)
def F(size, bold=True):
    p = SANSB if bold else SANS
    return ImageFont.truetype(p, size)

# reusable monospace fonts
MONO_28 = ImageFont.truetype(MONO, 27)
MONO_30 = ImageFont.truetype(MONO, 30)

SEV_COLOR = {"HIGH": (240, 160, 80), "high": (240, 160, 80), "mid": (200, 195, 235),
             "medium": (200, 195, 235), "low": (140, 155, 200), "ok": (125, 245, 176)}

def draw_terminal(base, lines, visible, height=H):
    """Draw a terminal window with `lines` (list of colored-line tuples or strs),
    revealing up to index `visible`. Returns a frame Image."""
    img = base.copy()
    d = ImageDraw.Draw(img)
    # window chrome
    pad = 44
    top = 54
    # title bar
    d.rectangle([pad-22, top-46, W-pad+22, top-14], fill=(18,17,30))
    d.ellipse([pad-14, top-38, pad+2, top-22], fill=(255,110,110))
    d.ellipse([pad+8, top-38, pad+24, top-22], fill=(255,200,90))
    d.ellipse([pad+30, top-38, pad+46, top-22], fill=(110,230,140))
    d.text((W- pad-22 - 260, top-38), "shovex — BetterPrompt (python3 cli.py)", font=F(20, False), fill=(150,150,190))
    # body
    body = Image.new("RGBA", (W, H), (13,12,22,255))
    db = ImageDraw.Draw(body)
    y = top + 8
    for i, ln in enumerate(lines[:visible]):
        if isinstance(ln, tuple):
            txt, color = ln
        else:
            txt, color = ln, (230,228,248)
        x = pad
        if visible is not None and i < visible:
            db.text((x, y), txt, font=MONO_30, fill=color)
        y += 36
    # cursor blink on the current typing line
    if visible is not None and visible < len(lines):
        last = lines[visible]
        t = last[0] if isinstance(last, tuple) else last
        db.text((pad + 14 + 27*0 + 0, top + 8 + 36*visible), "", font=MONO_30)
    img.paste(body, (0, 0), body)
    return img

def slide(title, subtitle=None, accent="#8b7ef0", small=None, sub2=None):
    img = Image.new("RGBA", (W, H), (11,10,18,255))
    d = ImageDraw.Draw(img)
    d.text((70, 150), title, font=F(64, True), fill=(238,236,255))
    if subtitle:
        d.text((70, 270), subtitle, font=F(30, False), fill=(207,201,232))
    if small:
        y = 380
        for s in small:
            d.text((70, y), "•  " + s, font=F(26, False), fill=(190,186,220))
            y += 58
    if sub2:
        d.text((70, 540), sub2, font=F(24, False), fill=(140,150,190))
    return img

def features():
    img = Image.new("RGBA", (W,H), (11,10,18,255)); d = ImageDraw.Draw(img)
    d.text((70,110),"One prompt bar. Five ways to fix it.",font=F(48,True),fill=(238,236,255))
    rows=[("Desktop","second prompt bar · live score · toggle · send-through"),
          ("CLI","hermes prompt-audit / python cli.py — --rewrite --json --models"),
          ("Slash","/bhp-audit (free) · /bhp-rewrite (AI polish on your model)"),
          ("Tools + skill","audit_prompt · improve_prompt · pre-audit before long jobs"),
          ("TUI","/auditprompt widget in the dock")]
    y=220
    for t,s in rows:
        d.text((70,y),t,font=F(30,True),fill=(139,126,240))
        d.text((270,y),s,font=F(25,False),fill=(200,196,232))
        y+=62
    d.text((70,y+8),"100% local · zero-token core · no telemetry",font=F(24,False),fill=(125,245,176))
    return img

# ---- load assets
promo = Image.open("betterprompt-promo.png").convert("RGB")
before = Image.open("bar-before.png").convert("RGB")
after = Image.open("bar-after.png").convert("RGB")
black = Image.new("RGB", (W,H), BG)

# ---- real CLI text (rewrap to ~46 cols)
def wrap(lines, col=46):
    out=[]
    for ln in lines:
        while len(ln)>col:
            out.append(ln[:col]); ln=ln[col:]
        out.append(ln)
    return out

bad = open("/tmp/cli_bad.txt").read().rstrip("\n").split("\n")
bad = wrap(bad)
rewrite = open("/tmp/cli_rewrite.txt").read().rstrip("\n").split("\n")
rewrite_tail = rewrite[-6:]
# only typing + embedded command output; keep it compact for video

def typed_cmd(cmd):
    # simulate typed command: returns generator of prefix frames handled in seq
    return cmd

CMDP1 = ['$ python3 -m cli "fix teh website please please, delete the old stuff but keep it, make it better and stuff"']
CMDP2 = ['$ python3 -m cli --rewrite "fix teh website please please, delete the old stuff but keep it, make it better and stuff"']

# ---- scene builders (return list of frames)
def scene_promo():
    N=int(4*FPS); base=promo.copy(); imgs=[]
    for k in range(N):
        f=k/N
        if k<FPS:  # fade in
            a=min(1.0,(FPS-k)/FPS if k<12 else 1.0)
        else:
            a=1.0
        imgs.append(base.copy())
    return imgs

def scene_problem():
    N=int(4.5*FPS)
    t=slide("Your prompt is the most expensive input.",subtitle="Every wasted token is paid again on every reply.",
            sub2="Worse: vague or contradictory prompts make the agent loop — asking, guessing, retrying. You pay for all of it.",
            small=["14 words became: filler + a contradiction + no scope.","The model asked clarifying questions before doing anything.","BetterPrompt stops this BEFORE you hit Send."])
    return [t.copy() for _ in range(N)]

def scene_terminal(lines, type_start=2.2, type_cmd=CMDP1, reveal=9.0):
    """type the command then reveal lines."""
    imgs=[]
    base=black.copy()
    # typing phase
    cmd=(type_cmd[0])
    for k in range(int(type_start*FPS)):
        shown=cmd[:int(len(cmd)* (k/(type_start*FPS)))]
        imgs.append(draw_terminal(base,[shown],visible=1))
    # reveal output progressively
    all_lines=[("","")]+lines
    total=len(lines)
    for k in range(int(reveal*FPS)):
        vis=1+int((total)*(k/(reveal*FPS)))
        render=[cmd] + [(l,None) for l in lines[:vis]]
        imgs.append(draw_terminal(base,render,visible=len(render)))
    # hold
    hold=draw_terminal(base,[cmd]+[(l,None) for l in lines],visible=len(lines)+1)
    for _ in range(int(1.2*FPS)): imgs.append(hold)
    return imgs

def scene_desktop_pair():
    N0=int(5.5*FPS); N1=int(7*FPS)
    fr=[]
    for _ in range(N0): fr.append(before.copy())
    for _ in range(N1): fr.append(after.copy())
    return fr

def scene_features():
    N=int(6*FPS); t=features(); return [t.copy() for _ in range(N)]

def scene_outro():
    N=int(6*FPS)
    t=slide("BetterPrompt", subtitle="0 tokens for the core audit.  Desktop · CLI · TUI · slash.",
            small=["github.com/shovexxx/Betterhermesprompt","@NousResearch · Hermes Agent Plugin Hackathon","hermes plugins install shovexxx/Betterhermesprompt"])
    t2=slide("Thanks — go sharpen your prompts.",subtitle="",small=["#NoMistakes","pre-audit before you send it"])
    t2=t2 if N%2 else t
    frames=[]
    for k in range(N): frames.append((t if k<int(N*0.6) else t2).copy())
    return frames

def crossfade(a, b, frames=18):
    out=[]
    ai = a[-1].convert("RGB") if isinstance(a, list) else a.convert("RGB")
    bi = b[0].convert("RGB") if isinstance(b, list) else b.convert("RGB")
    for k in range(frames):
        t=k/(frames-1)
        out.append(Image.blend(ai, bi, t))
    return out

seq=[]
def add(scenes, xf=18):
    global seq
    if seq and scenes:
        a=seq[-1]; b=scenes[0]
        seq+=crossfade([a],[b],xf)
    seq+=scenes

add(scene_promo())
add(scene_problem())
add(scene_terminal(bad[:1]+bad[1:], type_start=2.6, reveal=10.5))  # typing + output
add(scene_terminal(rewrite_tail, type_start=2.4, reveal=7.0))
add(scene_desktop_pair())
add(scene_features())
add(scene_outro())

# write frames
am = None
for i,im in enumerate(seq):
    im.convert("RGB").save(f"{OUT}/{i:05d}.png")
print("frames written:", len(seq))
import shutil, subprocess
enc = subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",f"{OUT}/%05d.png",
    "-vf","format=yuv420p","-c:v","libx264","-crf","20","-movflags","+faststart",
    "demo.mp4"],capture_output=True,text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
print("encode rc", enc.returncode, enc.stderr[-300:] if enc.returncode else "ok")
