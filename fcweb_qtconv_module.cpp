// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// _fcwebqt: the Shiboken converter for Base::Quantity.
//
// FreeCAD is configured with FREECAD_USE_SHIBOKEN=OFF on wasm (configure-gui-weh.sh), so
// Gui/PythonWrapper.cpp's registerTypes() -- the code that teaches PySide how to hand a
// Base::Quantity to a Python slot and how to take one back -- is never compiled, even
// though PySide6 itself is linked in and every widget works. Every Gui::QuantitySpinBox
// signal connected from Python then fails at emit time:
//
//   TypeError: Cannot call meta function "slot(Base::Quantity)" because parameter 0 of
//   type "Base::Quantity" cannot be converted. (4 times)
//
// Measured 2026-09-13 in Draft's Line task panel: the coordinate fields updated on screen
// (C++ side) while the Python slots that drive the tool never ran. Same registration as
// upstream's registerTypes(), as a builtin module the boot script imports once.
//
// Compiled by build-weh-objs.sh against the wasm shiboken6 headers and FreeCAD's Base
// headers; registered in MainGui.cpp's inittab (patches/freecad.patch) as _fcwebqt.
#include <FCConfig.h>

#include <Python.h>

#include <sbkpython.h>
#include <shiboken.h>
#include <sbkconverter.h>

#include <Base/Quantity.h>
#include <Base/QuantityPy.h>

namespace
{

PyObject* toPythonQuantity(const void* cpp)
{
    return new Base::QuantityPy(new Base::Quantity(*static_cast<const Base::Quantity*>(cpp)));
}

void toCppQuantity(PyObject* pyobj, void* cpp)
{
    *static_cast<Base::Quantity*>(cpp) = *static_cast<Base::QuantityPy*>(pyobj)->getQuantityPtr();
}

PythonToCppFunc checkQuantity(PyObject* obj)
{
    if (PyObject_TypeCheck(obj, &(Base::QuantityPy::Type))) {
        return toCppQuantity;
    }
    return nullptr;
}

bool installed = false;

PyObject* install(PyObject* /*self*/, PyObject* /*args*/)
{
    if (!installed) {
        SbkConverter* conv = Shiboken::Conversions::createConverter(&Base::QuantityPy::Type, toPythonQuantity);
        Shiboken::Conversions::setPythonToCppPointerFunctions(conv, toCppQuantity, checkQuantity);
        Shiboken::Conversions::registerConverterName(conv, "Base::Quantity");
        installed = true;
        Py_RETURN_TRUE;   // registered now
    }
    Py_RETURN_FALSE;      // was already registered
}

PyObject* isInstalled(PyObject* /*self*/, PyObject* /*args*/)
{
    return PyBool_FromLong(installed ? 1 : 0);
}

PyMethodDef methods[] = {
    {"install", install, METH_NOARGS, "Register the Shiboken converter for Base::Quantity (idempotent)."},
    {"installed", isInstalled, METH_NOARGS, "Whether the converter has been registered."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef moduleDef = {
    PyModuleDef_HEAD_INIT, "_fcwebqt", "FreeCAD-Web: PySide conversions the wasm build lacks", -1, methods,
    nullptr, nullptr, nullptr, nullptr,
};

}  // namespace

extern "C" PyObject* PyInit__fcwebqt(void)
{
    return PyModule_Create(&moduleDef);
}
