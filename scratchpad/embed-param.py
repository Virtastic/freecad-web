import os
import FreeCAD as App
d = App.newDocument("Param")
s = d.addObject("Spreadsheet::Sheet", "Spreadsheet")
s.set("A1", "20"); s.setAlias("A1", "len")
b = d.addObject("Part::Box", "Box")
b.setExpression("Length", "Spreadsheet.len")
b.Width = 10; b.Height = 5
d.recompute()
d.saveAs("os.environ.get("OUT", "param.FCStd")")
import sys; sys.__stderr__.write("SAVED %s\n" % b.Shape.Volume); sys.__stderr__.flush()
