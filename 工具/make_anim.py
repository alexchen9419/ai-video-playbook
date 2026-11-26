"""make_anim.py <project.json> [段落id ...]

把 project.json 裡 type 為 "anim" 的段落做成影片：
  1. 依每句旁白 WAV 的長度排出時間點（cues）：lead 秒後說第一句，句間隔 gap 秒，最後留 tail 秒。
  2. 用 Playwright 開動畫 HTML（?scene=<id>&cues=<json>），逐格呼叫 setT(t) 截圖（renderer 為 "html"），
     或執行自訂指令（renderer 為 "command"，見手冊 03_後製.md）。
  3. 把旁白依 cues 混進去，輸出 <build_dir>/<id>.mp4 與 <id>.cues.json。

環境變數 PREVIEW=1,4.5,10 → 只輸出這幾個秒數的截圖到 <build_dir>/prev_<id>_<t>.png，不產生影片（先看構圖用）。
"""
import os, sys, json, wave, shutil, subprocess, pathlib, urllib.parse
import imageio_ffmpeg
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 中文主控台（cp950）也能印

P = pathlib.Path(sys.argv[1]).resolve(); ROOT = P.parent
cfg = json.load(open(P, encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS = cfg.get("fps", 24); W, H = cfg.get("size", [1280, 720])
BUILD = ROOT / cfg.get("build_dir", "build"); BUILD.mkdir(exist_ok=True)
only = set(sys.argv[2:])
PREVIEW = os.environ.get("PREVIEW")


def wav_dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def timing(seg):
    lead, gap, tail = seg.get("lead", 0.8), seg.get("gap", 0.5), seg.get("tail", 1.0)
    t, cues = lead, []
    for ln in seg["lines"]:
        d = wav_dur(ROOT / ln["wav"]); cues.append([round(t, 3), round(t + d, 3)]); t += d + gap
    return cues, round(t - gap + tail, 3)


def launch(p):
    chans = [cfg.get("browser_channel"), None, "chrome", "msedge"]
    err = None
    for ch in dict.fromkeys(chans):
        try:
            kw = {"args": ["--allow-file-access-from-files"]}
            if ch: kw["channel"] = ch
            return p.chromium.launch(**kw)
        except Exception as e:  # 沒裝這個瀏覽器就試下一個
            err = e
    raise SystemExit(f"找不到可用的 Chromium：{err}\n請執行 python -m playwright install chromium")


def render_html(seg, cues, total, out):
    from playwright.sync_api import sync_playwright
    html = ROOT / seg.get("html", cfg.get("anim_html", "動畫/anim.html"))
    scene = seg.get("scene", seg["id"])
    url = html.as_uri() + "?" + urllib.parse.urlencode({"scene": scene, "cues": json.dumps(cues)})
    with sync_playwright() as p:
        b = launch(p)
        # 暖機：第一個 context 偶爾畫不出字型
        b.new_page().close()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(url); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(400)
        if PREVIEW:
            for s in PREVIEW.split(","):
                pg.evaluate(f"setT({float(s)})")
                pg.screenshot(path=str(BUILD / f"prev_{seg['id']}_{s}.png"))
            b.close(); return False
        fd = BUILD / f"frames_{seg['id']}"
        shutil.rmtree(fd, ignore_errors=True); fd.mkdir()
        for i in range(int(round(total * FPS))):
            pg.evaluate(f"setT({i / FPS})")
            pg.screenshot(path=str(fd / f"{i:05d}.png"))
        b.close()
    subprocess.run([FF, "-y", "-v", "error", "-framerate", str(FPS), "-i", str(fd / "%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)], check=True)
    shutil.rmtree(fd)
    return True


def render_command(seg, cues, total, out):
    cmd = seg["command"].format(dur=total, cues_json=json.dumps(cues).replace('"', '\\"'), out=str(out))
    subprocess.run(cmd, shell=True, cwd=ROOT, check=True)
    return True


def mux(video, seg, cues, total, out):
    cmd = [FF, "-y", "-v", "error", "-i", str(video)]; fl = []
    for k, ln in enumerate(seg["lines"]):
        cmd += ["-i", str(ROOT / ln["wav"])]; ms = int(cues[k][0] * 1000)
        fl.append(f"[{k+1}:a]aresample=48000,adelay={ms}|{ms}[v{k}]")
    n = len(seg["lines"])
    fl.append("".join(f"[v{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0,apad[a]")
    fl.append(f"[0:v]scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(fl), "-map", "[v]", "-map", "[a]", "-t", str(total),
            "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)


for seg in cfg["segments"]:
    if seg.get("type") != "anim" or (only and seg["id"] not in only):
        continue
    cues, total = timing(seg)
    silent = BUILD / f"{seg['id']}_silent.mp4"
    r = seg.get("renderer", "html")
    ok = render_html(seg, cues, total, silent) if r == "html" else render_command(seg, cues, total, silent)
    if not ok:
        print("preview", seg["id"]); continue
    mux(silent, seg, cues, total, BUILD / f"{seg['id']}.mp4")
    silent.unlink()
    json.dump({"cues": cues, "dur": total}, open(BUILD / f"{seg['id']}.cues.json", "w"), indent=1)
    print(seg["id"], total, cues)
