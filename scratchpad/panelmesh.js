const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const CODE=fs.readFileSync('/tmp/panelmesh.py','utf8');
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(500);}return false;};
(async()=>{
 let perr=0;
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=1400,900'],protocolTimeout:1200000,userDataDir:'/tmp/fc-panelmesh'});
 const p=(await b.pages())[0]; p.on('pageerror',e=>{perr++;});
 await p.goto('http://localhost:8799/index.html',{waitUntil:'domcontentloaded',timeout:240000});
 const t0=Date.now();while(Date.now()-t0<240000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',200000); await sl(6000);
 await runG(p,CODE);
 const done=await pw(p,'PM-END',300000); await sl(2000);
 const log=await p.evaluate(()=>document.getElementById('log').textContent);
 const out=log.split('\n').filter(x=>/PM-/.test(x)).join('\n')+'\n reachedEnd='+done+' pageErrs='+perr;
 fs.writeFileSync('/tmp/panelmesh.txt',out); console.log(out);
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/panelmesh.txt','DRIVER-ERR '+String(e).slice(0,250));process.exit(0);});
