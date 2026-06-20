"""Apply AGD ambient aesthetic to all inner ManifestYOU pages."""
import pathlib, re

ROOT = pathlib.Path(__file__).parent.parent

PAGES = [
    ROOT / "benchmark.html",
    ROOT / "writing.html",
    ROOT / "for-models.html",
    ROOT / "start.html",
    ROOT / "writing/benchmark-honest-result.html",
    ROOT / "writing/benchmark-v2-hallucination.html",
]

AGD_CSS = """
  /* ── AGD ambient layer ───────────────────────────────── */
  @keyframes agd-float{
    0%  {opacity:0;transform:translate(0,0);}
    12% {opacity:.4;}
    50% {opacity:.2;transform:translate(12px,-50px);}
    88% {opacity:.4;}
    100%{opacity:0;transform:translate(24px,-100px);}
  }
  @keyframes agd-sweep-a{
    0%,3%  {opacity:0;transform:translate(-45vw,35vh) scale(.9);}
    12%    {opacity:.7;transform:translate(-15vw,20vh) scale(1.1);}
    25%    {opacity:.3;transform:translate(10vw,5vh) scale(1);}
    38%    {opacity:.85;transform:translate(30vw,-5vh) scale(1.25);}
    52%    {opacity:.25;transform:translate(55vw,-15vh) scale(1);}
    65%    {opacity:.7;transform:translate(75vw,-22vh) scale(1.1);}
    78%    {opacity:0;transform:translate(105vw,-30vh) scale(.9);}
    79%,100%{opacity:0;transform:translate(-45vw,35vh) scale(.9);}
  }
  @keyframes agd-sweep-b{
    0%,38% {opacity:0;transform:translate(110vw,70vh) scale(.9);}
    50%    {opacity:.65;transform:translate(80vw,45vh) scale(1.2);}
    60%    {opacity:.25;transform:translate(55vw,25vh) scale(1);}
    72%    {opacity:.8;transform:translate(30vw,5vh) scale(1.25);}
    84%    {opacity:.15;transform:translate(5vw,-15vh) scale(1);}
    94%    {opacity:0;transform:translate(-20vw,-30vh) scale(.9);}
    95%,100%{opacity:0;transform:translate(110vw,70vh) scale(.9);}
  }
  #agd-nav{
    position:fixed;top:0;left:0;right:0;z-index:50;
    padding:20px 32px;display:flex;justify-content:space-between;align-items:center;
    backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
  }
  #agd-nav a{
    font-family:'JetBrains Mono',monospace;font-weight:300;font-size:11px;
    letter-spacing:.32em;text-transform:uppercase;color:var(--gold);
    text-decoration:none;transition:opacity .2s;
  }
  #agd-nav a:hover{opacity:.6;}
  #agd-nav .agd-date{
    font-family:'JetBrains Mono',monospace;font-size:11px;
    letter-spacing:.32em;text-transform:uppercase;color:rgba(200,169,126,.4);
  }
  #agd-ambient{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden;}
  .agd-orb-a{
    position:absolute;width:700px;height:700px;border-radius:50%;
    background:radial-gradient(circle,rgba(168,211,141,.11) 0%,rgba(168,211,141,.03) 45%,transparent 70%);
    animation:agd-sweep-a 22s ease-in-out infinite;
  }
  .agd-orb-b{
    position:absolute;width:500px;height:500px;border-radius:50%;
    background:radial-gradient(circle,rgba(168,211,141,.08) 0%,rgba(168,211,141,.02) 40%,transparent 65%);
    animation:agd-sweep-b 28s ease-in-out infinite;
  }
  .agd-sym{
    position:absolute;font-size:13px;color:var(--gold);opacity:0;
    font-family:'JetBrains Mono',monospace;
    animation:agd-float var(--dur) linear var(--delay) infinite;
    user-select:none;
  }
"""

AGD_HTML = """
<nav id="agd-nav">
  <a href="/">∇ ManifestYOU</a>
  <span class="agd-date">2026</span>
</nav>
<div id="agd-ambient" aria-hidden="true">
  <div class="agd-orb-a"></div>
  <div class="agd-orb-b"></div>
  <span class="agd-sym" style="left:8%;top:18%;--dur:28s;--delay:0s">∂</span>
  <span class="agd-sym" style="left:82%;top:12%;--dur:34s;--delay:6s">∑</span>
  <span class="agd-sym" style="left:22%;top:72%;--dur:38s;--delay:11s">∫</span>
  <span class="agd-sym" style="left:68%;top:58%;--dur:26s;--delay:3s">Δ</span>
  <span class="agd-sym" style="left:48%;top:88%;--dur:22s;--delay:14s">π</span>
  <span class="agd-sym" style="left:91%;top:38%;--dur:32s;--delay:8s">ε</span>
  <span class="agd-sym" style="left:12%;top:52%;--dur:29s;--delay:18s">α</span>
  <span class="agd-sym" style="left:58%;top:28%;--dur:42s;--delay:2s">λ</span>
  <span class="agd-sym" style="left:76%;top:78%;--dur:24s;--delay:20s">β</span>
  <span class="agd-sym" style="left:36%;top:42%;--dur:36s;--delay:9s">∞</span>
  <span class="agd-sym" style="left:5%;top:85%;--dur:30s;--delay:16s">σ</span>
  <span class="agd-sym" style="left:94%;top:65%;--dur:27s;--delay:5s">μ</span>
</div>
"""

def patch(path: pathlib.Path):
    src = path.read_text(encoding="utf-8")

    # 1. add --green to :root
    if "--green" not in src:
        src = re.sub(
            r"(--near-black:#080808;)",
            r"\1\n    --green:#A8D38D; --gold-soft:rgba(214,195,154,0.9);",
            src, count=1
        )

    # 2. inject AGD CSS before first </style>
    if "agd-float" not in src:
        src = src.replace("</style>", AGD_CSS + "</style>", 1)

    # 3. inject nav + ambient div right after <body>
    if "agd-nav" not in src:
        src = src.replace("<body>", "<body>" + AGD_HTML, 1)

    # 4. swap ◉ → ∇ in .mark spans and footer marks
    src = src.replace(">◉<", ">∇<")

    path.write_text(src, encoding="utf-8")
    print(f"  patched {path.relative_to(ROOT)}")


for p in PAGES:
    patch(p)

print("Done.")
