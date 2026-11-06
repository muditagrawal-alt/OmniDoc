"""
Turns the recorded frames (record.js) into the demo video: sped-up waits, movie-style subtitles at
the bottom centre, a quiet music bed, and short GIFs for the README.

    python make.py <recording dir> <music.mp3> <output dir>
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REC, MUSIC, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
WORK = REC / "work"
WORK.mkdir(exist_ok=True)
W, H = 1920, 1080          # the video
FW, FH = 1600, 900         # the recorded page, placed 1:1
FX, FY = (W - FW) // 2, 34  # leaves a 146 px band at the bottom for the subtitles
BAND_Y = FY + FH
FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 38, index=10)  # Medium
FPS = 30

log = json.loads((REC / "log.json").read_text())
frames = log["frames"]
t0 = frames[0][1]
fast = sorted([(f["start"] - t0, f["end"] - t0, f["factor"]) for f in log["fast"] if f.get("end")])


def out_time(t: float) -> float:
    """Recording time to video time, with the sped-up waits shortened."""
    shift = 0.0
    for a, b, k in fast:
        if t <= a:
            break
        shift += (min(t, b) - a) * (1 - 1 / k)
    return t - shift


# 1. The frames as a constant-rate video, waits sped up (concat list with each frame's duration).
times = [out_time(ts - t0) for _, ts in frames] + [out_time(log["end"] - t0)]
lines = []
for (idx, _), start, end in zip(frames, times, times[1:]):
    if end - start <= 0:
        continue
    lines.append(f"file '{REC / 'frames' / f'{idx:06d}.jpg'}'\nduration {end - start:.4f}")
lines.append(f"file '{REC / 'frames' / f'{frames[-1][0]:06d}.jpg'}'")
(WORK / "frames.txt").write_text("\n".join(lines) + "\n")
total = times[-1]
clean = WORK / "clean.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(WORK / "frames.txt"),
                "-vf", f"fps={FPS},scale={FW}:{FH}:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                "-crf", "17", str(clean)], check=True)

# 2. The backdrop: a dark stage with a soft shadow and a hairline around the page.
bg = Image.new("RGB", (W, H), (11, 13, 18))
shadow = Image.new("L", (W, H), 0)
ImageDraw.Draw(shadow).rounded_rectangle([FX - 6, FY + 8, FX + FW + 6, FY + FH + 18], 14, fill=150)
bg.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(22)))
ImageDraw.Draw(bg).rectangle([FX - 1, FY - 1, FX + FW, FY + FH], outline=(44, 50, 62))
bg.save(WORK / "stage.png")


# 3. Subtitles: white, centred, with a dark outline and shadow, as in films.
def wrap(text: str, width: int):
    words, rows, row = text.split(), [], ""
    for w in words:
        trial = f"{row} {w}".strip()
        if FONT.getlength(trial) <= width or not row:
            row = trial
        else:
            rows.append(row)
            row = w
    rows.append(row)
    return rows


def subtitle_png(text: str, path: Path):
    img = Image.new("RGBA", (W, H - BAND_Y), (0, 0, 0, 0))
    rows = wrap(text, 1500)
    line_h = 48
    top = ((H - BAND_Y) - line_h * len(rows)) // 2 - 4
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d_shade, d = ImageDraw.Draw(shade), ImageDraw.Draw(img)
    for i, row in enumerate(rows):
        x = (W - FONT.getlength(row)) / 2
        y = top + i * line_h
        d_shade.text((x, y + 3), row, font=FONT, fill=(0, 0, 0, 230), stroke_width=4, stroke_fill=(0, 0, 0, 230))
    img = Image.alpha_composite(shade.filter(ImageFilter.GaussianBlur(3)), img)
    d = ImageDraw.Draw(img)
    for i, row in enumerate(rows):
        x = (W - FONT.getlength(row)) / 2
        y = top + i * line_h
        d.text((x, y), row, font=FONT, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(8, 8, 10, 255))
    img.save(path)


subs = []
for k, c in enumerate(log["captions"]):
    start, end = out_time(c["start"] - t0), out_time((c["end"] or log["end"]) - t0)
    if end - start < 0.6:
        continue
    p = WORK / f"sub{k:02d}.png"
    subtitle_png(c["text"], p)
    subs.append((p, start + 0.15, end - 0.1, c["text"]))

# 4. Compose: stage, page, subtitles fading in and out; the music under it all.
inputs = ["-loop", "1", "-i", str(WORK / "stage.png"), "-i", str(clean)]
for p, *_ in subs:
    inputs += ["-loop", "1", "-i", str(p)]
inputs += ["-i", str(MUSIC)]
music = 2 + len(subs)
graph = [f"[0:v]trim=duration={total:.3f},setpts=PTS-STARTPTS[stage]", f"[stage][1:v]overlay={FX}:{FY}:shortest=1[v0]"]
for i, (p, s, e, _) in enumerate(subs):
    d = max(0.1, e - s)
    graph.append(f"[{i + 2}:v]format=rgba,trim=duration={total:.3f},fade=t=in:st={s:.3f}:d=0.25:alpha=1,"
                 f"fade=t=out:st={max(s, e - 0.25):.3f}:d=0.25:alpha=1[s{i}]")
    graph.append(f"[v{i}][s{i}]overlay=0:{BAND_Y}:enable='between(t,{s:.3f},{e:.3f})'[v{i + 1}]")
graph.append(f"[{music}:a]atrim=duration={total:.3f},volume=0.32,afade=t=in:d=1.5,afade=t=out:st={total - 3.5:.3f}:d=3.5[a]")
final = OUT / "omnidoc-demo.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph),
                "-map", f"[v{len(subs)}]", "-map", "[a]", "-r", str(FPS), "-c:v", "libx264", "-preset", "slow", "-crf", "22",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(final)],
               check=True)

# 5. Subtitles as an .srt too, for players that show them.
def stamp(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
(OUT / "omnidoc-demo.srt").write_text("".join(f"{i}\n{stamp(s)} --> {stamp(e)}\n{t}\n\n" for i, (_, s, e, t) in enumerate(subs, 1)))

json.dump({"duration": total, "subtitles": [(s, e, t) for _, s, e, t in subs]}, open(OUT / "timeline.json", "w"), indent=1)
print(f"video {total:.1f}s with {len(subs)} subtitles -> {final}")
