const puppeteer=require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--enable-features=SharedArrayBuffer']});
 const p=await b.newPage();
 // patch BEFORE scripts run: intercept to log clobbered value. Instead read after boot.
 await p.goto('http://localhost:8791/freecad-gui.html',{waitUntil:'domcontentloaded',timeout:60000});
 await new Promise(r=>setTimeout(r,40000));
 const v=await p.evaluate(()=>{ try{ const m=window.fcInstance; if(!m||!m.HEAPU32) return 'no-heap'; return {d0:m.HEAPU32[0], d1:m.HEAPU32[1], warned: globalThis.__fcAddr0Warned||0}; }catch(e){return String(e);} });
 console.log('addr0 after boot:', JSON.stringify(v));
 await b.close();
})().catch(e=>{console.error(e);process.exit(1);});
