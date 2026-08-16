const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl=ms=>new Promise(r=>setTimeout(r,ms));
const runG=(p,c)=>p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);(window.fcRunPy||((mm,pp)=>{mm._fcweb_run_python(pp);mm._free(pp);}))(m,q);return 1;},c);
const pw=async(p,mk,ms)=>{const t0=Date.now();while(Date.now()-t0<ms){try{if(await p.evaluate((k)=>document.getElementById('log').textContent.includes(k),mk))return true;}catch(e){}await sl(400);}return false;};
const click=async(p,l)=>{const bb=await p.evaluate((x)=>{const bs=[...document.querySelectorAll('button')].filter(b=>b.textContent.trim().toLowerCase()===x);if(!bs.length)return null;const r=bs[0].getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};},l);if(bb){await p.mouse.click(bb.x,bb.y);return true;}return false;};
(async()=>{
 let perr=0,crash=0,R=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=1400,900'],protocolTimeout:1200000,userDataDir:'/tmp/fc-regression'});
 const p=(await b.pages())[0];
 p.on('pageerror',e=>{perr++;R.push('  PAGEERR '+String(e.message||e).slice(0,120));});
 p.on('console',m=>{const t=m.text();if(/unreachable|null function|Aborted|RuntimeError/i.test(t)){crash++;R.push('  CRASH '+t.slice(0,120));}});
 await p.goto('http://localhost:8792/index.html',{waitUntil:'domcontentloaded',timeout:200000});
 const t0=Date.now();while(Date.now()-t0<200000){if(await p.evaluate(()=>!!(window.fcInstance&&window.fcInstance._malloc)))break;await sl(500);}
 await runG(p,"import sys\nsys.__stderr__.write('RDY\\n')"); await pw(p,'RDY',180000); await sl(8000);
 const bootErr=perr;
 let log=await p.evaluate(()=>document.getElementById('log').textContent);
 R.push('BOOT errs='+bootErr+'  '+((log.match(/PyEM_CountArgs selfcheck[^\n]*/)||['selfcheck MISSING'])[0]));
 // workbenches
 const WBS=['PartWorkbench','PartDesignWorkbench','SketcherWorkbench','DraftWorkbench','MeshWorkbench','TechDrawWorkbench','SpreadsheetWorkbench','FemWorkbench'];
 let wbOk=0;
 for(const wb of WBS){const before=perr;
  await runG(p,"import FreeCADGui as Gui,sys\ntry:\n Gui.activateWorkbench('"+wb+"')\n sys.__stderr__.write('WB_"+wb+" ok\\n')\nexcept Exception as e:\n sys.__stderr__.write('WB_"+wb+" ERR %r\\n'%e)");
  if(await pw(p,'WB_'+wb,45000) && perr===before) wbOk++;
  await sl(500);}
 R.push('WORKBENCHES '+wbOk+'/'+WBS.length);
 // examples
 await runG(p,fs.readFileSync('scratchpad/regpy/reg_examples.py','utf8')); await pw(p,'EX-AVAIL',20000);
 log=await p.evaluate(()=>document.getElementById('log').textContent);
 let avail=[];try{avail=JSON.parse(((log.match(/EX-AVAIL (\[.*\])/)||[])[1]||'[]').replace(/'/g,'"'));}catch(e){}
 R.push('EXAMPLES available='+avail.length);
 let exOk=0;
 for(const ex of avail){const before=perr;
  await runG(p,["import sys,time,FreeCAD as App","try:"," t=time.time(); d=App.openDocument('/freecad/share/examples/"+ex+".FCStd')"," sys.__stderr__.write('EX_"+ex+" objs=%d vis=%d dt=%.1f\\n'%(len(d.Objects),sum(1 for o in d.Objects if o.Visibility),time.time()-t))","except Exception as e:"," sys.__stderr__.write('EX_"+ex+" ERR %r\\n'%e)"].join('\n'));
  const ok=await pw(p,'EX_'+ex,150000);
  log=await p.evaluate(()=>document.getElementById('log').textContent);
  const line=(log.match(new RegExp('EX_'+ex+'[^\\n]*'))||['(no marker)'])[0];
  R.push('  '+(ok?'OK  ':'SLOW')+' '+line.replace(/^\{[\d.]+s\}\s*/,''));
  if(ok&&perr===before) exOk++;
  await sl(1500);}
 R.push('EXAMPLES ok='+exOk+'/'+avail.length);
 // dialogs
 // Native Qt dialog: the HTML bridge is gone, so the button lives on the canvas.
 // Publish its position from Qt, click the real pixels, and require the REAL return value.
 await runG(p,["import sys","from PySide6 import QtWidgets, QtCore",
   "mb=QtWidgets.QMessageBox(); mb.setWindowTitle('R'); mb.setText('ok?')",
   "mb.setStandardButtons(QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)",
   "mb.show(); QtWidgets.QApplication.processEvents()",
   "for _b in mb.buttons():",
   "    _c=_b.mapToGlobal(QtCore.QPoint(_b.width()//2,_b.height()//2))",
   "    sys.__stderr__.write('DLGBTN %s %d %d\\n'%(_b.text().replace('&',''),_c.x(),_c.y()))",
   "sys.__stderr__.flush()",
   "sys.__stderr__.write('DLG=%d\\n'%int(QtWidgets.QDialog.exec(mb))); sys.__stderr__.flush()"].join('\n'));
 await sl(2500);
 log=await p.evaluate(()=>document.getElementById('log').textContent);
 const bm=/DLGBTN Yes (\d+) (\d+)/.exec(log);
 let clicked=false;
 if(bm){ await p.mouse.click(+bm[1],+bm[2]); clicked=true; }
 await pw(p,'DLG=',15000);
 log=await p.evaluate(()=>document.getElementById('log').textContent);
 R.push('DIALOG clicked='+clicked+' '+((log.match(/DLG=\d+/)||['?'])[0])+' (16384=Yes)');
 // workflow
 await runG(p,["import sys,FreeCAD as App,Part","d=App.newDocument('RG')","b=d.addObject('Part::Box','B');c=d.addObject('Part::Cylinder','C')","x=d.addObject('Part::Cut','X');x.Base=b;x.Tool=c;d.recompute()","import Mesh,MeshPart","m=MeshPart.meshFromShape(Shape=x.Shape,LinearDeflection=0.5)","d.saveAs('/tmp/rg.FCStd'); App.closeDocument('RG')","d2=App.openDocument('/tmp/rg.FCStd')","import Import","Import.export([d2.getObject('X')],'/tmp/rg.step')","import os","sys.__stderr__.write('WF vol=%.0f facets=%d step=%d\\n'%(d2.getObject('X').Shape.Volume,m.CountFacets,os.path.getsize('/tmp/rg.step')))"].join('\n'));
 const wfOk=await pw(p,'WF ',90000);
 log=await p.evaluate(()=>document.getElementById('log').textContent);
 R.push('WORKFLOW '+(wfOk?(log.match(/WF [^\n]*/)||[''])[0]:'FAILED'));
 // render proof
 await runG(p,["import FreeCAD as App,FreeCADGui as Gui","d=App.newDocument('RV');b=d.addObject('Part::Box','B');d.recompute()","b.ViewObject.ShapeColor=(0.9,0.2,0.2)","Gui.activeDocument().activeView().viewIsometric();Gui.SendMsgToActiveView('ViewFit')","import sys;sys.__stderr__.write('RENDER ok\\n')"].join('\n'));
 await pw(p,'RENDER',30000); await sl(4000);
 await p.screenshot({path:'/tmp/reg-render.png'});
 await runG(p,"import sys\nsys.__stderr__.write('ALIVE\\n')");
 R.push('ALIVE='+await pw(p,'ALIVE',15000));
 R.push('TOTAL pageErrs='+perr+' crashes='+crash);
 fs.writeFileSync('/tmp/regression.txt',R.join('\n'));
 console.log(R.join('\n'));
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/regression.txt','DRIVER-ERR '+String(e).slice(0,300));process.exit(0);});
