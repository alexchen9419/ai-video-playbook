"""Planar-track a glowing phone screen and pin a screen recording onto it.
track2.py <in.mp4> <recdir> <t_start> <speed> <out.mp4> "x,y;..." (rough corners TL,TR,BR,BL in frame 0)

1. Frame 0: exact corners from 4 straight screen edges (line fits, rounded corners and fingers ignored).
2. Every frame: ECC homography from frame 0 to the current frame on a ring around the screen edge
   (bezel + border), started from the previous frame's result -> no drift, no smoothing lag.
3. Composite with rounded screen corners; non-glowing pixels inside the screen (fingers) stay on top."""
import sys, json, subprocess, cv2, numpy as np, imageio_ffmpeg

def bright_mask(fr):
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 2] > 165) & (hsv[..., 1] < 75)).astype(np.uint8) * 255

def line_from(p, q):
    a = np.cross(np.append(p, 1), np.append(q, 1)); return a / np.linalg.norm(a[:2])

def fit_corners(fr, rough, trust_rough=False):
    """trust_rough: rough is an accurate prediction; a side whose fit strays from it (dim/blurred/occluded edge)
    keeps the predicted line instead."""
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    roi = np.zeros(fr.shape[:2], np.uint8); cv2.fillConvexPoly(roi, rough.astype(np.int32), 255)
    roi = cv2.dilate(roi, np.ones((41, 41), np.uint8))
    thr, _ = cv2.threshold(hsv[..., 2][roi > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)   # adaptive glow threshold
    m = ((hsv[..., 2] > thr) & (hsv[..., 1] < 80)).astype(np.uint8) * 255
    diag = np.linalg.norm(rough[0] - rough[2])
    m = cv2.morphologyEx(cv2.bitwise_and(m, roi), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    lines = []
    for k in range(4):
        a, b = rough[k], rough[(k + 1) % 4]
        L = line_from(a, b)
        d = pts @ L[:2] + L[2]
        t = (pts - a) @ (b - a) / np.dot(b - a, b - a)
        sel = pts[(np.abs(d) < 0.09 * diag) & (t > 0.15) & (t < 0.85)]
        Lp = L
        if len(sel) < 10:
            if trust_rough: lines.append(Lp); continue
            raise RuntimeError(f'side {k}: screen edge not found - check the rough corners')
        for _ in range(4):                       # iterative trimmed fit (drops finger notches)
            vx, vy, x0, y0 = cv2.fitLine(sel.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
            L = line_from(np.array([x0, y0]), np.array([x0 + vx, y0 + vy]))
            r = np.abs(sel @ L[:2] + L[2])
            keep = r < max(1.5, np.percentile(r, 70))
            if keep.sum() < 10: break
            sel = sel[keep]
        if trust_rough:
            seglen = np.linalg.norm(b - a)
            dev = max(abs(a @ L[:2] + L[2]), abs(b @ L[:2] + L[2]))        # fitted line vs predicted endpoints
            if dev > max(2.5, 0.03 * seglen) or len(sel) < 0.35 * seglen:
                L = Lp
        lines.append(L)
    c = []
    for k in range(4):                           # corner k = side k-1 x side k
        X = np.cross(lines[k - 1], lines[k]); c.append(X[:2] / X[2])
    return np.array(c, np.float32)

def detect_quad(fr, pred, rng=np.random.default_rng(0)):
    """Absolute per-frame detection of the glowing screen: RANSAC one straight line per side near the
    predicted quad (finger notches / rounded corners are minority points), intersect the 4 lines.
    Returns (quad, n_sides_found)."""
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    diag = np.linalg.norm(pred[0] - pred[2])
    roi = np.zeros(fr.shape[:2], np.uint8); cv2.fillConvexPoly(roi, pred.astype(np.int32), 255)
    k = int(0.3 * diag) | 1
    roi = cv2.dilate(roi, np.ones((k, k), np.uint8))
    thr, _ = cv2.threshold(hsv[..., 2][roi > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = ((hsv[..., 2] > thr) & (hsv[..., 1] < 80) & (roi > 0)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs: return pred, 0
    pts = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    lines, found = [], 0
    for s in range(4):
        a, b = pred[s].astype(np.float64), pred[(s + 1) % 4].astype(np.float64)
        Lp = line_from(a, b); seglen = np.linalg.norm(b - a)
        d = pts @ Lp[:2] + Lp[2]; t = (pts - a) @ (b - a) / np.dot(b - a, b - a)
        cand = pts[(np.abs(d) < 0.12 * diag) & (t > 0.08) & (t < 0.92)]
        best, bestL = None, Lp
        if len(cand) >= 10:
            dp = (b - a) / seglen
            for _ in range(150):
                i, j = rng.choice(len(cand), 2, replace=False)
                v = cand[j] - cand[i]; nv = np.linalg.norm(v)
                if nv < 0.15 * seglen or abs(v @ dp) / nv < 0.985: continue      # within ~10 deg of predicted side
                L = line_from(cand[i], cand[j])
                inl = np.abs(cand @ L[:2] + L[2]) < 1.5
                if best is None or inl.sum() > best.sum(): best = inl
        if best is not None and best.sum() >= 0.3 * seglen:
            vx, vy, x0, y0 = cv2.fitLine(cand[best].astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
            bestL = line_from(np.array([x0, y0]), np.array([x0 + vx, y0 + vy])); found += 1
        lines.append(bestL)
    c = []
    for s in range(4):
        X = np.cross(lines[s - 1], lines[s]); c.append(X[:2] / X[2])
    return np.array(c, np.float32), found

if __name__ == '__main__':
    inp, rec, ts, speed, out, q0 = sys.argv[1:7]
    ts, speed = float(ts), float(speed)
    rough = np.array([[float(v) for v in p.split(',')] for p in q0.split(';')], np.float64)
    idx = json.load(open(rec + '/frames.json'))
    cap = cv2.VideoCapture(inp)
    FPS = cap.get(cv2.CAP_PROP_FPS) or 24
    W, H = int(cap.get(3)), int(cap.get(4))
    SW, SH = 780, 1688
    src = np.array([[0, 0], [SW, 0], [SW, SH], [0, SH]], np.float32)
    # rounded-corner alpha in screen space
    R = int(SW * 0.07)
    salpha = np.zeros((SH, SW), np.uint8)
    cv2.rectangle(salpha, (R, 0), (SW - R, SH), 255, -1); cv2.rectangle(salpha, (0, R), (SW, SH - R), 255, -1)
    for cx, cy in ((R, R), (SW - R, R), (R, SH - R), (SW - R, SH - R)):
        cv2.circle(salpha, (cx, cy), R, 255, -1, cv2.LINE_AA)

    def screen_at(t):
        fn = idx[0][1]
        for tt, f in idx:
            if tt <= t: fn = f
            else: break
        return fn
    cache = {}
    def load(fn):
        if fn not in cache:
            cache.clear(); cache[fn] = cv2.resize(cv2.imread(fn), (SW, SH), interpolation=cv2.INTER_AREA)
        return cache[fn]

    ok, f0 = cap.read()
    c0 = fit_corners(f0, rough)
    import os; RD, RE, SNAP = int(os.environ.get('RD', 31)), int(os.environ.get('RE', 15)), os.environ.get('SNAP', '1') == '1'; LKD = int(os.environ.get('LKD', 81)); DET = os.environ.get('DET', '1') == '1'; qprev = None
    S = 0.5                                       # ECC on half resolution
    g0 = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(f0, None, fx=S, fy=S, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY), (0, 0), 1.0)
    ring = np.zeros_like(g0)
    cv2.fillConvexPoly(ring, (c0 * S).astype(np.int32), 255)
    ring = cv2.subtract(cv2.dilate(ring, np.ones((RD, RD), np.uint8)), cv2.erode(ring, np.ones((RE, RE), np.uint8)))
    Sm = np.diag([S, S, 1.0]); Si = np.linalg.inv(Sm)
    Wm = np.eye(3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    p = subprocess.Popen([ff, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
    log, fails, i, fr, snaps = [], 0, 0, f0, 0
    Hf = np.eye(3)                                # frame0 -> current, full res
    quad = c0.copy()
    gprev = cv2.cvtColor(f0, cv2.COLOR_BGR2GRAY)
    lk = dict(winSize=(41, 41), maxLevel=5, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01))
    D = np.diag([0.5, 0.5, 1.0]); Di = np.linalg.inv(D)
    def qerr(Ha, Hb):
        return np.abs(cv2.perspectiveTransform(c0[None].astype(np.float64), Ha) - cv2.perspectiveTransform(c0[None].astype(np.float64), Hb)).max()
    while True:
        if i > 0:
            ok, fr = cap.read()
            if not ok: break
            gfull = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            if DET:
              # detection mode: constant-velocity prediction + absolute edge detection every frame
              pred = quad + (quad - qprev) if qprev is not None else quad
              qd, nf = detect_quad(fr, pred)
              if nf < 4:                            # a side missing: keep found sides, others from prediction
                  fails += 1
              qprev = quad.copy()
              Hf = cv2.getPerspectiveTransform(c0.astype(np.float32), qd.astype(np.float32)).astype(np.float64)
              snaps += nf == 4
            else:
                # 1) predict: LK features around the phone, previous -> current frame
                fm = np.zeros_like(gfull); cv2.fillConvexPoly(fm, quad.astype(np.int32), 255)
                fm = cv2.dilate(fm, np.ones((LKD, LKD), np.uint8))
                p0 = cv2.goodFeaturesToTrack(gprev, 400, 0.005, 5, mask=fm)
                Hpred = Hf
                if p0 is not None and len(p0) >= 8:
                    p1, st, _ = cv2.calcOpticalFlowPyrLK(gprev, gfull, p0, None, **lk)
                    b0, b1 = p0[st[:, 0] == 1], p1[st[:, 0] == 1]
                    if len(b0) >= 8:
                        Hd, _ = cv2.findHomography(b0, b1, cv2.RANSAC, 2.0)
                        if Hd is not None: Hpred = Hd @ Hf
                # 2) refine: ECC frame0 -> current (coarse-to-fine), started from the prediction
                g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(fr, None, fx=S, fy=S, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY), (0, 0), 1.0)
                Hnew = Hpred
                try:
                    Wc = D @ (Sm @ Hpred @ Si) @ Di
                    _, Wc = cv2.findTransformECC(cv2.pyrDown(g0), cv2.pyrDown(g), (Wc / Wc[2, 2]).astype(np.float32), cv2.MOTION_HOMOGRAPHY, crit, cv2.pyrDown(ring), 3)
                    _, Wn = cv2.findTransformECC(g0, g, (Di @ Wc @ D).astype(np.float32), cv2.MOTION_HOMOGRAPHY, crit, ring, 5)
                    Hecc = Si @ Wn.astype(np.float64) @ Sm
                    if qerr(Hecc, Hpred) < 0.25 * np.linalg.norm(c0[1] - c0[0]): Hnew = Hecc   # reject runaway ECC
                    else: fails += 1
                except cv2.error:
                    fails += 1
                # 3) snap: re-fit the 4 glowing screen edges around the prediction (absolute, no drift)
                qp = cv2.perspectiveTransform(c0[None].astype(np.float64), Hnew)[0]
                if SNAP:
                  try:
                    qf = fit_corners(fr, qp, trust_rough=True).astype(np.float64)
                    if np.abs(qf - qp).max() < 0.15 * np.linalg.norm(qp[1] - qp[0]):
                        Hnew = cv2.getPerspectiveTransform(c0.astype(np.float32), qf.astype(np.float32)).astype(np.float64)
                        snaps += 1
                  except Exception:
                    pass
                Hf, gprev = Hnew, gfull
        quad = cv2.perspectiveTransform(c0[None].astype(np.float64), Hf)[0].astype(np.float32)
        log.append(quad.tolist())
        scr = load(screen_at(ts + i / FPS * speed))
        cen = quad.mean(0); big = (cen + (quad - cen) * 1.015).astype(np.float32)
        Hs = cv2.getPerspectiveTransform(src, big)
        warped = cv2.warpPerspective(scr, Hs, (W, H), flags=cv2.INTER_AREA)
        a = cv2.warpPerspective(salpha, Hs, (W, H))
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        finger = (~((hsv[..., 2] > 140) & (hsv[..., 1] < 85))).astype(np.uint8) * 255
        finger = cv2.morphologyEx(finger, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        inner = np.zeros((H, W), np.uint8)       # only treat as finger well inside the screen
        cv2.fillConvexPoly(inner, (cen + (quad - cen) * 0.975).astype(np.int32), 255)
        a = cv2.subtract(a, cv2.bitwise_and(finger, inner))
        a = cv2.GaussianBlur(a, (3, 3), 0).astype(np.float32)[..., None] / 255
        p.stdin.write((fr * (1 - a) + warped * a).astype(np.uint8).tobytes())
        i += 1
    p.stdin.close(); p.wait()
    json.dump(log, open(out + '.corners.json', 'w'))
    print('ok frames', i, 'ecc fails', fails, 'edge snaps', snaps, 'c0', c0.round(1).tolist())









