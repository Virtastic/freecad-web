const puppeteer=require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:'new',args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--enable-features=SharedArrayBuffer','--use-gl=angle','--use-angle=swiftshader','--ignore-gpu-blocklist','--window-size=1400,900']});
 const p=await b.newPage(); await p.setViewport({width:1400,height:900});
 const errs=[]; p.on('pageerror',e=>errs.push('[PAGEERR] '+e.message.slice(0,120)));
 await p.goto('http://localhost:8791/',{waitUntil:'domcontentloaded',timeout:60000});  // ROOT URL like the user
 let ok=false;
 try{ await p.waitForFunction(()=>window.fcInstance&&window.fcInstance._malloc,{timeout:90000,polling:1000}); ok=true; }catch(e){}
 await new Promise(r=>setTimeout(r,8000));
 const log=await p.evaluate(()=>document.getElementById('log').innerText).catch(()=>'');
 await p.screenshot({path:'/tmp/fc-roottest.png'});
 console.log('ROOT fcInstance-ready='+ok);
 console.log('log tail:\n'+log.split('\n').filter(l=>/FreeCAD loaded|Running|remaining=0|warmup|Failed to fetch|qtLoad failed|error/i.test(l)).slice(-8).join('\n'));
 if(errs.length) console.log('ERRORS:\n'+errs.slice(-5).join('\n'));
 await b.close();
})().catch(e=>{console.error('ERR',e);process.exit(1);});
