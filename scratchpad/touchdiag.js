const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(400);}return false;};
const cam=async(p,tag)=>{await runG(p,["import FreeCADGui as Gui,sys","c=Gui.activeDocument().activeView().getCamera()","q=[l.strip() for l in c.splitlines() if 'position' in l]","sys.__stderr__.write('"+tag+" %s\\n'%(q[0] if q else '?'))"].join('\n'));await pw(p,tag,20000);
  const log=await p.evaluate(()=>document.getElementById('log').textContent);
  return ((log.match(new RegExp(tag+'[^\\n]*'))||[''])[0]).replace(/^\{[\d.]+s\}\s*/,'');};
(async()=>{
 const R=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=900,1200'],protocolTimeout:900000,userDataDir:'/tmp/fc-touchdiag'});
 const p=(await b.pages())[0];
 const cdp=await p.target().createCDPSession();
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:820,height:1180,deviceScaleFactor:2,mobile:true,hasTouch:true});
 await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5});
 await p.goto('http://localhost:8799/index.html',{waitUntil:'domcontentloaded',timeout:240000});
 const t0=Date.now();while(Date.now()-t0<240000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',200000); await sl(7000);
 await runG(p,["import FreeCAD as App,FreeCADGui as Gui,sys","d=App.newDocument('T')","d.addObject('Part::Box','B');d.recompute()","Gui.activeDocument().activeView().viewIsometric();Gui.SendMsgToActiveView('ViewFit')","sys.__stderr__.write('BOXREADY\\n')"].join('\n'));
 await pw(p,'BOXREADY',60000); await sl(3000);

 // where does Qt actually live, and what does it listen to?
 R.push('DOM: '+JSON.stringify(await p.evaluate(()=>{
   const host=document.getElementById('qt-shadow-container');
   const sr=host&&host.shadowRoot;
   const canv=(sr?sr.querySelector('canvas'):null)||document.querySelector('canvas');
   const scr=document.getElementById('screen');
   return {hasShadowHost:!!host, hasShadowRoot:!!sr, canvasFound:!!canv,
           canvasInShadow: !!(sr&&sr.querySelector('canvas')),
           canvasId: canv?(canv.id||'(none)'):null,
           screenContainsCanvas: !!(scr&&canv&&scr.contains(canv))};
 })));

 // drag with MY handler active
 const c0=await cam(p,'D0');
 const box=await p.evaluate(()=>{const e=document.getElementById('screen');const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
 const drag=async()=>{await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:box.x,y:box.y}]});
   for(let i=1;i<=12;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:box.x+i*10,y:box.y+i*6}]});await sl(30);}
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await sl(1200);};
 await drag(); const c1=await cam(p,'D1');
 R.push('with shim   : '+(c0===c1.replace('D1','D0')?'NO CHANGE':'moved')+'   '+c1);

 // now REMOVE my handler by reloading with it disabled, and let Qt see raw touch
 await p.evaluate(()=>{ window.__fcTouchDisabled = true;
   const e=document.getElementById('screen'); const clone=e.cloneNode(true); e.parentNode.replaceChild(clone,e); });
 R.push('(shim listeners detached by replacing #screen)');
 const c2=await cam(p,'D2'); await drag(); const c3=await cam(p,'D3');
 R.push('without shim: '+(c2.replace('D2','X')===c3.replace('D3','X')?'NO CHANGE':'moved')+'   '+c3);

 fs.writeFileSync('/tmp/touchdiag.txt',R.join('\n')); console.log(R.join('\n'));
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/touchdiag.txt','DRIVER-ERR '+String(e).slice(0,250));process.exit(0);});
