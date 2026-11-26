"""A4 流程圖段：依旁白長度排 Archify story 時間 → story video → 720p24 + 旁白 → 動畫/a4_vo.mp4，並把字幕時間寫回 ../project.json 的 a4 段
需要 Node.js 與 Archify；路徑可用環境變數 NODE、ARCHIFY 指定。沒有 Archify 時直接用 repo 內已做好的 動畫/a4_vo.mp4。"""
import json, wave, subprocess, pathlib, os, shutil
import imageio_ffmpeg
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
VO = ROOT / "語音"
FF = imageio_ffmpeg.get_ffmpeg_exe()
NODE = r"C:\Program Files\nodejs\node.exe"
ARCH = pathlib.Path(os.environ.get("ARCHIFY") or pathlib.Path.home() / ".claude/skills/archify/bin/archify.mjs")
FILES = ["A4_1", "A4_2", "A4_3"]
LEAD, GAP, TAIL = 0.4, 0.6, 1.4   # LEAD 0.4：A3 結尾已有 1 秒留白，避免接起來超過 2 秒靜音

def dur(n):
    w = wave.open(str(VO / f"講師_{n}.wav")); return w.getnframes() / w.getframerate()

cues, t = [], LEAD
for n in FILES:
    d = dur(n); cues.append([round(t, 3), round(t + d, 3)]); t += d + GAP
total = round(t - GAP + TAIL, 2)

story = json.load(open(HERE / "story.json", encoding="utf-8"))
starts = [0.0] + [c[0] - 0.3 for c in cues[1:]]
for k, st in enumerate(story["steps"]):
    st["at"] = round(starts[k], 2)
    st["duration"] = round((starts[k + 1] if k + 1 < len(starts) else total) - starts[k], 2)
story["duration"] = total
story["loop"] = False
json.dump(story, open(HERE / "story.timed.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

raw = HERE / "a4_1080.mp4"
subprocess.run([NODE, str(ARCH), "story", "video", "story.timed.json", raw.name, "--fps", "30", "--json"], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
out = ROOT / "動畫" / "a4_vo.mp4"
cmd = [FF, "-y", "-v", "error", "-i", str(raw)]
fl = []
for k, n in enumerate(FILES):
    cmd += ["-i", str(VO / f"講師_{n}.wav")]
    ms = int(cues[k][0] * 1000); fl.append(f"[{k+1}:a]adelay={ms}|{ms}[v{k}]")
fl.append("".join(f"[v{k}]" for k in range(len(FILES))) + f"amix=inputs={len(FILES)}:normalize=0,apad[a]")
# 底部留 88 px 給字幕：圖縮到 1124×632 置中，補上與流程圖相同的底色 #f3f4f6
fl.append("[0:v]scale=1124:632:flags=lanczos,pad=1280:720:78:0:color=0xf3f4f6,fps=24[v]")
cmd += ["-filter_complex", ";".join(fl), "-map", "[v]", "-map", "[a]", "-t", str(total),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)]
subprocess.run(cmd, check=True)
pj = ROOT / "project.json"
cfg = json.load(open(pj, encoding="utf-8"))
seg = next(x for x in cfg["segments"] if x["id"] == "a4")
for ln, c in zip(seg["lines"], cues): ln["at"] = c
json.dump(cfg, open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
raw.unlink()
print("a4", total, cues)
