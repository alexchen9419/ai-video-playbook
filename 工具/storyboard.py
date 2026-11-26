"""storyboard.py <project.json>

從 project.json 產生標準格式分鏡表（Film Story Board）：
  <專案>/分鏡表.pdf                 A4 直式，每列一鏡（動畫段每句旁白一列＝一拍），含影格縮圖
  <output_dir>/<name>_分鏡表.html  同內容（中間檔），可在瀏覽器看
  <專案>/分鏡表.md                  Markdown 版（放進 repo、貼進腳本用）

資料來源（唯一來源是 project.json，不要另外手抄一份）：
  頂層 "board": {"title", "subtitle", "acts": [{"name", "segments": [id...], "time_of_day", "lighting", "cast", "purpose", "focus"}]}
  每段 "board": {"shot_size" 景別, "camera" 機位運鏡, "beats" 秒數節拍, "action" 畫面與表演, "lighting" 光線,
                 "tone" 語氣, "sound" 聲音, "transition" 轉場, "post" 後製／注意（**粗體** 會保留）, "status" 狀態}
  動畫段每句 lines[k].board: {"visual" 畫面元素, "timing" 時機與動作}
影格（依序取第一個找得到的）：
  1. <專案>/分鏡影格/<鏡號>.png（或 <鏡號>_<k>.png，動畫段第 k 拍）
  2. 成品影片（需先跑 assemble.py）中該鏡／該拍的中間時刻
  3. 該段原始影片（影片/…、build/<id>.mp4）的中間時刻
"""
import sys, json, re, html, base64, subprocess, pathlib, wave
import imageio_ffmpeg
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = pathlib.Path(sys.argv[1]).resolve(); ROOT = P.parent
cfg = json.load(open(P, encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
NAME = cfg.get("name", "成品")
OUT = ROOT / cfg.get("output_dir", "成品"); OUT.mkdir(exist_ok=True)
BUILD = ROOT / cfg.get("build_dir", "build")
FINAL = OUT / f"{NAME}_無字幕.mp4"
SEGJ = OUT / f"{NAME}.segments.json"
starts = {s: (a, d) for s, a, d in json.load(open(SEGJ, encoding="utf-8"))} if SEGJ.exists() else {}
B = cfg.get("board", {})
TYPE = {"video": "Flow", "anim": "動畫", "clip": "片段"}


def frame(src, t):
    r = subprocess.run([FF, "-v", "error", "-ss", f"{max(t, 0):.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=320:-2", "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "-"], capture_output=True)
    return r.stdout or None


def still(seg, k, t_local):
    sid = seg["id"]
    for f in ([ROOT / "分鏡影格" / f"{sid}_{k+1}.png"] if k is not None else []) + [ROOT / "分鏡影格" / f"{sid}.png"]:
        if f.exists():
            return frame(f, 0)
    if FINAL.exists() and sid in starts:
        return frame(FINAL, starts[sid][0] + t_local)
    src = BUILD / f"{sid}.mp4" if seg.get("type") == "anim" else ROOT / seg.get("src", "")
    return frame(src, t_local) if src.is_file() else None


def wav_dur(p):
    with wave.open(str(p)) as w: return w.getnframes() / w.getframerate()


def fmt(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def seg_cues(seg):
    """動畫段每句的 [開始, 結束]（相對該段）；clip 用 lines[].at。"""
    cj = BUILD / f"{seg['id']}.cues.json"
    if seg.get("type") == "anim" and cj.exists():
        return json.load(open(cj))["cues"]
    if seg.get("type") == "anim":  # 還沒輸出動畫：依旁白長度推算
        t, out = seg.get("lead", 0.8), []
        for ln in seg["lines"]:
            d = wav_dur(ROOT / ln["wav"]); out.append([t, t + d]); t += d + seg.get("gap", 0.5)
        return out
    return [ln.get("at") for ln in seg.get("lines", [])]


# ---- 整理成列 ----
rows = []   # 每列：dict(id, label, kind, tc, size, camera, action, line, sound, post, img)
for seg in cfg["segments"]:
    b = seg.get("board", {}); sid = seg["id"]; typ = seg.get("type", "video")
    a0, dur = starts.get(sid, (None, None))
    tc = f"{fmt(a0)}–{fmt(a0 + dur)}（{dur:.0f} 秒）" if a0 is not None else ""
    lines = seg.get("lines", [])
    if typ == "video" or not lines:
        txt = seg.get("text", "")
        rows.append(dict(id=sid, kind=TYPE.get(typ, typ), tc=tc, b=b, line=txt, sub=None,
                         img=still(seg, None, (dur or 8) / 2)))
        continue
    cues = seg_cues(seg)
    one = len(lines) == 1
    for k, ln in enumerate(lines):
        c = cues[k] if k < len(cues) and cues[k] else None
        lb = ln.get("board", {})
        tck = f"本拍 {fmt(a0 + c[0])}–{fmt(a0 + c[1])}" if (a0 is not None and c and not one) else ""
        tcs = ("段 " + tc if not one else tc) if k == 0 and tc else ""
        rows.append(dict(id=sid if one else f"{sid}-{k+1}", kind=TYPE.get(typ, typ), tc="<br>".join(x for x in (tcs, tck) if x),
                         b=b if k == 0 else {}, line=ln.get("text", ""), sub=lb,
                         img=still(seg, k, (c[0] + c[1]) / 2 if c else 1.0)))

act_of = {s: a for a in B.get("acts", []) for s in a.get("segments", [])}


def md_inline(s):
    s = html.escape(s or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s).replace("\n", "<br>")


def cell_visual(r):
    b, sb = r["b"], r["sub"] or {}
    parts = []
    if sb.get("visual"): parts.append(md_inline(sb["visual"]))
    if b.get("action"): parts.append(md_inline(b["action"]))
    if sb.get("timing"): parts.append('<span class="muted">' + md_inline(sb["timing"]) + "</span>")
    if b.get("beats"): parts.append('<span class="muted">節拍：' + md_inline(b["beats"]) + "</span>")
    if b.get("lighting"): parts.append('<span class="muted">光線：' + md_inline(b["lighting"]) + "</span>")
    return "<br>".join(parts)


# ---- HTML / PDF ----
css = """
@font-face{font-family:TC;src:local('Microsoft JhengHei'),url('file:///C:/Windows/Fonts/msjh.ttc'),local('Noto Sans TC'),local('PingFang TC');}
@page{size:A4 portrait;margin:12mm 10mm 14mm}
body{font-family:TC,sans-serif;color:#1f2937;font-size:9.5pt;margin:0}
h1{font-size:17pt;margin:0 0 2mm} .sub{color:#6b7280;margin-bottom:4mm}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th,td{border:0.6pt solid #9ca3af;padding:1.6mm;vertical-align:top;word-break:break-word}
th{background:#1f2937;color:#fff;font-weight:700;font-size:9pt}
thead{display:table-header-group} tr{page-break-inside:avoid}
td.id{font-weight:800;font-size:11pt;text-align:center} td.id small{display:block;font-weight:400;font-size:8pt;color:#6b7280}
td.img img{width:100%;display:block;border-radius:1mm} td.img .none{height:22mm;background:#e5e7eb;border-radius:1mm}
.act td{background:#f3f4f6;border-left:2.5pt solid #2563eb;font-size:9pt}
.act b{font-size:10.5pt} .muted{color:#6b7280} b{color:#b91c1c}
.tl{margin:0 0 5mm} .tl td,.tl th{font-size:8.5pt}
"""
h = [f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(NAME)} 分鏡表</title><style>{css}</style></head><body>",
     f"<h1>{html.escape(B.get('title', NAME))}｜分鏡表</h1>",
     f"<div class='sub'>{html.escape(B.get('subtitle', ''))}　共 {len(cfg['segments'])} 段、{len(rows)} 列"
     + (f"，總長 {fmt(sum(d for _, d in starts.values()))}" if starts else "") + "</div>"]
if B.get("acts"):
    h.append("<table class='tl'><thead><tr><th style='width:22%'>幕</th><th style='width:20%'>時碼</th><th style='width:9%'>段數</th>"
             "<th style='width:14%'>時段</th><th>展示重點</th></tr></thead><tbody>")
    for a in B["acts"]:
        ss = [starts[s] for s in a["segments"] if s in starts]
        tca = f"{fmt(ss[0][0])}–{fmt(ss[-1][0] + ss[-1][1])}" if ss else ""
        h.append(f"<tr><td><b>{html.escape(a['name'])}</b></td><td>{tca}</td><td>{len(a['segments'])}</td>"
                 f"<td>{html.escape(a.get('time_of_day', ''))}</td><td>{md_inline(a.get('focus', ''))}</td></tr>")
    h.append("</tbody></table>")
h.append("<table><colgroup><col style='width:9%'><col style='width:22%'><col style='width:13%'><col style='width:26%'>"
         "<col style='width:16%'><col style='width:14%'></colgroup><thead><tr><th>鏡號</th><th>影格</th><th>景別／運鏡<br>時碼</th>"
         "<th>畫面與表演</th><th>台詞／旁白</th><th>聲音／後製</th></tr></thead><tbody>")
for r in rows:
    seg_id = r["id"].rsplit("-", 1)[0] if r["id"] not in act_of else r["id"]
    a = act_of.get(seg_id)
    if a and a.get("_shown") is None:
        a["_shown"] = True
        ok_ = lambda v: v and v != "—"
        meta = "｜".join(x for x in (a.get("time_of_day") if ok_(a.get("time_of_day")) else None,
                                     ok_(a.get("lighting")) and "光線：" + a["lighting"], ok_(a.get("cast")) and "出場：" + a["cast"]) if x)
        h.append(f"<tr class='act'><td colspan='6'><b>{html.escape(a['name'])}</b>　{html.escape(meta)}<br>"
                 f"劇情目的：{md_inline(a.get('purpose', ''))}　展示重點：{md_inline(a.get('focus', ''))}</td></tr>")
    b = r["b"]
    img = f"<img src='data:image/jpeg;base64,{base64.b64encode(r['img']).decode()}'>" if r["img"] else "<div class='none'></div>"
    cam = "<br>".join(md_inline(x) for x in (b.get("shot_size"), b.get("camera")) if x)
    tone = f"<br><span class='muted'>（{md_inline(b['tone'])}）</span>" if b.get("tone") else ""
    sp = [md_inline(x) for x in (b.get("sound"),) if x] + [md_inline(x) for x in (b.get("post"),) if x]
    if b.get("transition"): sp.append("<span class='muted'>轉場：" + md_inline(b["transition"]) + "</span>")
    if b.get("status"): sp.append("<span class='muted'>狀態：" + md_inline(b["status"]) + "</span>")
    h.append(f"<tr><td class='id'>{html.escape(r['id'])}<small>{r['kind']}</small></td><td class='img'>{img}</td>"
             f"<td>{cam}{'<br>' if cam and r['tc'] else ''}<span class='muted'>{r['tc']}</span></td><td>{cell_visual(r)}</td>"
             f"<td>{md_inline(r['line'])}{tone}</td><td>{'<br>'.join(sp)}</td></tr>")
h.append("</tbody></table></body></html>")
hp = OUT / f"{NAME}_分鏡表.html"; hp.write_text("".join(h), encoding="utf-8")

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = None
    for ch in dict.fromkeys([cfg.get("browser_channel"), None, "chrome", "msedge"]):
        try: b = p.chromium.launch(**({"channel": ch} if ch else {})); break
        except Exception: pass
    pg = b.new_page(); pg.goto(hp.as_uri()); pg.evaluate("document.fonts.ready")
    pg.pdf(path=str(ROOT / "分鏡表.pdf"), format="A4", print_background=True,
           display_header_footer=True, header_template="<span></span>",
           footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'><span class='pageNumber'></span> / <span class='totalPages'></span></div>",
           margin={"top": "12mm", "bottom": "14mm", "left": "10mm", "right": "10mm"})
    b.close()

# ---- Markdown ----
def plain(s): return (s or "").replace("|", "｜").replace("\n", " ")
md = [f"# {B.get('title', NAME)}｜分鏡表", "", "> 由 `工具/storyboard.py` 依 `project.json` 產生，請改 project.json 的 board 欄位再重新產生，不要直接改這個檔。", ""]
if B.get("acts"):
    md += ["## 整體時間軸", "", "| 幕 | 時碼 | 段數 | 時段 | 展示重點 |", "| --- | --- | --- | --- | --- |"]
    for a in B["acts"]:
        ss = [starts[s] for s in a["segments"] if s in starts]
        tca = f"{fmt(ss[0][0])}–{fmt(ss[-1][0] + ss[-1][1])}" if ss else ""
        md.append(f"| {plain(a['name'])} | {tca} | {len(a['segments'])} | {plain(a.get('time_of_day'))} | {plain(a.get('focus'))} |")
    md.append("")
md += ["## 逐鏡", "", "| 鏡號 | 來源 | 時碼 | 景別／運鏡 | 畫面與表演 | 台詞／旁白 | 聲音／後製 |", "| --- | --- | --- | --- | --- | --- | --- |"]
for r in rows:
    b, sb = r["b"], r["sub"] or {}
    vis = "；".join(plain(x) for x in (sb.get("visual"), b.get("action"), sb.get("timing"), b.get("beats") and "節拍：" + b["beats"]) if x)
    md.append(f"| {r['id']} | {r['kind']} | {r['tc'].replace('<br>', ' ')} | {plain('｜'.join(x for x in (b.get('shot_size'), b.get('camera')) if x))} | "
              f"{vis} | {plain(r['line'])}{'（' + plain(b['tone']) + '）' if b.get('tone') else ''} | "
              f"{'；'.join(plain(x) for x in (b.get('sound'), b.get('post')) if x)} |")
(ROOT / "分鏡表.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("→", ROOT / "分鏡表.pdf"); print("→", ROOT / "分鏡表.md")
