# React Bits components

Animated components from [React Bits](https://reactbits.dev) by David Haz (MIT + Commons Clause),
copied in as the library intends and used on the landing page (`src/landing/`):

| Component | Used for |
|---|---|
| LiquidChrome | The liquid metal the hero's product screenshot rises out of (WebGL 2, no dependencies) |
| Threads | The background of the closing call to action (WebGL, no dependencies) |
| RotatingText | "Ask your annual reports / contracts / ..." |
| CardSwap | The 3D stack of product screenshots in the closing call to action |
| SpotlightCard | Feature cards |
| CountUp | Benchmark figures |
| LogoLoop | Formats and languages |
| ShinyText | The hero badge |

Changes from upstream: CardSwap's demo cards and the icon library they needed are removed (OmniDoc
passes its own cards), and the `'use client'` directives are dropped (this is a Vite app). RotatingText
and CountUp need `motion`.
