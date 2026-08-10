const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(400);}return false;};
const cam=async(p,tag)=>{await runG(p,["import FreeCADGui as Gui,sys","c=Gui.activeDocument().activeView().getCamera()","q=[l.strip() for l in c.splitlines() if 'position' in l or 'orientation' in l]","sys.__stderr__.write('"+tag+" %s\\n'%(' ; '.join(q[:2])))"].join('\n'));
  await pw(p,tag,20000);const log=await p.evaluate(()=>document.getElementById('log').textContent);
  return ((log.match(new RegExp(tag+'[^\\n]*'))||[''])[0]).replace(/^\{[\d.]+s\}\s*/,'').replace(tag+' ','');};
(async()=>{
 const R=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=1300,900'],protocolTimeout:900000,userDataDir:'/tmp/fc-dragctl'});
 const p=(await b.pages())[0];
 await p.goto('http://localhost:8799/index.html',{waitUntil:'domcontentloaded',timeout:240000});
 const t0=Date.now();while(Date.now()-t0<240000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',200000); await sl(7000);
 await runG(p,["import FreeCAD as App,FreeCADGui as Gui,sys","d=App.newDocument('C')","d.addObject('Part::Box','B');d.recompute()","Gui.activeDocument().activeView().viewIsometric();Gui.SendMsgToActiveView('ViewFit')","sys.__stderr__.write('READY\\n')"].join('\n'));
 await pw(p,'READY',60000); await sl(3000);

 const c=await p.evaluate(()=>{const h=document.getElementById('qt-shadow-container');const sr=h&&h.shadowRoot;const cv=sr&&sr.querySelector('canvas');const r=(cv||document.body).getBoundingClientRect();return {x:r.x+r.width*0.55,y:r.y+r.height*0.5};});
 R.push('canvas centre '+JSON.stringify(c));

 // CONTROL A: real trusted mouse drag via puppeteer (middle button = pan in FreeCAD)
 const a0=await cam(p,'A0');
 await p.mouse.move(c.x,c.y); await p.mouse.down({button:'middle'});
 for(let i=1;i<=15;i++){ await p.mouse.move(c.x+i*8,c.y+i*4); await sl(25); }
 await p.mouse.up({button:'middle'});
 await sl(1200);
 const a1=await cam(p,'A1');
 R.push('REAL middle-drag : '+(a0===a1?'NO CHANGE':'MOVED'));

 // CONTROL B: real left drag (rotate in some nav styles)
 const b0=await cam(p,'B0');
 await p.mouse.move(c.x,c.y); await p.mouse.down({button:'left'});
 for(let i=1;i<=15;i++){ await p.mouse.move(c.x+i*8,c.y-i*4); await sl(25); }
 await p.mouse.up({button:'left'});
 await sl(1200);
 const b1=await cam(p,'B1');
 R.push('REAL left-drag   : '+(b0===b1?'NO CHANGE':'MOVED'));

 // CONTROL C: real wheel (zoom) — simplest possible interaction
 const w0=await cam(p,'W0');
 await p.mouse.move(c.x,c.y); await p.mouse.wheel({deltaY:-300}); await sl(1200);
 const w1=await cam(p,'W1');
 R.push('REAL wheel       : '+(w0===w1?'NO CHANGE':'MOVED'));
 R.push('  A0='+a0.slice(0,60)); R.push('  A1='+a1.slice(0,60));
 fs.writeFileSync('/tmp/dragctl.txt',R.join('\n')); console.log(R.join('\n'));
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/dragctl.txt','DRIVER-ERR '+String(e).slice(0,250));process.exit(0);});
