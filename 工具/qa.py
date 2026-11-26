"""qa.py <project.json>

自動驗收成品，寫出 <output_dir>/qa/report.md 與 contact_sheet.jpg（每句字幕中點一格，供人或視覺模型目視檢查）。
檢查項目（FAIL 必須修，WARN 要人判斷）：
  1. 片長是否在 target_seconds ± tolerance
  2. 整體響度 I 與真峰值 TP（ebur128）
  3. 超過 2 秒的靜音、超過 0.5 秒的全黑畫面
  4. 字幕：重疊、太短（<0.8 秒）、太快（>9 字/秒）、單行太長、超出片長
"""
import sys, json, re, subprocess, pathlib
import imageio_ffmpeg
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 中文主控台（cp950）也能印

P = pathlib.Path(sys.argv[1]).resolve(); ROOT = P.parent
cfg = json.load(open(P, encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = ROOT / cfg.get("output_dir", "成品"); NAME = cfg.get("name", "成品")
QA = OUT / "qa"; QA.mkdir(exist_ok=True)
VID, SRT = OUT / f"{NAME}_字幕.mp4", OUT / f"{NAME}.srt"
MAXC = cfg.get("subtitle", {}).get("max_chars", 22)
rows = []


def add(level, item, detail): rows.append((level, item, detail))


def ff_err(*a):
    return subprocess.run([FF, "-hide_banner", *a], capture_output=True, text=True, errors="ignore").stderr


for f in (VID, SRT):
    if not f.exists(): sys.exit(f"缺少 {f}，請先執行 assemble.py")

info = ff_err("-i", str(VID))
h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info).groups(); dur = int(h) * 3600 + int(m) * 60 + float(s)
tgt, tol = cfg.get("target_seconds"), cfg.get("tolerance_seconds", 15)
if tgt:
    add("PASS" if abs(dur - tgt) <= tol else "WARN", "片長", f"{dur:.1f} 秒（目標 {tgt}±{tol}）")
else:
    add("PASS", "片長", f"{dur:.1f} 秒")

e = ff_err("-i", str(VID), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-")
I = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e)[-1]); TP = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", e)[-1])
add("PASS" if -18 <= I <= -13 else "WARN", "整體響度", f"{I} LUFS（網路影片建議 −16 左右）")
add("PASS" if TP <= -1.0 else "WARN", "真峰值", f"{TP} dBFS（應 ≤ −1）")

e = ff_err("-i", str(VID), "-vn", "-af", "silencedetect=noise=-45dB:d=2", "-f", "null", "-")
sil = re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)", e)
add("PASS" if not sil else "WARN", "長靜音（>2 秒）", "無" if not sil else "；".join(f"{float(a):.1f}–{float(b):.1f}" for a, b in sil))

e = ff_err("-i", str(VID), "-an", "-vf", "blackdetect=d=0.5:pix_th=0.08", "-f", "null", "-")
blk = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", e)
add("PASS" if not blk else "WARN", "全黑畫面（>0.5 秒）", "無" if not blk else "；".join(f"{float(a):.1f}–{float(b):.1f}" for a, b in blk))


def sec(x):
    hh, mm, rest = x.split(":"); ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


subs = []
for blk_ in SRT.read_text(encoding="utf-8").strip().split("\n\n"):
    ln = blk_.splitlines()
    a, b = [sec(x.strip()) for x in ln[1].split("-->")]
    subs.append((a, b, "\n".join(ln[2:])))
bad = []
for i, (a, b, txt) in enumerate(subs):
    n = len(txt.replace("\n", "")); d = b - a
    if i and a < subs[i - 1][1] - 0.01: bad.append(f"#{i+1} 與上一句重疊")
    if d < 0.8: bad.append(f"#{i+1} 只有 {d:.2f} 秒")
    if n / max(d, 0.01) > 9: bad.append(f"#{i+1} {n / d:.1f} 字/秒")
    if any(len(x) > MAXC for x in txt.splitlines()): bad.append(f"#{i+1} 單行超過 {MAXC} 字")
    if b > dur + 0.05: bad.append(f"#{i+1} 超出片長")
add("PASS" if not bad else "FAIL", f"字幕（{len(subs)} 句）", "全部正常" if not bad else "；".join(bad))

# contact sheet：每句字幕中點一格
for p in QA.glob("f_*.jpg"): p.unlink()
for i, (a, b, _) in enumerate(subs):
    subprocess.run([FF, "-v", "error", "-y", "-ss", f"{(a + b) / 2:.2f}", "-i", str(VID), "-frames:v", "1",
                    "-vf", "scale=480:-2", str(QA / f"f_{i:03d}.jpg")], check=True)
cols = 4; rws = (len(subs) + cols - 1) // cols
subprocess.run([FF, "-v", "error", "-y", "-framerate", "1", "-i", "qa/f_%03d.jpg", "-vf", f"tile={cols}x{rws}:padding=4",
                "-frames:v", "1", "qa/contact_sheet.jpg"], cwd=OUT, check=True)
for p in QA.glob("f_*.jpg"): p.unlink()

md = [f"# 自動驗收：{VID.name}", "", "| 結果 | 項目 | 說明 |", "| --- | --- | --- |"]
md += [f"| {l} | {i} | {d} |" for l, i, d in rows]
md += ["", "contact_sheet.jpg：依字幕順序，每句一格（左到右、上到下）。逐格檢查字幕是否蓋住畫面重點、畫面有無變形或錯字。",
       "", "**自動檢查不能取代試聽**：唸錯字、口音、嘴型、音樂與台詞的感覺，必須由人從頭看聽一次（見手冊 04_輸出與驗收.md）。"]
(QA / "report.md").write_text("\n".join(md), encoding="utf-8")
for l, i, d in rows: print(f"[{l}] {i}：{d}")
print("→", QA / "report.md")
sys.exit(1 if any(l == "FAIL" for l, _, _ in rows) else 0)
