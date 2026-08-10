// gmsh as a standalone wasm module for FreeCAD-Web.
//
// FreeCAD's FEM workbench meshes by writing two files and shelling out:
//
//     <Part>_Geometry.brep      the geometry
//     shape2mesh.geo            a script that Merge"s the brep, sets the meshing
//                               parameters, runs `Mesh <dim>;` and ends with
//                               `Save "<name>.unv";`
//     $ gmsh -v 4 - shape2mesh.geo
//     -> read <name>.unv back with Fem.read()
//
// There is no fork/exec in the browser, so this replaces the binary. Everything the
// mesher needs is already inside the .geo — including the Mesh and Save commands — so
// running it is literally "parse the script and let it execute", which is exactly what
// gmsh::open() does for a .geo. That keeps us on gmsh's own supported entry point
// instead of reimplementing its command line.
//
// Built as its own .wasm (see configure-gmsh-weh.sh + build-gmsh-weh.sh) rather than
// linked into FreeCAD.wasm: the main binary is already ~152 MB, and meshing is not
// needed to boot, so this is fetched on first use.

#include <emscripten.h>

#include <cstdio>
#include <string>

#include <gmsh.h>

extern "C" {

// Run a .geo script that is already present in this module's FS. Returns 0 on success.
// The script's own `Save` line decides where the mesh lands; the JS side then copies
// that file back into FreeCAD's FS.
EMSCRIPTEN_KEEPALIVE
int fcweb_gmsh_run(const char* geoPath, int verbosity)
{
    if (!geoPath || !*geoPath) {
        std::fprintf(stderr, "[gmsh-wasm] no .geo path given\n");
        return 2;
    }
    try {
        gmsh::initialize();
        gmsh::option::setNumber("General.Terminal", 1);
        gmsh::option::setNumber("General.Verbosity", verbosity > 0 ? verbosity : 4);
        // No display, and never try to pop the GUI or write config files into $HOME.
        gmsh::option::setNumber("General.AbortOnError", 0);
        gmsh::option::setNumber("General.SaveOptions", 0);
        gmsh::option::setNumber("Mesh.Binary", 0);

        // Executes the script: Merge of the .brep, the meshing options, `Mesh <dim>;`
        // and the trailing `Save "...unv";`.
        gmsh::open(geoPath);

        gmsh::finalize();
        return 0;
    }
    catch (const std::exception& e) {
        std::fprintf(stderr, "[gmsh-wasm] %s\n", e.what());
        try { gmsh::finalize(); } catch (...) {}
        return 1;
    }
    catch (...) {
        std::fprintf(stderr, "[gmsh-wasm] unknown error\n");
        try { gmsh::finalize(); } catch (...) {}
        return 1;
    }
}

// Reported by FreeCAD's preferences page / version probe (it used to run `gmsh --info`).
EMSCRIPTEN_KEEPALIVE
const char* fcweb_gmsh_version()
{
    static std::string v;
    if (v.empty()) {
        try {
            gmsh::initialize();
            gmsh::option::getString("General.Version", v);
            gmsh::finalize();
        }
        catch (...) { v = "unknown"; }
        if (v.empty()) { v = "unknown"; }
    }
    return v.c_str();
}

}  // extern "C"
