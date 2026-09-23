// SPDX-License-Identifier: LGPL-2.1-or-later
// A 3D mouse (SpaceMouse and friends) in the browser: WebHID in, FreeCAD's own events out.
//
// Desktop FreeCAD has one backend per OS under src/Gui/3Dconnexion/, and every one of them
// ends the same way: mark the device present, then hand six axis values to
// GUIApplicationNativeEventAware::postMotionEvent (button changes to postButtonEvent).
// From there it is all upstream: importSettings() applies the user's Spaceball Motion
// preferences, the event goes to the focus widget, and View3DInventorViewer and the
// navigation styles move the camera.
//
// The browser cannot run any of those backends, but it can read the device's raw HID
// reports (WebHID), which is exactly what the Windows backend reads. freecad-gui.html
// parses the reports the way GuiNativeEventWin32.cpp does and calls these three exports.
// Nothing here reimplements navigation; it only replaces the OS layer.
//
// Exported by EMSCRIPTEN_KEEPALIVE, so the link needs the object but no flag changes.
// Called from the page's main thread; posting an event never suspends.

#include <emscripten/emscripten.h>

#include <cstdint>
#include <vector>

#include "Gui/GuiApplicationNativeEventAware.h"

namespace
{
Gui::GUIApplicationNativeEventAware* app()
{
    return qobject_cast<Gui::GUIApplicationNativeEventAware*>(QCoreApplication::instance());
}
}  // namespace

extern "C" {

// The device was opened (1) or went away (0). Desktop backends call setSpaceballPresent
// when they detect a device; the Spaceball Buttons/Motion pages read it.
EMSCRIPTEN_KEEPALIVE void fcweb_spaceball_present(int present)
{
    if (auto a = app()) {
        a->setSpaceballPresent(present != 0);
    }
}

// Translations then rotations, already in FreeCAD's axis convention.
EMSCRIPTEN_KEEPALIVE void fcweb_spaceball_motion(int tx, int ty, int tz, int rx, int ry, int rz)
{
    if (auto a = app()) {
        a->postMotionEvent({tx, ty, tz, rx, ry, rz});
    }
}

EMSCRIPTEN_KEEPALIVE void fcweb_spaceball_button(int number, int pressed)
{
    if (auto a = app()) {
        a->postButtonEvent(number, pressed);
    }
}
}

// ---- navlib: the 3Dconnexion driver path ------------------------------------------------
//
// With 3Dconnexion's driver (3DxWare) installed, the driver owns the device and WebHID gets
// nothing. Desktop FreeCAD then talks to the driver's navlib (src/Gui/3Dconnexion/navlib/),
// which drives the camera by reading and writing a fixed set of properties. The browser
// reaches the same navlib through 3Dconnexion's JavaScript client; these exports answer its
// property reads and writes for the active 3D view, ported from NavlibNavigation.cpp and
// NavlibPivot.cpp (3D view only; the 2D graphics-view branches have no web counterpart).
//
// The JavaScript client calls its getters synchronously, so this cannot go through the
// Python bridge. Scalars only across the boundary: a read fills a small buffer that the
// page reads back one double at a time, and a write takes its values as arguments.

#include <algorithm>
#include <cmath>
#include <limits>

#include <QImage>

#include <Inventor/SbMatrix.h>
#include <Inventor/SbViewVolume.h>
#include <Inventor/SoPickedPoint.h>
#include <Inventor/SoRenderManager.h>
#include <Inventor/actions/SoGetBoundingBoxAction.h>
#include <Inventor/actions/SoRayPickAction.h>
#include <Inventor/nodes/SoDepthBuffer.h>
#include <Inventor/nodes/SoGroup.h>
#include <Inventor/nodes/SoImage.h>
#include <Inventor/nodes/SoOrthographicCamera.h>
#include <Inventor/nodes/SoPerspectiveCamera.h>
#include <Inventor/nodes/SoResetTransform.h>
#include <Inventor/nodes/SoSwitch.h>
#include <Inventor/nodes/SoTransform.h>

#include <Base/BoundBox.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Selection/Selection.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/ViewProvider.h>

namespace
{
// Property ids shared with freecad-gui.html (fcweb3dx).
enum NlProp
{
    NL_VIEW_AFFINE = 0,
    NL_VIEW_EXTENTS = 1,
    NL_VIEW_PERSPECTIVE = 2,
    NL_VIEW_FRUSTUM = 3,
    NL_MODEL_EXTENTS = 4,
    NL_SELECTION_EMPTY = 5,
    NL_SELECTION_EXTENTS = 6,
    NL_HIT_LOOKAT = 7,
    NL_VIEW_ROTATABLE = 8,
    NL_HIT_LOOKFROM = 10,
    NL_HIT_DIRECTION = 11,
    NL_HIT_APERTURE = 12,
    NL_HIT_SELECTION_ONLY = 13,
    NL_PIVOT_POSITION = 14,
    NL_PIVOT_VISIBLE = 15,
};

double nlBuf[16];

struct
{
    SbVec3f origin;
    SbVec3f direction {0.f, 0.f, -1.f};
    float radius = 0.f;
    bool selectionOnly = false;
} ray;
float orthoNearDistance = 0.f;

struct
{
    SoSwitch* pVisibility = nullptr;
    SoTransform* pTransform = nullptr;
    const Gui::View3DInventorViewer* attachedTo = nullptr;
} pivot;

// NavlibInterface::initializePattern: a sunflower spiral of hit-test sample offsets.
constexpr uint32_t hitTestingResolution = 30;
float hitTestPattern[hitTestingResolution][2];
bool patternInitialized = false;

void initializePattern()
{
    if (patternInitialized) {
        return;
    }
    hitTestPattern[0][0] = 0.f;
    hitTestPattern[0][1] = 0.f;
    for (uint32_t i = 1; i < hitTestingResolution; i++) {
        float coefficient = std::sqrt(static_cast<float>(i) / static_cast<float>(hitTestingResolution));
        float angle = 2.4f * static_cast<float>(i);
        hitTestPattern[i][0] = coefficient * std::sin(angle);
        hitTestPattern[i][1] = coefficient * std::cos(angle);
    }
    patternInitialized = true;
}

// The active 3D view, as NavlibInterface::onViewChanged tracks it. The Start page and any
// other non-3D view answer "no data", exactly as desktop does.
Gui::View3DInventorViewer* activeViewer()
{
    auto* view = dynamic_cast<Gui::View3DInventor*>(Gui::Application::Instance
                                                        ? Gui::Application::Instance->activeView()
                                                        : nullptr);
    return view ? view->getViewer() : nullptr;
}

SoCamera* activeCamera()
{
    auto* viewer = activeViewer();
    return viewer ? viewer->getCamera() : nullptr;
}

// NavlibInterface::initializePivot / onViewChanged: the pivot marker lives in the scene of
// the view being navigated.
void attachPivot(Gui::View3DInventorViewer* viewer)
{
    if (!pivot.pVisibility) {
        pivot.pVisibility = new SoSwitch;
        pivot.pTransform = new SoTransform;
        auto* image = new SoImage;
        auto* always = new SoDepthBuffer;
        auto* less = new SoDepthBuffer;
        always->function.setValue(SoDepthBufferElement::ALWAYS);
        less->function.setValue(SoDepthBufferElement::LESS);
        QImage pivotImage(QStringLiteral(":/icons/3dx_pivot.png"));
        if (!pivotImage.isNull()) {
            Gui::BitmapFactory().convert(pivotImage, image->image);
        }
        pivot.pVisibility->ref();
        pivot.pVisibility->whichChild = SO_SWITCH_NONE;
        pivot.pVisibility->addChild(always);
        pivot.pVisibility->addChild(pivot.pTransform);
        pivot.pVisibility->addChild(image);
        pivot.pVisibility->addChild(new SoResetTransform);
        pivot.pVisibility->addChild(less);
    }
    if (!viewer || pivot.attachedTo == viewer) {
        return;
    }
    if (auto* group = dynamic_cast<SoGroup*>(viewer->getSceneGraph())) {
        if (group->findChild(pivot.pVisibility) == -1) {
            group->addChild(pivot.pVisibility);
        }
        pivot.attachedTo = viewer;
    }
}

int fillBox(const SbBox3f& box)
{
    if (box.isEmpty()) {
        return -1;
    }
    const float* mn = box.getMin().getValue();
    const float* mx = box.getMax().getValue();
    for (int i = 0; i < 3; i++) {
        nlBuf[i] = mn[i];
        nlBuf[3 + i] = mx[i];
    }
    return 6;
}

// NavlibInterface::GetViewExtents (orthographic only).
bool viewExtents(double out[6])
{
    auto* camera = dynamic_cast<SoOrthographicCamera*>(activeCamera());
    if (!camera) {
        return false;
    }
    const SbViewVolume viewVolume = camera->getViewVolume(camera->aspectRatio.getValue());
    const double halfHeight = static_cast<double>(viewVolume.getHeight() / 2.0f);
    const double halfWidth = static_cast<double>(viewVolume.getWidth() / 2.0f);
    const double halfDepth = 1.0e8;
    const double v[6] = {-halfWidth, -halfHeight, -halfDepth, halfWidth, halfHeight, halfDepth};
    std::copy(v, v + 6, out);
    return true;
}

bool isPerspective()
{
    return dynamic_cast<SoPerspectiveCamera*>(activeCamera()) != nullptr;
}
}  // namespace

extern "C" {

// A number that changes whenever the active 3D view changes, so the page knows to push the
// new view's camera and model extents (NavlibInterface::onViewChanged).
EMSCRIPTEN_KEEPALIVE double fcweb_nl_view_id()
{
    auto* viewer = activeViewer();
    if (viewer) {
        attachPivot(viewer);
    }
    return static_cast<double>(reinterpret_cast<std::uintptr_t>(viewer));
}

EMSCRIPTEN_KEEPALIVE double fcweb_nl_buf(int i)
{
    return (i >= 0 && i < 16) ? nlBuf[i] : 0.0;
}

// Returns the number of values written to the buffer, or -1 for navlib's no_data_available.
EMSCRIPTEN_KEEPALIVE int fcweb_nl_read(int prop)
{
    auto* viewer = activeViewer();
    SoCamera* camera = viewer ? viewer->getCamera() : nullptr;
    switch (prop) {
        case NL_VIEW_AFFINE: {  // NavlibInterface::GetCameraMatrix
            if (!camera) {
                return -1;
            }
            SbMatrix cameraMatrix;
            camera->orientation.getValue().getValue(cameraMatrix);
            for (int i = 0; i < 4; i++) {
                for (int j = 0; j < 4; j++) {
                    nlBuf[4 * i + j] = cameraMatrix[i][j];
                }
            }
            const SbVec3f position = camera->position.getValue();
            for (int j = 0; j < 3; j++) {
                nlBuf[12 + j] = position[j];
            }
            return 16;
        }
        case NL_VIEW_EXTENTS:
            return viewExtents(nlBuf) ? 6 : -1;
        case NL_VIEW_PERSPECTIVE:  // NavlibInterface::GetIsViewPerspective
            if (!camera) {
                return -1;
            }
            nlBuf[0] = isPerspective() ? 1.0 : 0.0;
            return 1;
        case NL_VIEW_FRUSTUM: {  // NavlibInterface::GetViewFrustum (perspective only)
            auto* p = dynamic_cast<SoPerspectiveCamera*>(camera);
            if (!p) {
                return -1;
            }
            const SbViewVolume viewVolume = p->getViewVolume(p->aspectRatio.getValue());
            const float halfHeight = viewVolume.getHeight() / 2.0f;
            const float halfWidth = viewVolume.getWidth() / 2.0f;
            const double v[6] = {-halfWidth, halfWidth, -halfHeight, halfHeight, viewVolume.getNearDist(),
                                 10.0f * (viewVolume.getNearDist() + viewVolume.nearToFar)};
            std::copy(v, v + 6, nlBuf);
            return 6;
        }
        case NL_MODEL_EXTENTS: {  // NavlibInterface::GetModelExtents
            if (!viewer) {
                return -1;
            }
            SoGetBoundingBoxAction action(viewer->getSoRenderManager()->getViewportRegion());
            action.apply(viewer->getSceneGraph());
            return fillBox(action.getBoundingBox());
        }
        case NL_SELECTION_EMPTY:  // NavlibInterface::GetIsSelectionEmpty
            nlBuf[0] = Gui::Selection().hasSelection() ? 0.0 : 1.0;
            return 1;
        case NL_SELECTION_EXTENTS: {  // NavlibInterface::GetSelectionExtents
            Base::BoundBox3d boundingBox;
            for (auto& selection : Gui::Selection().getSelection()) {
                if (auto* vp = Gui::Application::Instance->getViewProvider(selection.pObject)) {
                    boundingBox.Add(vp->getBoundingBox(selection.SubName, true));
                }
            }
            if (!boundingBox.IsValid()) {
                return -1;
            }
            const double v[6] = {boundingBox.MinX, boundingBox.MinY, boundingBox.MinZ,
                                 boundingBox.MaxX, boundingBox.MaxY, boundingBox.MaxZ};
            std::copy(v, v + 6, nlBuf);
            return 6;
        }
        case NL_HIT_LOOKAT: {  // NavlibInterface::GetHitLookAt
            if (!viewer || !camera || !viewer->getSceneGraph()) {
                return -1;
            }
            SoRayPickAction rayPickAction(viewer->getSoRenderManager()->getViewportRegion());
            SbMatrix cameraMatrix;
            camera->orientation.getValue().getValue(cameraMatrix);
            initializePattern();
            const bool perspective = isPerspective();
            SbVec3f closestHitPoint;
            float minLength = std::numeric_limits<float>::max();
            for (uint32_t i = 0; i < hitTestingResolution; i++) {
                SbVec3f transform(hitTestPattern[i][0] * ray.radius, hitTestPattern[i][1] * ray.radius, 0.0f);
                cameraMatrix.multVecMatrix(transform, transform);
                const SbVec3f origin = ray.origin + transform;
                if (perspective) {
                    rayPickAction.setRay(origin, ray.direction, camera->nearDistance.getValue(),
                                         camera->farDistance.getValue());
                }
                else {
                    rayPickAction.setRay(origin, ray.direction);
                }
                rayPickAction.apply(viewer->getSceneGraph());
                if (SoPickedPoint* picked = rayPickAction.getPickedPoint()) {
                    const SbVec3f hitPoint = picked->getPoint();
                    const float distance = (origin - hitPoint).length();
                    if (distance < minLength) {
                        minLength = distance;
                        closestHitPoint = hitPoint;
                    }
                }
            }
            if (minLength == std::numeric_limits<float>::max()) {
                return -1;
            }
            for (int j = 0; j < 3; j++) {
                nlBuf[j] = closestHitPoint[j];
            }
            return 3;
        }
        case NL_VIEW_ROTATABLE:  // NavlibInterface::GetIsViewRotatable
            nlBuf[0] = viewer ? 1.0 : 0.0;
            return 1;
        case NL_PIVOT_VISIBLE:
            if (!pivot.pVisibility) {
                return -1;
            }
            nlBuf[0] = pivot.pVisibility->whichChild.getValue() == SO_SWITCH_ALL ? 1.0 : 0.0;
            return 1;
        default:
            return -1;
    }
}

// Returns 0, or -1 for navlib's no_data_available.
EMSCRIPTEN_KEEPALIVE int fcweb_nl_write(int prop,
                                        double a0, double a1, double a2, double a3,
                                        double a4, double a5, double a6, double a7,
                                        double a8, double a9, double a10, double a11,
                                        double a12, double a13, double a14, double a15)
{
    const double m[16] = {a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15};
    SoCamera* camera = activeCamera();
    switch (prop) {
        case NL_VIEW_AFFINE: {  // NavlibInterface::SetCameraMatrix
            if (!camera) {
                return -1;
            }
            SbMatrix cameraMatrix(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7],
                                  m[8], m[9], m[10], m[11], m[12], m[13], m[14], m[15]);
            camera->orientation = SbRotation(cameraMatrix);
            camera->position.setValue(m[12], m[13], m[14]);
            camera->touch();
            return 0;
        }
        case NL_VIEW_EXTENTS: {  // NavlibInterface::SetViewExtents
            auto* ortho = dynamic_cast<SoOrthographicCamera*>(camera);
            double oldExtents[6];
            if (!ortho || !viewExtents(oldExtents) || oldExtents[3] == 0.0) {
                return -1;
            }
            ortho->scaleHeight(static_cast<float>(m[3] / oldExtents[3]));
            orthoNearDistance = ortho->nearDistance.getValue();
            return 0;
        }
        case NL_HIT_LOOKFROM:  // NavlibInterface::SetHitLookFrom
            if (isPerspective()) {
                ray.origin.setValue(m[0], m[1], m[2]);
            }
            else {
                if (!camera) {
                    return -1;
                }
                ray.origin = camera->position.getValue() + orthoNearDistance * ray.direction;
            }
            return 0;
        case NL_HIT_DIRECTION:
            ray.direction.setValue(m[0], m[1], m[2]);
            return 0;
        case NL_HIT_APERTURE:
            ray.radius = static_cast<float>(m[0]);
            return 0;
        case NL_HIT_SELECTION_ONLY:
            ray.selectionOnly = m[0] != 0.0;
            return 0;
        case NL_PIVOT_POSITION:  // NavlibInterface::SetPivotPosition
            attachPivot(activeViewer());
            if (!pivot.pTransform) {
                return -1;
            }
            pivot.pTransform->translation.setValue(m[0], m[1], m[2]);
            return 0;
        case NL_PIVOT_VISIBLE:  // NavlibInterface::SetPivotVisible
            attachPivot(activeViewer());
            if (!pivot.pVisibility) {
                return -1;
            }
            pivot.pVisibility->whichChild = m[0] != 0.0 ? SO_SWITCH_ALL : SO_SWITCH_NONE;
            return 0;
        default:
            return -1;
    }
}
}
