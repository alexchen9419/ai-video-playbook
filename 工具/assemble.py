"""assemble.py <project.json>

依 project.json 的 segments 順序組裝全片：
  - type "video"：AI 生成的真人／角色影片（src）。台詞字幕時間由音量自動偵測說話區間；
                   若給 "dub": "語音/xx.wav"，改用該配音取代原音（延遲 dub_delay 秒，預設 0.7）；
                   若給 "speech": [t0, t1]，直接用這個區間排字幕，不偵測。
  - type "anim"： 由 make_anim.py 產生的 <build_dir>/<id>.mp4，字幕依 <id>.cues.json 對到每句旁白。
  - type "clip"： 任何已做好的影片（字卡、片尾、外部動畫）；"lines" 裡每句可給 "at": [t0, t1] 排字幕，
                   沒有 text 的段落就不上字幕。
每段先統一成 size／fps／48 kHz 立體聲，再串接、做響度標準化（loudnorm），最後燒錄字幕。
輸出：<output_dir>/<name>_無字幕.mp4、<name>_字幕.mp4、<name>.srt
"""
import sys, json, re, shutil, subprocess, pathlib
import numpy as np, imageio_ffmpeg
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 中文主控台（cp950）也能印

P = pathlib.Path(sys.argv[1]).resolve(); ROOT = P.parent
cfg = json.load(open(P, encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS = cfg.get("fps", 24); W, H = cfg.get("size", [1280, 720])
BUILD = ROOT / cfg.get("build_dir", "build")
OUT = ROOT / cfg.get("output_dir", "成品"); TMP = OUT / "tmp"
OUT.mkdir(exist_ok=True); TMP.mkdir(exist_ok=True)
NAME = cfg.get("name", "成品")
SUB = {"max_chars": 22, "font_name": "Microsoft JhengHei", "font_file": r"C:\Windows\Fonts\msjhbd.ttc",
       "font_size": 17, "margin_v": 14, **cfg.get("subtitle", {})}
LOUD = cfg.get("loudnorm", "I=-16:TP=-1.5:LRA=11")
NORM = ["-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def run(*a, cwd=None):
    subprocess.run([FF, "-y", "-v", "error", *a], check=True, cwd=cwd)


def probe_dur(p):
    r = subprocess.run([FF, "-i", str(p)], capture_output=True, text=True, errors="ignore").stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def speech_span(p):
    """回傳影片中說話的起訖秒數（帶通 120–4000 Hz、20 ms 視窗、門檻＝第 98 百分位 −20 dB，下限 −42 dB）。"""
    r = subprocess.run([FF, "-v", "quiet", "-i", str(p), "-ac", "1", "-ar", "16000",
                        "-af", "highpass=f=120,lowpass=f=4000", "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768; w = 320
    if len(a) < w * 2: return 0.0, 0.0
    db = 20 * np.log10(np.sqrt(np.array([np.mean(a[k:k + w] ** 2) for k in range(0, len(a) - w, w)])) + 1e-6)
    on = np.where(db > max(np.percentile(db, 98) - 20, -42))[0]
    return (on[0] * 0.02, (on[-1] + 1) * 0.02) if len(on) else (0.0, 0.0)


def chunks(text, t0, t1, maxc):
    """在標點處把一句切成每行 ≤ maxc 字，依字數比例分配時間。"""
    parts = [p for p in re.split(r"(?<=[，。！？：；])", text) if p.strip()]
    lines, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > maxc: lines.append(cur); cur = p
        else: cur += p
    if cur: lines.append(cur)
    n = sum(len(l) for l in lines) or 1; out, t = [], t0
    for l in lines:
        d = (t1 - t0) * len(l) / n; out.append((t, t + d, l.rstrip("，、：；"))); t += d
    return out


def ts(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


segs, subs, t, report = [], [], 0.0, []
for k, s in enumerate(cfg["segments"]):
    tmp = TMP / f"{k:02d}_{s['id']}.mp4"
    typ = s.get("type", "video")
    if typ == "video":
        src = ROOT / s["src"]
        if s.get("dub"):
            ms = int(s.get("dub_delay", 0.7) * 1000)
            run("-i", str(src), "-i", str(ROOT / s["dub"]), "-filter_complex", f"[1:a]aresample=48000,adelay={ms}|{ms},apad[a]",
                "-map", "0:v", "-map", "[a]", *NORM, "-shortest", str(tmp))
        else:
            run("-i", str(src), *NORM, str(tmp))
        d = probe_dur(tmp)
        if s.get("text"):
            a0, a1 = s.get("speech") or speech_span(tmp)
            subs += chunks(s["text"], t + a0, t + a1, SUB["max_chars"])
    else:
        src = BUILD / f"{s['id']}.mp4" if typ == "anim" else ROOT / s["src"]
        has_audio = "Audio:" in subprocess.run([FF, "-i", str(src)], capture_output=True, text=True, errors="ignore").stderr
        if has_audio:
            run("-i", str(src), *NORM, str(tmp))
        else:  # 字卡等無聲片段補靜音，避免串接後音畫不同步
            run("-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a", *NORM, "-shortest", str(tmp))
        d = probe_dur(tmp)
        if typ == "anim":
            cues = json.load(open(BUILD / f"{s['id']}.cues.json"))["cues"]
            spans = [(c, ln) for c, ln in zip(cues, s["lines"])]
        else:
            spans = [(ln["at"], ln) for ln in s.get("lines", []) if "at" in ln]
        for (c0, c1), ln in spans:
            if ln.get("text"): subs += chunks(ln["text"], t + c0, t + c1, SUB["max_chars"])
    segs.append(tmp); report.append((s["id"], round(t, 2), round(d, 2))); t += d
    print(f"{s['id']:>8}  起 {t - d:7.2f}  長 {d:6.2f}")

(TMP / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
srt = "".join(f"{i+1}\n{ts(a)} --> {ts(b)}\n{l}\n\n" for i, (a, b, l) in enumerate(subs))
(OUT / f"{NAME}.srt").write_text(srt, encoding="utf-8")
(OUT / f"{NAME}.segments.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

af = ["-af", f"loudnorm={LOUD}"] if LOUD else []
run("-f", "concat", "-safe", "0", "-i", "tmp/list.txt", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
    *af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", f"{NAME}_無字幕.mp4", cwd=OUT)

# 燒字幕：ffmpeg subtitles 濾鏡吃不了含冒號或中文的絕對路徑，所以在輸出資料夾內用相對檔名，字型放 fonts/
fonts = OUT / "fonts"; fonts.mkdir(exist_ok=True)
ff = pathlib.Path(SUB["font_file"])
if ff.exists() and not (fonts / ff.name).exists(): shutil.copy(ff, fonts / ff.name)
shutil.copy(OUT / f"{NAME}.srt", OUT / "_sub.srt")
style = (f"FontName={SUB['font_name']},FontSize={SUB['font_size']},Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
         f"BackColour=&H80000000,BorderStyle=1,Outline=1.6,Shadow=0.8,MarginV={SUB['margin_v']}")
run("-i", f"{NAME}_無字幕.mp4", "-vf", f"subtitles=_sub.srt:fontsdir=fonts:force_style='{style}'", "-c:v", "libx264", "-crf", "20",
    "-pix_fmt", "yuv420p", "-c:a", "copy", f"{NAME}_字幕.mp4", cwd=OUT)
(OUT / "_sub.srt").unlink()
print("total", round(t, 2), "→", OUT / f"{NAME}_字幕.mp4")
