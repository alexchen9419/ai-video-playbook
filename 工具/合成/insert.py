"""Full-screen phone insert: insert.py <recdir> <t_start> <t_end> <bg.jpg> <out.mp4> [speed]
Phone mock (rounded bezel) centred over a blurred, darkened background frame. 1920x1080, 24 fps."""
import sys, json, subprocess, cv2, numpy as np, imageio_ffmpeg
rec, ts, te, bgp, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]
speed = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0
FPS, W, H = 24, 1920, 1080
idx = json.load(open(rec + '/frames.json'))

bg = cv2.imdecode(np.fromfile(bgp, np.uint8), cv2.IMREAD_COLOR)
bg = cv2.resize(bg, (W, H))
bg = cv2.GaussianBlur(bg, (0, 0), 18)
bg = (bg * 0.45).astype(np.uint8)

SH = 900                      # screen height on canvas
SW = round(SH * 390 / 844)    # 416
BZ = 16                       # bezel
PW, PH = SW + 2 * BZ, SH + 2 * BZ
px, py = (W - PW) // 2, (H - PH) // 2

def rr_mask(w, h, r):
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m

body = rr_mask(PW, PH, 62).astype(np.float32)[..., None] / 255
scr = rr_mask(SW, SH, 48).astype(np.float32)[..., None] / 255
# soft shadow
shadow = np.zeros((H, W), np.float32)
shadow[py + 20:py + PH + 20, px:px + PW] = body[..., 0]
shadow = cv2.GaussianBlur(shadow, (0, 0), 30)[..., None] * 0.7
base = (bg * (1 - shadow)).astype(np.float32)
roi = base[py:py + PH, px:px + PW]
base[py:py + PH, px:px + PW] = roi * (1 - body) + np.array([18, 18, 22], np.float32) * body

cache = {}
def screen_at(t):
    fn = idx[0][1]
    for tt, f in idx:
        if tt <= t: fn = f
        else: break
    if fn not in cache:
        im = cv2.imread(fn)
        cache.clear(); cache[fn] = cv2.resize(im, (SW, SH), interpolation=cv2.INTER_AREA).astype(np.float32)
    return cache[fn]

ff = imageio_ffmpeg.get_ffmpeg_exe()
p = subprocess.Popen([ff, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                      '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
n = int((te - ts) / speed * FPS)
for i in range(n):
    s = screen_at(ts + i / FPS * speed)
    fr = base.copy()
    sx, sy = px + BZ, py + BZ
    r = fr[sy:sy + SH, sx:sx + SW]
    fr[sy:sy + SH, sx:sx + SW] = r * (1 - scr) + s * scr
    p.stdin.write(fr.astype(np.uint8).tobytes())
p.stdin.close(); p.wait()
print('ok', n, 'frames', round(n / FPS, 2), 's')
