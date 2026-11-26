"""check_env.py：檢查這台機器能不能跑手冊裡的工具。必要項目缺少時結束碼為 1。"""
import sys, shutil, pathlib, subprocess, platform, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ok = True


def item(level, name, detail=""):
    global ok
    if level == "FAIL": ok = False
    print(f"[{level}] {name}" + (f"：{detail}" if detail else ""))


v = sys.version_info
item("PASS" if v >= (3, 10) else "FAIL", "Python", f"{v.major}.{v.minor}.{v.micro}（需要 3.10+）")

for mod, need in (("numpy", True), ("imageio_ffmpeg", True), ("playwright", True), ("cv2", False)):
    try:
        m = __import__(mod); item("PASS", mod, getattr(m, "__version__", ""))
    except ImportError:
        item("FAIL" if need else "WARN", mod, "未安裝：pip install -r requirements.txt" + ("" if need else "（只有手機畫面合成需要）"))

try:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, errors="ignore").stdout
    miss = [f for f in ("subtitles", "loudnorm", "ebur128", "atempo") if f" {f} " not in out]
    item("FAIL" if miss else "PASS", "ffmpeg", ff if not miss else f"缺少濾鏡 {miss}")
except Exception as e:
    item("FAIL", "ffmpeg", str(e))

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        launched = None
        for ch in (None, "chrome", "msedge"):
            try:
                b = p.chromium.launch(**({"channel": ch} if ch else {})); b.close(); launched = ch or "內建 chromium"; break
            except Exception:
                pass
    item("PASS" if launched else "FAIL", "瀏覽器", launched or "請執行 python -m playwright install chromium")
except Exception as e:
    item("FAIL", "瀏覽器", str(e))

# 字型：字幕與動畫範本預設用 Windows 字型；其他系統要改 project.json 的 subtitle.font_file 與 HTML 的 @font-face
fonts = {"微軟正黑體粗體（字幕）": "C:/Windows/Fonts/msjhbd.ttc",
         "思源黑體 NotoSansTC-VF（動畫）": "C:/Windows/Fonts/NotoSansTC-VF.ttf",
         "Cascadia Mono（範例程式碼畫面）": "C:/Windows/Fonts/CascadiaMono.ttf"}
for name, f in fonts.items():
    item("PASS" if pathlib.Path(f).exists() else "WARN", "字型 " + name,
         f if pathlib.Path(f).exists() else f"找不到 {f}（{platform.system()}）；請改設定指向本機的繁中字型")

node = os.environ.get("NODE") or shutil.which("node")
arch = pathlib.Path(os.environ.get("ARCHIFY") or pathlib.Path.home() / ".claude/skills/archify/bin/archify.mjs")
item("PASS" if node else "WARN", "Node.js（選用，流程圖）", node or "未安裝；範例已附做好的流程圖影片，不影響重建")
item("PASS" if arch.exists() else "WARN", "Archify（選用，流程圖）", str(arch) if arch.exists() else "未安裝；可設環境變數 ARCHIFY 指到 archify.mjs")

print("\n環境可以使用。" if ok else "\n有必要項目未通過，請依上面說明修正。")
sys.exit(0 if ok else 1)
