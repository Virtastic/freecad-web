const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const errs=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',defaultViewport:{width:1200,height:800},args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer'],protocolTimeout:900000,userDataDir:'/tmp/fc-diag'});
 const p=(await b.pages())[0];
 p.on('pageerror',e=>errs.push(String(e).slice(0,200)));
 p.on('console',m=>{const t=m.text(); if(/error|Error|fcweb/.test(t)) errs.push('CONSOLE '+t.slice(0,160));});
 await p.goto('http://localhost:8791/index.html',{waitUntil:'domcontentloaded',timeout:300000});
 const t0=Date.now(); let ready=false;
 while(Date.now()-t0<300000){ if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc))){ready=true;break;} await sl(500); }
 await sl(8000);
 await p.evaluate((c)=>{window.__CODE=c;}, require('fs').readFileSync('/tmp/ccxe2e.py','utf8'));
 const r=await p.evaluate(()=>{
   const m=window.fcInstance;
   const c=window.__CODE;
   const n=new TextEncoder().encode(c).length+1; const q=m._malloc(n); m.stringToUTF8(c,q,n);
   (window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);
   return 1;
 });
 await sl(900000);
 const log=await p.evaluate(()=>{const e=document.getElementById('log');return e?e.textContent.slice(-3000):'(no log el)';});
 fs.writeFileSync('/tmp/diag.txt','ready='+ready+'\nerrs='+errs.length+'\n'+errs.slice(0,6).join('\n')+'\n--- log tail ---\n'+log);
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/diag.txt','DRIVER '+String(e).slice(0,200));process.exit(0);});
