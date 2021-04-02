#!/usr/bin/env python3

# suppress some nasty warnings we don't want. Note that this is really generic. For developing purposes re-enable this
import logging
for key in logging.Logger.manager.loggerDict:
    print(key)
logging.getLogger().setLevel(logging.CRITICAL)

import sys
import os
from lxml import etree

import inkex
from inkex import transforms
from inkex.paths import CubicSuperPath
from inkex.command import inkscape

import vpype
import vpype_viewer
from vpype_viewer import ViewMode
from vpype_cli import execute

from shapely.geometry import LineString, Point

"""
Extension for InkScape 1.X
Author: Mario Voigt / FabLab Chemnitz
Mail: mario.voigt@stadtfabrikanten.org
Date: 01.04.2021
Last patch: 01.04.2021
License: GNU GPL v3

Used version of vpype: commit id https://github.com/abey79/vpype/commit/0b0dc8dd7e32998dbef639f9db578c3bff02690b

CLI / API docs:
- https://vpype.readthedocs.io/en/stable/api/vpype_cli.html#module-vpype_cli
- https://vpype.readthedocs.io/en/stable/api/vpype.html#module-vpype

vpype commands could be performed differently: 
 - 1. Work with current selection (line-wise): we could get the selected nodes/groups and check if those nodes are paths. If yes we could convert them to polylines and put it into vpype using doc.add(LineCollection, Layer)
 - 2. We could execute vpype on the complete document only (svg file handling, possible as one layer or multiple layers)
      working line of code (example:) doc = vpype.read_multilayer_svg(self.options.input_file, quantization=0.1, crop=False, simplify=False, parallel=False)

Todo's
- show_pen_up does not work. does not get written to svg file properly > https://github.com/abey79/vpype/issues/242
- https://github.com/abey79/vpype/issues/243
"""

class vpypetools (inkex.EffectExtension):

    def __init__(self):
        inkex.Effect.__init__(self)
        self.arg_parser.add_argument("--linesort_no_flip", type=inkex.Boolean, default=False, help="Disable reversing stroke direction for optimization")
        self.arg_parser.add_argument("--apply_transformations", type=inkex.Boolean, default=False, help="Run 'Apply Transformations' extension before running vpype. Helps avoiding geometry shifting")
        self.arg_parser.add_argument("--output_show", type=inkex.Boolean, default=False, help="This will open a new matplotlib window showing modified SVG data")
        self.arg_parser.add_argument("--output_stats", type=inkex.Boolean, default=False, help="Show output statistics before/after conversion")
        self.arg_parser.add_argument("--output_trajectories", type=inkex.Boolean, default=False, help="Add paths for the travel trajectories")
        self.arg_parser.add_argument("--keep_selection", type=inkex.Boolean, default=True, help="If false, selected paths will be removed")
 
    def effect(self):  
        lc = vpype.LineCollection() # create a new array of LineStrings consisting of Points. We convert selected paths to polylines and grab their points
        nodesToConvert = [] # we make an array of all collected nodes to get the boundingbox of that array. We need it to place the vpype converted stuff to the correct XY coordinates
        
        applyTransformAvailable = False
        
        # at first we apply external extension
        try:
            sys.path.append("..") # add parent directory to path to allow importing applytransform (vpype extension is encapsulated in sub directory)
            import applytransform
            applyTransformAvailable = True
        except Exception as e:
            # inkex.utils.debug(e)
            inkex.utils.debug("Calling 'Apply Transformations' extension failed. Maybe the extension is not installed. You can download it from official InkScape Gallery. Skipping this step")


        def convertPath(node):
            if node.tag == inkex.addNS('path','svg'):
                nodesToConvert.append(node)
                d = node.get('d')
                p = CubicSuperPath(d)
                points = []
                for subpath in p:
                    for csp in subpath:
                        points.append(Point(csp[1][0], csp[1][1]))
                lc.append(LineString(points))        
            children = node.getchildren()
            if children is not None: 
                for child in children:
                    convertPath(child)

        # inkex.utils.debug(str(applyTransformAvailable)) #check if ApplyTransform Extension is available. If yes we use it
        if self.options.apply_transformations is True and applyTransformAvailable is True:
            applytransform.ApplyTransform().recursiveFuseTransform(self.document.getroot())

        # getting the bounding box of the current selection. We use to calculate the offset XY from top-left corner of the canvas. This helps us placing back the elements
        bbox = None
        if len(self.svg.selected) == 0:
            convertPath(self.document.getroot())
            for element in nodesToConvert:
                bbox += element.bounding_box()      
        else:
            for id, item in self.svg.selected.items():
                convertPath(item)
            bbox = inkex.elements._selected.ElementList.bounding_box(self.svg.selected) # get BoundingBox for selection
            
        # inkex.utils.debug(bbox)
            
        #l c.as_mls() #cast LineString array to MultiLineString

        if len(lc) == 0:
            inkex.errormsg('Selection does not contain any paths. Try to cast your objects to paths using CTRL + SHIFT + C or strokes to paths using CTRL + ALT+ C')
            return

        doc = vpype.Document() #create new vpype document
        
        # we add the lineCollection (converted selection) to the vpype document
        doc.add(lc, layer_id=None)

        if self.options.output_stats is True:
            tooling_length_before = doc.length()
            traveling_length_before = doc.pen_up_length()
        
        # build and execute the conversion command
        command = "linesort "
        if self.options.linesort_no_flip:
            command += " --no-flip"      
        # inkex.utils.debug(command)
        doc = execute(command, doc)

        # show the vpype document visually
        # there are missing options to set pen_width and pen_opacity. This is anchored in "Engine" class
        if self.options.output_show:
            vpype_viewer.show(doc, view_mode=ViewMode.PREVIEW, show_pen_up=self.options.output_trajectories, show_points=False, argv=None) # https://vpype.readthedocs.io/en/stable/api/vpype_viewer.ViewMode.html
      
        if self.options.output_stats is True:
            tooling_length_after = doc.length()
            traveling_length_after = doc.pen_up_length()        
            if tooling_length_before > 0:
                tooling_length_saving = (1.0 - tooling_length_after / tooling_length_before) * 100.0
            else:
                tooling_length_saving = 0.0            
            if traveling_length_before > 0:
                traveling_length_saving = (1.0 - traveling_length_after / traveling_length_before) * 100.0
            else:
                traveling_length_saving = 0.0                 
            inkex.utils.debug('Total tooling length before vpype conversion: '   + str('{:0.2f}'.format(tooling_length_before))   + ' mm')
            inkex.utils.debug('Total traveling length before vpype conversion: ' + str('{:0.2f}'.format(traveling_length_before)) + ' mm')
            inkex.utils.debug('Total tooling length after vpype conversion: '    + str('{:0.2f}'.format(tooling_length_after))    + ' mm')
            inkex.utils.debug('Total traveling length after vpype conversion: '  + str('{:0.2f}'.format(traveling_length_after))  + ' mm')
            inkex.utils.debug('Total tooling length optimized: '   + str('{:0.2f}'.format(tooling_length_saving))   + ' %')
            inkex.utils.debug('Total traveling length optimized: ' + str('{:0.2f}'.format(traveling_length_saving)) + ' %')
          
        # save the vpype document to new svg file and close it afterwards
        output_file = self.options.input_file + ".vpype.svg"
        output_fileIO = open(output_file, "w", encoding="utf-8")
        vpype.write_svg(output_fileIO, doc, page_size=None, center=False, source_string='', layer_label_format='%d', show_pen_up=self.options.output_trajectories, color_mode='layer')       
        output_fileIO.close()
        
        # convert vpype polylines/lines/polygons to regular paths again. We need to use "--with-gui" to respond to "WARNING: ignoring verb FileSave - GUI required for this verb."
        cli_output = inkscape(output_file, "--with-gui", actions="EditSelectAllInAllLayers;EditUnlinkClone;ObjectToPath;FileSave;FileQuit")
        
        if len(cli_output) > 0:
            self.debug(_("Inkscape returned the following output when trying to run the vpype object to path back-conversion:"))
            self.debug(cli_output)
        
        # new parse the SVG file and insert it as new group into the current document tree
        # converted = etree.parse(output_file).getroot()
        converted = etree.parse(output_file).getroot().xpath("//svg:g[@inkscape:label='1']",namespaces=inkex.NSS) # the label id is the number of layer_id=None (will start with 1)
        newGroup = self.document.getroot().add(inkex.Group())
        newGroup.set('style', 'stroke:#000000;stroke-width:1px;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1;fill:none')       
        for child in converted[0].getchildren(): 
            newGroup.append(child)
        newGroup.attrib['transform'] = 'translate(' + str(bbox.left) + ',' + str(bbox.top) + ')'
        newGroupId = self.svg.get_unique_id('vpypetools-')
        newGroup.set('id', newGroupId)

        # inkex.utils.debug(self.svg.selection.first()) # get the first selected element. Chould be None
        self.svg.selection.set(newGroupId)
        #inkex.utils.debug(self.svg.selection.first()) # get the first selected element again to check if changing selection has worked
      
        # we apply transformations also for new group to remove the "translate()" again
        if self.options.apply_transformations and applyTransformAvailable:
            for node in self.svg.selection:
                applytransform.ApplyTransform().recursiveFuseTransform(node) 

        # Delete the temporary file again because we do not need it anymore
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # Remove selection objects to do a real replace with new objects from vpype document
        if self.options.keep_selection is False:
            for node in nodesToConvert:
                node.getparent().remove(node)
    
if __name__ == '__main__':
    vpypetools().run()
