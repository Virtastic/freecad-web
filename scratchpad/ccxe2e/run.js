// End-to-end: box -> gmsh mesh -> CalculiX solve -> results, in the real browser.
const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const CODE=fs.readFileSync('/tmp/ccxe2e.py','utf8');
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(1000);}return false;};
(async()=>{
 let perr=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',defaultViewport:{width:1400,height:900},args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer'],protocolTimeout:2400000,userDataDir:'/tmp/fc-ccxe2e'});
 const p=(await b.pages())[0];
 p.on('pageerror',e=>perr.push(String(e).slice(0,140)));
 await p.goto('http://localhost:8791/index.html',{waitUntil:'domcontentloaded',timeout:300000});
 const t0=Date.now();while(Date.now()-t0<300000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',240000); await sl(6000);
 const bridges=await p.evaluate(()=>({ccx:typeof window.fcwebCcxRun,gmsh:typeof window.fcwebGmshRun}));
 await runG(p,CODE);
 const done=await pw(p,'CX-END',1500000); await sl(2000);
 const log=await p.evaluate(()=>document.getElementById('log').textContent);
 const out=['bridges='+JSON.stringify(bridges)]
   .concat(log.split('\n').filter(x=>/CX-/.test(x)))
   .concat(['reachedEnd='+done,'pageErrs='+perr.length].concat(perr.slice(0,4))).join('\n');
 fs.writeFileSync('/tmp/ccxe2e.txt',out); console.log(out);
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{const m='DRIVER-ERR '+String(e).slice(0,300);fs.writeFileSync('/tmp/ccxe2e.txt',m);console.log(m);process.exit(0);});
