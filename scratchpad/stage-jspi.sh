#!/bin/bash
set -e
cd /Users/mstavridis/Downloads/FreeCAD-Web
bash scratchpad/linkcmds/fc-post-weh.sh 2>&1 | grep -E "minified GL patches" || true
python3 - <<'PY'
import re
p='play-gui/FreeCAD.js'; s=open(p).read(); out=[]
if 'pname==5634' in s: out.append('mat:already')
else:
    m=re.search(r"else if\(pname==5633\)\{GLEmulation\.materialShininess\[0\]=(HEAPF32|GROWABLE_HEAP_F32\(\))\[param(>>>2>>>0|>>2)\]\}else\{0\}\}(;?)var _emscripten_glMaterialfv", s)
    if m:
        H,SH,semi=m.groups()
        mad=('else if(pname==5633){GLEmulation.materialShininess[0]='+H+'[param'+SH+']}'
         'else if(pname==5632){GLEmulation.materialEmission[0]='+H+'[param'+SH+'];GLEmulation.materialEmission[1]='+H+'[param+4'+SH+'];GLEmulation.materialEmission[2]='+H+'[param+8'+SH+'];GLEmulation.materialEmission[3]='+H+'[param+12'+SH+']}'
         'else if(pname==5634){var _r='+H+'[param'+SH+'],_g='+H+'[param+4'+SH+'],_b='+H+'[param+8'+SH+'],_a='+H+'[param+12'+SH+'];'
         'GLEmulation.materialAmbient[0]=_r;GLEmulation.materialAmbient[1]=_g;GLEmulation.materialAmbient[2]=_b;GLEmulation.materialAmbient[3]=_a;'
         'GLEmulation.materialDiffuse[0]=_r;GLEmulation.materialDiffuse[1]=_g;GLEmulation.materialDiffuse[2]=_b;GLEmulation.materialDiffuse[3]=_a}'
         'else{0}}'+semi+'var _emscripten_glMaterialfv')
        s=s.replace(m.group(0),mad,1); out.append('mat:OK')
    else: out.append('mat:MISS')
old='wasmTableMirror[funcPtr]=func=wasmTable.get(funcPtr);if(Asyncify.isAsyncExport(func)){wasmTableMirror[funcPtr]=func=Asyncify.makeAsyncFunction(func)}}return func}'
new='try{wasmTableMirror[funcPtr]=func=wasmTable.get(funcPtr)}catch(e){func=undefined}if(func&&Asyncify.isAsyncExport(func)){wasmTableMirror[funcPtr]=func=Asyncify.makeAsyncFunction(func)}}if(!func){return function(){return 0}}return func}'
if 'catch(e){func=undefined}' in s: out.append('tbl:already')
elif old in s: s=s.replace(old,new,1); out.append('tbl:OK')
else: out.append('tbl:MISS')
open(p,'w').write(s); print(' | '.join(out))
PY
cp play-gui/freecad-gui.html play-gui/index.html
node scratchpad/wasmvalidate.js FreeCAD.wasm 2>&1 | tail -1
