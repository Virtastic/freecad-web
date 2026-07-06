const puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--enable-features=SharedArrayBuffer','--use-gl=angle','--use-angle=swiftshader','--ignore-gpu-blocklist']});
 const p=await b.newPage();
 let last='';
 p.on('pageerror',e=>console.log('[PAGEERR]',e.message.slice(0,200)));
 await p.goto('http://localhost:8791/freecad-gui.html',{waitUntil:'domcontentloaded',timeout:60000}).catch(e=>console.log('[goto]',e.message));
 for(let i=0;i<20;i++){
   await new Promise(r=>setTimeout(r,4000));
   try{ const t=await p.evaluate(()=>document.getElementById('log')?document.getElementById('log').innerText:''); 
        const nu=t.slice(last.length); if(nu.trim()) console.log(nu.trim().split('\n').slice(-6).join('\n')); last=t;
   }catch(e){ console.log('[detached@'+(i*4)+'s]',e.message.slice(0,80)); break; }
 }
 await b.close().catch(()=>{});
})().catch(e=>{console.error(e);process.exit(1);});
