const puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const run=async(p,c)=>{await p.evaluate((c)=>{const m=window.fcInstance;const n=new TextEncoder().encode(c).length+1;const q=m._malloc(n);m.stringToUTF8(c,q,n);m._fcweb_run_python(q);m._free(q);},c);};
const wait=async(p,mk,ms)=>{try{await p.waitForFunction((k)=>document.getElementById('log').textContent.includes(k),{timeout:ms,polling:500},mk);return true;}catch(e){return false;}};
const FILES=[
 '/freecad/share/examples/PartDesignExample.FCStd',
 '/freecad/share/examples/EngineBlock.FCStd',
 '/freecad/share/examples/AssemblyExample.FCStd',
 '/freecad/share/examples/draft_test_objects.FCStd',
 '/freecad/share/examples/FEMExample.FCStd',
 '/freecad/share/examples/BIMExample.FCStd',
 '/freecad/share/examples/Schenkel.stp',
];
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,
  args:['--no-sandbox','--use-gl=angle','--use-angle=metal','--enable-features=SharedArrayBuffer','--window-size=1400,900'],
  protocolTimeout:300000,userDataDir:'/tmp/fc-sm-profile'});
 const p=(await b.pages())[0];
 let errs=[];
 p.on('pageerror',e=>errs.push('PAGEERR '+String(e).slice(0,100)));
 p.on('console',m=>{if(m.type()==='error') errs.push('CERR '+m.text().slice(0,100));});
 await p.goto('http://localhost:8799/index.html',{waitUntil:'domcontentloaded',timeout:150000});
 await wait(p,'Wizard shaft',240000); await new Promise(r=>setTimeout(r,4000));
 console.log('BOOTED\n');
 for(const f of FILES){
   const name=f.split('/').pop();
   errs=[];
   const tag='S_'+name.replace(/[^A-Za-z0-9]/g,'');
   const isStep=/\.(stp|step)$/i.test(f);
   const py = isStep ? [
     "import FreeCAD,Import,FreeCADGui as Gui,sys,time",
     "t=time.time()",
     "d=FreeCAD.newDocument('"+tag+"')",
     "Import.insert("+JSON.stringify(f)+",'"+tag+"')",
     "d.recompute()",
     "objs=[o for o in d.Objects if hasattr(o,'Shape')]",
     "faces=sum(len(o.Shape.Faces) for o in objs)",
     "err=[o.Name for o in d.Objects if hasattr(o,'State') and 'Invalid' in o.State]",
     "Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView('ViewFit')",
     "sys.__stderr__.write('"+tag+"-OK objs=%d faces=%d invalid=%d t=%.1f\\n'%(len(objs),faces,len(err),time.time()-t))"
   ] : [
     "import FreeCAD,FreeCADGui as Gui,sys,time",
     "t=time.time()",
     "d=FreeCAD.openDocument("+JSON.stringify(f)+")",
     "d.recompute()",
     "objs=d.Objects",
     "shp=[]",
     "for o in objs:",
     "  try:",
     "    sh=getattr(o,'Shape',None)",
     "    if sh is not None and getattr(sh,'Faces',None) is not None: shp.append(o)",
     "  except Exception: pass",
     "faces=0",
     "for o in shp:",
     "  try: faces+=len(o.Shape.Faces)",
     "  except Exception: pass",
     "err=[o.Name for o in objs if hasattr(o,'State') and ('Invalid' in o.State or 'Error' in o.State)]",
     "try:",
     "  Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView('ViewFit')",
     "except Exception as e: sys.__stderr__.write('viewerr:%s\\n'%e)",
     "sys.__stderr__.write('"+tag+"-OK objs=%d faces=%d invalid=%d t=%.1f\\n'%(len(objs),faces,len(err),time.time()-t))",
     "if err: sys.__stderr__.write('"+tag+"-INVALID %s\\n'%err[:6])"
   ];
   await run(p, py.join('\n')).catch(e=>errs.push('RUN-THREW '+String(e).slice(0,60)));
   const ok=await wait(p,tag+'-OK',180000);
   await new Promise(r=>setTimeout(r,3500));
   const line=await p.evaluate((t)=>{const m=document.getElementById('log').textContent.match(new RegExp(t+'-OK[^\\n]*'));return m?m[0]:null;},tag).catch(()=>null);
   const inv=await p.evaluate((t)=>{const m=document.getElementById('log').textContent.match(new RegExp(t+'-INVALID[^\\n]*'));return m?m[0]:null;},tag).catch(()=>null);
   // does it actually render pixels?
   const px=await p.evaluate(()=>{
     const cs=[...document.querySelectorAll('canvas')]; let best=null,n=0;
     for(const c of cs){ if(c.width*c.height>n){n=c.width*c.height;best=c;} }
     if(!best) return 0;
     const t=document.createElement('canvas'); t.width=best.width;t.height=best.height;
     const cx=t.getContext('2d'); cx.drawImage(best,0,0);
     let d; try{d=cx.getImageData(0,0,t.width,t.height).data;}catch(e){return -1;}
     const bk={}; for(let i=0;i<d.length;i+=4){ if(d[i+3]<10)continue;
       const l=Math.round((0.299*d[i]+0.587*d[i+1]+0.114*d[i+2])/32)*32; bk[l]=(bk[l]||0)+1; }
     return Object.keys(bk).length;
   }).catch(()=>-1);
   const uniq=[...new Set(errs)].filter(e=>!/GL emulation/.test(e));
   console.log((ok?'[PASS]':'[FAIL]')+' '+name);
   console.log('        '+(line||'(no marker — load failed/hung)'));
   if(inv) console.log('        !! '+inv);
   console.log('        shades='+px+(px<2?'  <-- NOT RENDERING':'')+'  errors='+uniq.length+(uniq.length?(' :: '+uniq.slice(0,2).join(' | ')):''));
   await p.screenshot({path:'/tmp/sample-'+name.replace(/\W/g,'_')+'.png'}).catch(()=>{});
 }
 console.log('\nSAMPLES-DONE');
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{console.log('OUTER '+String(e).slice(0,140));process.exit(0);});
