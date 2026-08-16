const puppeteer=require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--enable-features=SharedArrayBuffer','--use-gl=angle','--use-angle=swiftshader','--ignore-gpu-blocklist']});
 const p=await b.newPage();
 const con=[]; p.on('console',m=>con.push(m.text())); p.on('pageerror',e=>con.push('[PAGEERR] '+e.message));
 await p.goto('http://localhost:8791/'+(process.argv[2]||''),{waitUntil:'domcontentloaded',timeout:60000});
 try{ await p.waitForFunction(()=>window.fcInstance&&window.fcInstance._malloc,{timeout:90000,polling:1000}); }catch(e){}
 await new Promise(r=>setTimeout(r,15000));
 const log=await p.evaluate(()=>document.getElementById('log').innerText).catch(()=>'');
 // union of page log + console, filter to warnings/errors
 const all=(log.split('\n').concat(con));
 const issues=all.filter(l=>/error|warning|cannot|fail|unable|not found|traceback|abort|missing|undefined|exception|no module/i.test(l))
   .filter(l=>!/using emscripten GL emulation|Automatic fallback to software WebGL/i.test(l));
 // dedup
 const seen=new Set(), out=[];
 for(const l of issues){ const k=l.replace(/\d+/g,'#').slice(0,90); if(!seen.has(k)){seen.add(k);out.push(l.slice(0,160));} }
 console.log('=== UNIQUE ISSUES ('+out.length+') ===\n'+out.join('\n'));
 await b.close();
})().catch(e=>{console.error('ERR',e);process.exit(1);});
