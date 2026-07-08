const fs=require('fs');const puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PY=fs.readFileSync(process.argv[2],'utf8');
const PROFILE='/tmp/fc-warm';   // fixed, reused, never wiped (wasm is stable)
(async()=>{
  const b=await puppeteer.launch({executablePath:CHROME,headless:'new',
    args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192',
          '--use-gl=angle','--use-angle=swiftshader','--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'],
    protocolTimeout:600000,userDataDir:PROFILE});
  const p=await b.newPage();
  await p.goto('http://localhost:8799/freecad-gui.html',{waitUntil:'domcontentloaded',timeout:120000});
  await p.waitForFunction(()=>window.fcInstance&&window.fcInstance._malloc,{timeout:540000,polling:2500});
  await new Promise(r=>setTimeout(r,10000));
  try{await p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);try{m._fcweb_run_python(q);}finally{m._free(q);}},PY);}catch(e){console.log('[EVAL] '+String(e.message).slice(0,60));}
  await new Promise(r=>setTimeout(r,5000));
  let log='';try{log=await p.evaluate(()=>document.getElementById('log').innerText);}catch(e){log='[read-fail]';}
  console.log(log.split('\n').filter(l=>/STEP|OK|FAIL|DONE|Error|Traceback/.test(l)).slice(-40).join('\n'));
  await b.close().catch(()=>{});
})().catch(e=>{console.error('CRASH '+e.message.slice(0,60));process.exit(1);});
