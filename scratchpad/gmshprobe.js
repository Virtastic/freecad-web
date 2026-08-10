const puppeteer=require('puppeteer-core');const fs=require('fs');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const R=[];
 const b=await puppeteer.launch({executablePath:CHROME,headless:false,defaultViewport:null,args:['--no-sandbox','--enable-features=SharedArrayBuffer','--window-size=900,700'],protocolTimeout:900000,userDataDir:'/tmp/fc-gmshprobe'});
 const p=(await b.pages())[0];
 p.on('console',m=>{const t=m.text(); if(/gmsh|error|Error|abort/i.test(t)) R.push('  con: '+t.slice(0,160));});
 p.on('pageerror',e=>R.push('  PAGEERR '+String(e.message||e).slice(0,160)));
 // bare page on the same origin (COOP/COEP) so we can load gmsh.js standalone
 await p.goto('http://localhost:8799/probe-blank.html',{waitUntil:'domcontentloaded',timeout:120000}).catch(()=>{});
 const res=await p.evaluate(async()=>{
   const geo = await (await fetch('/probe.geo')).text();
   await new Promise((res,rej)=>{const s=document.createElement('script');s.src='/gmsh.js';s.onload=res;s.onerror=()=>rej(new Error('fetch gmsh.js failed'));document.head.appendChild(s);});
   if (typeof GmshModule!=='function') return {err:'GmshModule missing'};
   const t0=performance.now();
   const G = await GmshModule();
   const loaded=performance.now()-t0;
   try{G.FS.mkdir('/work');}catch(e){}
   G.FS.writeFile('/work/probe.geo', new TextEncoder().encode(geo));
   try{G.FS.chdir('/work');}catch(e){}
   const t1=performance.now();
   const rc = G.ccall('fcweb_gmsh_run','number',['string','number'],['/work/probe.geo',2]);
   const meshed=performance.now()-t1;
   let unv=null; try{ unv=G.FS.readFile('/work/probe.unv'); }catch(e){}
   let ver=null; try{ ver=G.ccall('fcweb_gmsh_version','string',[],[]); }catch(e){}
   return {rc, loadedMs:Math.round(loaded), meshedMs:Math.round(meshed), unvBytes: unv?unv.length:0, ver};
 }).catch(e=>({err:String(e).slice(0,200)}));
 R.unshift('RESULT '+JSON.stringify(res));
 fs.writeFileSync('/tmp/gmshprobe.txt',R.join('\n')); console.log(R.join('\n'));
 await b.close().catch(()=>{}); process.exit(0);
})().catch(e=>{fs.writeFileSync('/tmp/gmshprobe.txt','DRIVER-ERR '+String(e).slice(0,200));process.exit(0);});
