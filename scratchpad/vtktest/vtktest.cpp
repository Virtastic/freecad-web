// Minimal standalone reproducer: read a .vtu with vtkXMLUnstructuredGridReader.
#include <cstdio>
#include <vtkSmartPointer.h>
#include <vtkXMLUnstructuredGridReader.h>
#include <vtkUnstructuredGrid.h>
#include <vtkDataSet.h>

int main(int argc, char** argv) {
    const char* fn = argc > 1 ? argv[1] : "test.vtu";
    printf("[T] creating reader\n"); fflush(stdout);
    auto reader = vtkSmartPointer<vtkXMLUnstructuredGridReader>::New();
    printf("[T] reader=%p\n", (void*)reader.Get()); fflush(stdout);
    reader->SetFileName(fn);
    printf("[T] before Update\n"); fflush(stdout);
    reader->Update();
    printf("[T] after Update\n"); fflush(stdout);
    vtkDataSet* ds = reader->GetOutputAsDataSet();
    printf("[T] dataset=%p points=%lld cells=%lld\n", (void*)ds,
        ds ? (long long)ds->GetNumberOfPoints() : -1,
        ds ? (long long)ds->GetNumberOfCells() : -1); fflush(stdout);
    printf("[T] OK\n"); fflush(stdout);
    return 0;
}
