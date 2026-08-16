const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(400);}return false;};
(async()=>{
 const R=[]; let perr=0;
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,
   args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=900,1200'],
   protocolTimeout:900000,userDataDir:'/tmp/fc-touch2'});
 const p=(await b.pages())[0]; p.on('pageerror',()=>perr++);
 // emulate a real tablet: touch-capable, device pixel ratio, mobile UA
 const cdp=await p.target().createCDPSession();
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:820,height:1180,deviceScaleFactor:2,mobile:true,hasTouch:true});
 await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5});
 await p.goto('http://localhost:8799/index.html',{waitUntil:'domcontentloaded',timeout:240000});
 const t0=Date.now();while(Date.now()-t0<240000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',200000); await sl(7000);

 R.push('viewport meta applied: '+await p.evaluate(()=>{const m=document.querySelector('meta[name=viewport]');return m?m.content.slice(0,40):'MISSING';}));
 R.push('touch handlers attached: '+await p.evaluate(()=>('ontouchstart' in window)));

 // put a box on screen and fit
 await runG(p,["import FreeCAD as App,FreeCADGui as Gui,sys","d=App.newDocument('T')","d.addObject('Part::Box','B');d.recompute()","Gui.activeDocument().activeView().viewIsometric();Gui.SendMsgToActiveView('ViewFit')","sys.__stderr__.write('BOXREADY\\n')"].join('\n'));
 await pw(p,'BOXREADY',60000); await sl(3000);
 const cam0 = await p.evaluate(()=>null); // camera read via python below
 await runG(p,["import FreeCADGui as Gui,sys","c=Gui.activeDocument().activeView().getCamera()","p=[l.strip() for l in c.splitlines() if 'position' in l]","sys.__stderr__.write('CAM0 %s\\n'%(p[0] if p else '?'))"].join('\n'));
 await pw(p,'CAM0',20000);

 // ---- 1-finger drag == rotate ----
 const box=await p.evaluate(()=>{const e=document.getElementById('screen');const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:box.x,y:box.y}]});
 for(let i=1;i<=12;i++){ await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:box.x+i*9,y:box.y+i*5}]}); await sl(25); }
 await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 await sl(1200);
 await runG(p,["import FreeCADGui as Gui,sys","c=Gui.activeDocument().activeView().getCamera()","p=[l.strip() for l in c.splitlines() if 'position' in l]","sys.__stderr__.write('CAM1 %s\\n'%(p[0] if p else '?'))"].join('\n'));
 await pw(p,'CAM1',20000);

 // ---- pinch == zoom ----
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:box.x-60,y:box.y,id:1},{x:box.x+60,y:box.y,id:2}]});
 for(let i=1;i<=10;i++){ const d=60-i*4; await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:box.x-d,y:box.y,id:1},{x:box.x+d,y:box.y,id:2}]}); await sl(30); }
 await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 await sl(1200);
 await runG(p,["import FreeCADGui as Gui,sys","c=Gui.activeDocument().activeView().getCamera()","h=[l.strip() for l in c.splitlines() if 'height' in l or 'position' in l]","sys.__stderr__.write('CAM2 %s\\n'%(' | '.join(h[:2]) if h else '?'))"].join('\n'));
 await pw(p,'CAM2',20000);

 await p.screenshot({path:'/tmp/touch-tablet.png'});
 const log=await p.evaluate(()=>document.getElementById('log').textContent);
 for(const k of ['CAM0','CAM1','CAM2']) R.push('  '+((log.match(new RegExp(k+'[^\\n]*'))||[k+' ?'])[0]).replace(/^\{[\d.]+s\}\s*/,''));
 R.push('pageErrs='+perr);
 fs.writeFileSync('/tmp/touch2.txt',R.join('\n')); console.log(R.join('\n'));
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/touch2.txt','DRIVER-ERR '+String(e).slice(0,250));process.exit(0);});
