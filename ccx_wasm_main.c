/* CalculiX as a standalone wasm module for FreeCAD-Web.
 *
 * FreeCAD's FEM workbench solves by writing an .inp and shelling out:
 *
 *     $ ccx -i <jobname>
 *     -> read <jobname>.frd / <jobname>.dat back
 *
 * There is no fork/exec in the browser, so this replaces the binary. ccx's own main()
 * is reused rather than reimplemented -- it is compiled with -Dmain=fcweb_ccx_main and
 * called with the argv it expects, so the solver follows exactly its normal path.
 *
 * Built as its own .wasm (see build-ccx-module-weh.sh) rather than linked into
 * FreeCAD.wasm: solving is not needed to boot, so it is fetched on first use.
 *
 * The JS side instantiates a FRESH module per solve. ccx keeps state in globals and
 * was written as a one-shot process; reusing an instance would carry the previous run's
 * state into the next one.
 */
#include <emscripten.h>
#include <stdio.h>

int fcweb_ccx_main(int argc, char *argv[]);   /* ccx_2.22.c, renamed at compile time */

EMSCRIPTEN_KEEPALIVE
int fcweb_ccx_run(const char *jobname)
{
    char *argv[3];
    char prog[] = "ccx";
    char flag[] = "-i";
    if (!jobname || !*jobname) {
        fprintf(stderr, "[ccx-wasm] no job name given\n");
        return 2;
    }
    argv[0] = prog;
    argv[1] = flag;
    argv[2] = (char *)jobname;
    return fcweb_ccx_main(3, argv);
}

EMSCRIPTEN_KEEPALIVE
const char *fcweb_ccx_version(void)
{
    return "2.22";
}
