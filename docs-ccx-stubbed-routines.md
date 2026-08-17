# CalculiX: the 68 routines a clean build cannot translate

Produced by `.github/workflows/build-ccx.yml` (run 31985042689), from CalculiX 2.22
upstream + `patches/ccx-wasm-automatic-array.patch`.

## What this is

f2c implements FORTRAN 77. CalculiX uses some F90, so 68 of its 977 routines fail to
translate and `build-ccx-weh.sh` **stubs** them: they compile, they link, and at run time
they do nothing. That is why a build can print `failed: 0` and still be missing
functionality, and it is the whole of the size gap against production:

    production   code section = 4,188,444
    clean CI     code section = 3,346,xxx     ~840 KB of stubs

## Why this matters more than a size number

`e_c3d.f` is the 3D element stiffness routine and `gauss.f` supplies the integration
points. Stub those and solid FEM does not work at all. Production's solver demonstrably
DOES work -- validated to under 1% against beam theory -- so the build machine has f2c
workarounds for these that were never captured into `patches/`.

That is the actual defect: `deps/` is gitignored, so those edits are invisible until
someone builds from clean. Nobody had, until 2026-08-16.

## The work list

Fix these on the build machine and capture the delta as a patch beside
`ccx-wasm-automatic-array.patch`. When the CI code section matches production's, the CI
build is trustworthy and threaded CalculiX becomes the one-flag change it was meant to be.

### Core solid/thermal FEM -- stubbing these breaks analyses
    calcmass.f
    calcstressheatfluxfem.f
    e_c3d.f
    e_c3d_cs_se.f
    e_c3d_duds.f
    e_c3d_em.f
    e_c3d_prhs.f
    e_c3d_se.f
    e_c3d_th.f
    e_c3d_u.f
    e_c3d_u1.f
    e_c3d_us3.f
    e_c3d_us45.f
    e_c3d_v1rhs.f
    e_c3d_v2rhs.f
    extrapolate.f
    extrapolate_se.f
    extrapolatecontact.f
    extrapolatefem.f
    gauss.f
    mafilldm.f
    mafilldmss.f
    mafillv1rhs.f

### Everything else
    basis.f
    beamextscheme.f
    calcenergy.f
    calcspringforc.f
    calcview.f
    cavity_refine.f
    cavityext_refine.f
    checkconstraint.f
    e_corio.f
    e_damp.f
    effectivemodalmass.f
    extendmesh.f
    gen3dfrom2d.f
    initialconditionss.f
    interpolateinface.f
    jouleheating.f
    near2d.f
    near3d.f
    objective_mass_dx.f
    objective_shapeener_dx.f
    patch.f
    printoutelem.f
    printoutface.f
    printoutfacefem.f
    printoutint.f
    printoutintfluidfem.f
    regularization_gn_c.f
    resultsem.f
    resultsmech.f
    resultsmech_matrix.f
    resultsmech_se.f
    resultsmech_u1.f
    resultsmech_us3.f
    resultsmech_us45.f
    resultstherm.f
    slavintmortar.f
    slavintpoints.f
    springstiff_n2f_th.f
    umat_ciarlet_el.f
    us3_sub.f
    us4_sub.f
    writemeshinp.f
    writetrilinos.f
    xlocal.f
    zienzhu.f

## Note on US3/US45

`e_c3d_us3`, `e_c3d_us45`, `resultsmech_us3/45`, `us3_sub`, `us4_sub` are the *user*
shell elements. BUILD-WEH.md records that FreeCAD never emits them, so those are the
one group that can stay stubbed.
