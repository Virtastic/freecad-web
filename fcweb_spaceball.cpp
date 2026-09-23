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
