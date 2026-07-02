// Spike (b): prebuilt opencascade.js smoke test, loaded the CommonJS way
// (the emscripten module is Node/UMD-style; ESM default import mis-parses it).
const path = require("path");
const fs = require("fs");
const factory = require("opencascade.js/dist/opencascade.wasm.js");
const wasmPath = path.join(__dirname, "node_modules/opencascade.js/dist/opencascade.wasm.wasm");

(async () => {
  const oc = await factory({ locateFile: (p) => (p.endsWith(".wasm") ? wasmPath : p) });
  console.log("[spike-b] OpenCASCADE initialized");

  const box = new oc.BRepPrimAPI_MakeBox_2(10, 10, 10).Shape();
  const sphere = new oc.BRepPrimAPI_MakeSphere_1(7).Shape();

  let shape = box;
  try {
    const fuse = new oc.BRepAlgoAPI_Fuse_3(box, sphere, new oc.Message_ProgressRange_1());
    fuse.Build(new oc.Message_ProgressRange_1());
    shape = fuse.Shape();
    console.log("[spike-b] boolean fuse OK");
  } catch (e) {
    console.log("[spike-b] fuse overload mismatch, using box:", e.message ?? e);
  }

  new oc.BRepMesh_IncrementalMesh_2(shape, 0.1, false, 0.5, false);

  let tris = 0;
  const exp = new oc.TopExp_Explorer_2(shape, oc.TopAbs_ShapeEnum.TopAbs_FACE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
  for (; exp.More(); exp.Next()) {
    const face = oc.TopoDS.Face_1(exp.Current());
    const loc = new oc.TopLoc_Location_1();
    const tri = oc.BRep_Tool.Triangulation(face, loc, 0);
    if (!tri.IsNull()) tris += tri.get().NbTriangles();
  }
  console.log("[spike-b] triangle count =", tris);

  const writer = new oc.STEPControl_Writer_1();
  writer.Transfer(shape, oc.STEPControl_StepModelType.STEPControl_AsIs, true, new oc.Message_ProgressRange_1());
  writer.Write("out.step");
  const ok = fs.existsSync("out.step") && fs.statSync("out.step").size > 0;
  console.log("[spike-b] out.step written:", ok, ok ? fs.statSync("out.step").size + " bytes" : "");
  console.log(tris > 0 && ok ? "[spike-b] PASS" : "[spike-b] FAIL");
})().catch((e) => { console.error("[spike-b] ERROR:", e.message ?? e); process.exit(1); });
