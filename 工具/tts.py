"""tts.py <project.json> [段落id ...] [--force]

不用 Flow 時產生旁白：把 project.json 裡每個 lines 項目的文字用 edge-tts（微軟線上神經語音，免費、需連網）
唸成 WAV，存到該項目的 "wav" 路徑。已存在的 WAV 不覆蓋，除非加 --force（只重做唸錯的那句：先刪掉那個 WAV 再跑）。

設定（project.json）：
  "tts": {"voice": "zh-TW-HsiaoChenNeural", "rate": "+0%", "pitch": "+0Hz"}
  段落或單句也可以各自覆寫 "voice"／"rate"。
  單句加 "say"：實際要唸的文字（字幕仍用 "text"）。用來修正讀音，例如 "text": "cnt 加一" → "say": "C N T 加一"。
台灣華語聲音：zh-TW-HsiaoChenNeural（女，預設）、zh-TW-HsiaoYuNeural（女）、zh-TW-YunJheNeural（男）。
type 為 "video" 的段落若有 "dub" 與 "text"，也會產生配音。
"""
import sys, json, asyncio, subprocess, pathlib, tempfile
import imageio_ffmpeg
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    import edge_tts
except ImportError:
    sys.exit("請先安裝：pip install edge-tts")

args = [a for a in sys.argv[1:] if a != "--force"]; FORCE = "--force" in sys.argv
P = pathlib.Path(args[0]).resolve(); ROOT = P.parent
cfg = json.load(open(P, encoding="utf-8"))
only = set(args[1:])
FF = imageio_ffmpeg.get_ffmpeg_exe()
base = {"voice": "zh-TW-HsiaoChenNeural", "rate": "+0%", "pitch": "+0Hz", **cfg.get("tts", {})}

jobs = []
for seg in cfg["segments"]:
    if only and seg["id"] not in only: continue
    sopt = {k: seg[k] for k in ("voice", "rate", "pitch") if k in seg}
    items = list(seg.get("lines", []))
    if seg.get("type") == "video" and seg.get("dub") and seg.get("text"):
        items.append({"wav": seg["dub"], "text": seg["text"], **({"say": seg["say"]} if "say" in seg else {})})
    for ln in items:
        if "wav" not in ln or not (ln.get("say") or ln.get("text")): continue
        out = ROOT / ln["wav"]
        if out.exists() and not FORCE: continue
        opt = {**base, **sopt, **{k: ln[k] for k in ("voice", "rate", "pitch") if k in ln}}
        jobs.append((ln.get("say") or ln["text"], opt, out))


async def main():
    for text, opt, out in jobs:
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            mp3 = pathlib.Path(td) / "a.mp3"
            await edge_tts.Communicate(text, opt["voice"], rate=opt["rate"], pitch=opt["pitch"]).save(str(mp3))
            # 先切掉 TTS 自帶的頭尾靜音（各約 0.5 秒，會讓段落交界出現 2 秒以上的空白），
            # 再前後各補 0.15 秒，避免字頭字尾被切；輸出 24 kHz 單聲道 WAV
            trim = "silenceremove=start_periods=1:start_threshold=-50dB"
            subprocess.run([FF, "-y", "-v", "error", "-i", str(mp3), "-af",
                            f"{trim},areverse,{trim},areverse,adelay=150|150,apad=pad_dur=0.15",
                            "-ar", "24000", "-ac", "1", str(out)], check=True)
        print("✓", out.relative_to(ROOT), "｜", text)

asyncio.run(main())
print(f"完成 {len(jobs)} 句" + ("" if jobs else "（全部已存在；要重做請加 --force 或刪掉該 WAV）"))
