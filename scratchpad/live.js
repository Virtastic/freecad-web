const puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--enable-features=SharedArrayBuffer','--use-gl=angle','--use-angle=swiftshader','--ignore-gpu-blocklist']});
 const p=await b.newPage();
 p.on('console',m=>console.log('[c]',m.text()));
 p.on('pageerror',e=>console.log('[PAGEERR]',e.message));
 p.on('error',e=>console.log('[CRASH]',e.message));
 await p.goto('http://localhost:8791/freecad-gui.html',{waitUntil:'domcontentloaded',timeout:60000}).catch(e=>console.log('[goto]',e.message));
 await new Promise(r=>setTimeout(r,50000));
 await b.close().catch(()=>{});
})().catch(e=>{console.error(e);process.exit(1);});
