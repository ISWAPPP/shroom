#!/usr/bin/env bash
# Rebuild the Material Symbols subset after adding icons to frontend/src/Icons.tsx.
# Keeps only ligatures for icons used by the portal (4 MB -> a few KB). Needs fonttools+brotli (venv path below).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${FT_PY:-python3}
SRC=frontend/node_modules/material-symbols/material-symbols-outlined.woff2
OUT=frontend/src/assets/symbols-subset.woff2
mkdir -p frontend/src/assets
ICONS=$(grep -o "sym('[a-z_0-9]*')" frontend/src/Icons.tsx | sed "s/sym('//;s/')//"; grep -oE "content:'[a-z_]+'" frontend/src/style.css | sed "s/content:'//;s/'//")
"$PY" - "$SRC" "$OUT" $ICONS <<'EOF'
import sys
from fontTools import subset
from fontTools.ttLib import TTFont
src,out,*icons=sys.argv[1:]
font=TTFont(src); order=set(font.getGlyphOrder())
icons=sorted({i for i in icons if i in order}|{i+'.fill' for i in icons if i+'.fill' in order})
letters=[c for c in 'abcdefghijklmnopqrstuvwxyz0123456789_']
opts=subset.Options(); opts.flavor='woff2'; opts.layout_features=['liga','rlig','rclt','calt','ccmp']; opts.layout_closure=False
opts.notdef_outline=True; opts.name_IDs=['*']; opts.drop_tables+=['DSIG']
s=subset.Subsetter(opts); s.populate(glyphs=icons+['space'],text=''.join(letters)); s.subset(font)
font.flavor='woff2'; font.save(out); print(out, len(icons), 'glyphs')
EOF
ls -la "$OUT"
