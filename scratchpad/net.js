const puppeteer=require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--enable-features=SharedArrayBuffer','--use-gl=angle','--use-angle=swiftshader','--ignore-gpu-blocklist']});
 const p=await b.newPage();
 const bad=[];
 p.on('response',r=>{ if(r.status()>=400) bad.push(r.status()+' '+r.url()); });
 p.on('requestfailed',r=>bad.push('FAILED '+r.url()+' '+(r.failure()&&r.failure().errorText)));
 await p.goto('http://localhost:8791/',{waitUntil:'domcontentloaded',timeout:60000});
 try{ await p.waitForFunction(()=>window.fcInstance&&window.fcInstance._malloc,{timeout:90000,polling:1000}); }catch(e){}
 await new Promise(r=>setTimeout(r,15000));
 console.log('=== BAD REQUESTS ('+bad.length+') ===\n'+[...new Set(bad)].join('\n'));
 await b.close();
})().catch(e=>{console.error('ERR',e);process.exit(1);});
