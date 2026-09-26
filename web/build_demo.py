"""Assemble the hosted preview (a single HTML page with everything inlined)
from the site's own files, so the story, the styling and the viewer stay
one source.  Usage: python build_demo.py <out_dir>  (needs info.json and
meshes.json in out_dir)."""
import re
import sys
from pathlib import Path

here = Path(__file__).parent
out = Path(sys.argv[1])
html = (here / "index.html").read_text()
css = (here / "style.css").read_text()
i18n = (here / "i18n.js").read_text().replace("export ", "")
core = (here / "viewer-core.js").read_text().replace("export ", "")
app = (here / "app.js").read_text()
app = re.sub(r"^import .*?from '\./.*?';\n", "", app, flags=re.M)     # local imports are inlined
app = app.replace("import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';\n", "")
app = app.replace("import { STLLoader } from 'three/addons/loaders/STLLoader.js';\n", "")

body = html[html.index("<body>") + len("<body>"):html.index("<script src=")]
importmap = re.search(r"<script type=\"importmap\">.*?</script>", html, re.S).group(0)
fonts = re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com[^>]*>', html).group(0)
demo_body = body.replace('data-i18n="eyebrow"', 'data-i18n="demoEyebrow"').replace('data-i18n="lede"', 'data-i18n="demoLede"')
# the hosted preview has no files to offer: drop the download links entirely
demo_body = re.sub(r'<div id="downloads".*?</div>\n', '', demo_body, flags=re.S)
page = f"""<meta charset="utf-8">
<title>The Sundial That Keeps Clock Time</title>
{fonts}
<style>
{css}
</style>
<script>document.documentElement.classList.add('static');</script>
{demo_body}
{importmap}
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ RoomEnvironment }} from 'three/addons/environments/RoomEnvironment.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';
import {{ STLLoader }} from 'three/addons/loaders/STLLoader.js';
{re.sub(r"^import .*$", "", core, flags=re.M)}
{i18n}
{app}
</script>
"""
(out / "index.html").write_text(page)
print("wrote", out / "index.html", len(page) // 1024, "KB")
