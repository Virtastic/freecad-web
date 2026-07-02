// G1: authoritative OCCT-in-wasm proof against our OWN static libTK*.a.
// box(10) minus sphere(7) -> tessellate -> count triangles -> write STEP.
// Built with em++ and run under node (NODERAWFS so STEP lands on the real FS).
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopLoc_Location.hxx>
#include <Poly_Triangulation.hxx>
#include <STEPControl_Writer.hxx>
#include <gp_Pnt.hxx>
#include <cstdio>

int main()
{
  // Solids.
  TopoDS_Shape box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape();
  TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 7.0).Shape();

  // Boolean cut (box - sphere).
  TopoDS_Shape cut = BRepAlgoAPI_Cut(box, sphere).Shape();
  std::printf("[G1] boolean cut built\n");

  // Tessellate.
  BRepMesh_IncrementalMesh mesher(cut, 0.1);
  mesher.Perform();
  std::printf("[G1] meshed, done=%d\n", (int)mesher.IsDone());

  // Count triangles.
  int tris = 0;
  for (TopExp_Explorer ex(cut, TopAbs_FACE); ex.More(); ex.Next())
  {
    TopLoc_Location loc;
    Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(TopoDS::Face(ex.Current()), loc);
    if (!tri.IsNull())
      tris += tri->NbTriangles();
  }
  std::printf("[G1] triangle count = %d\n", tris);

  // STEP export.
  STEPControl_Writer writer;
  writer.Transfer(cut, STEPControl_AsIs);
  IFSelect_ReturnStatus st = writer.Write("/tmp/out.step");
  std::printf("[G1] STEP write status = %d (1=done)\n", (int)st);

  bool ok = (tris > 0) && (st == IFSelect_RetDone);
  std::printf("%s\n", ok ? "[G1] PASS" : "[G1] FAIL");
  return ok ? 0 : 1;
}
