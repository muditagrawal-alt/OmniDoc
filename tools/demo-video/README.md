# Demo video

How `docs/media/omnidoc-demo.mp4` and the README GIFs are made: a scripted walkthrough of the live site is
recorded as frames, then turned into a 1080p video with sped-up waits, film-style subtitles at the bottom centre
and a quiet music bed.

```bash
npm i -g @playwright/cli && npx playwright install chromium
mkdir -p /tmp/omnidoc-demo
PW_ROOT="$(npm root -g)/@playwright/cli/node_modules" CHROME="<path to Chromium>" \
  BASE=https://omnidoc-silk.vercel.app OUT=/tmp/omnidoc-demo node tools/demo-video/record.js
curl -o /tmp/inspired.mp3 https://incompetech.com/music/royalty-free/mp3-royaltyfree/Inspired.mp3
python tools/demo-video/make.py /tmp/omnidoc-demo /tmp/inspired.mp3 /tmp/omnidoc-demo/out
```

`record.js` drives a headless Chromium through the product page, the demo, two questions (one in Hindi) and the
library tools, logging when each subtitle starts and which waits to speed up. `make.py` needs ffmpeg and Pillow
(and Helvetica Neue, as on macOS); it writes `omnidoc-demo.mp4`, `omnidoc-demo.srt` and `timeline.json`, from
which the GIFs are cut. Music: “Inspired” by Kevin MacLeod (incompetech.com), CC BY 4.0.
