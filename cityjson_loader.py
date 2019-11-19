# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CityJsonLoader
                                 A QGIS plugin
 This plugin allows for CityJSON files to be loaded in QGIS
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2018-06-08
        git sha              : $Format:%H$
        copyright            : (C) 2018 by 3D Geoinformation
        email                : s.vitalis@tudelft.nl
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os.path

from PyQt5.QtCore import (QCoreApplication, QSettings, QTranslator, QVariant,
                          qVersion)
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import QAction, QDialogButtonBox, QFileDialog, QMessageBox
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionDialog

from .cjio import cityjson
from .core.geometry import GeometryReader, VerticesCache
from .core.helpers.treemodel import (MetadataElement, MetadataModel,
                                     MetadataNode)
from .core.layers import (AttributeFieldsDecorator, BaseFieldsBuilder,
                          BaseNamingIterator, DynamicLayerManager,
                          LodFeatureDecorator, LodFieldsDecorator,
                          LodNamingDecorator, SemanticSurfaceFeatureDecorator,
                          SemanticSurfaceFieldsDecorator, SimpleFeatureBuilder,
                          TypeNamingIterator)
from .core.loading import CityJSONLoader, load_cityjson_model
from .core.styling import (Copy2dStyling, NullStyling, SemanticSurfacesStyling,
                           is_3d_styling_available,
                           is_rule_based_3d_styling_available)
# Import the code for the dialog
from .gui.cityjson_loader_dialog import CityJsonLoaderDialog
from .resources import *
from .processing.provider import Provider


class CityJsonLoader:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'CityJsonLoader_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = CityJsonLoaderDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&CityJSON Loader')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'CityJsonLoader')
        self.toolbar.setObjectName(u'CityJsonLoader')

        self.dlg.browseButton.clicked.connect(self.select_cityjson_file)
        self.dlg.changeCrsPushButton.clicked.connect(self.select_crs)
        self.dlg.semanticsLoadingCheckBox.stateChanged.connect(self.semantics_loading_changed)

        self.provider = None
    
    def initProcessing(self):
        """Initialises the processing provider"""
        self.provider = Provider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def select_cityjson_file(self):
        """Shows a dialog to select a CityJSON file."""
        filename, _ = QFileDialog.getOpenFileName(self.dlg,
                                                  "Select CityJSON file",
                                                  "",
                                                  "*.json")
        if filename == "":
            self.clear_file_information()
        else:
            self.dlg.cityjsonPathLineEdit.setText(filename)
            self.update_file_information(filename)
    
    def select_crs(self):
        """Shows a dialog to select a new CRS for the model"""
        crs_dialog = QgsProjectionSelectionDialog()
        crs_dialog.setShowNoProjection(True)
        if self.dlg.crsLineEdit.text() != "None":
            old_crs = QgsCoordinateReferenceSystem("EPSG:{}".format(self.dlg.crsLineEdit.text()))
            crs_dialog.setCrs(old_crs)
        crs_dialog.exec()
        if crs_dialog.crs().postgisSrid() == 0:
            self.dlg.crsLineEdit.setText("None")
        else:
            self.dlg.crsLineEdit.setText("{}".format(crs_dialog.crs().postgisSrid()))

    def semantics_loading_changed(self):
        """Update the GUI according to the new state of semantic
        surfaces loading
        """
        if is_rule_based_3d_styling_available():
            self.dlg.semanticSurfacesStylingCheckBox.setEnabled(self.dlg.semanticsLoadingCheckBox.isChecked())

    def clear_file_information(self):
        """Clear all fields related to file information"""
        line_edits = [self.dlg.cityjsonVersionLineEdit,
                      self.dlg.compressedLineEdit,
                      self.dlg.crsLineEdit]
        for line_edit in line_edits:
            line_edit.setText("")
        self.dlg.metadataTreeView.setModel(None)
        self.dlg.changeCrsPushButton.setEnabled(False)
        self.dlg.button_box.button(QDialogButtonBox.Ok).setEnabled(False)

    def update_file_information(self, filename):
        """Update metadata fields according to the file provided"""
        try:
            fstream = open(filename, encoding='utf-8-sig')
            model = cityjson.CityJSON(fstream)
            self.dlg.cityjsonVersionLineEdit.setText(model.get_version())
            self.dlg.compressedLineEdit.setText("Yes" if "transform" in model.j else "No")
            if "crs" in model.j["metadata"]:
                self.dlg.crsLineEdit.setText(str(model.j["metadata"]["crs"]["epsg"]))
            elif "referenceSystem" in model.j["metadata"]:
                self.dlg.crsLineEdit.setText(str(model.j["metadata"]["referenceSystem"]).split("::")[1])
            else:
                self.dlg.crsLineEdit.setText("None")
            self.dlg.changeCrsPushButton.setEnabled(True)
            self.dlg.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
            model = MetadataModel(model.j["metadata"], self.dlg.metadataTreeView)
            self.dlg.metadataTreeView.setModel(model)
            self.dlg.metadataTreeView.setColumnWidth(0, model.getKeyColumnWidth())
        except Exception as error:
            self.dlg.changeCrsPushButton.setEnabled(False)
            self.dlg.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            raise error

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('CityJsonLoader', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/cityjson_loader/cityjson_logo.svg'
        self.add_action(
            icon_path,
            text=self.tr(u'Load CityJSON...'),
            callback=self.run,
            parent=self.iface.mainWindow())
        
        self.initProcessing()


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr(u'&CityJSON Loader'),
                action)
            self.iface.removeToolBarIcon(action)

        del self.toolbar
        
        QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        """Run method that performs all the real work"""
        # show the dialog
        self.dlg.show()
        self.dlg.changeCrsPushButton.setEnabled(False)
        self.dlg.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        self.dlg.semanticSurfacesStylingCheckBox.setEnabled(False)
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:
            filepath = self.dlg.cityjsonPathLineEdit.text()
            self.load_cityjson(filepath)
    
    def load_cityjson(self, filepath):
        """Loads the given CityJSON"""

        citymodel = load_cityjson_model(filepath)

        lod_as = 'NONE'
        if self.dlg.loDLoadingComboBox.currentIndex() == 1:
            lod_as = 'ATTRIBUTES'
        elif self.dlg.loDLoadingComboBox.currentIndex() == 2:
            lod_as = 'LAYERS'

        loader = CityJSONLoader(filepath,
                                citymodel,
                                epsg=self.dlg.crsLineEdit.text(),
                                divide_by_object=self.dlg.splitByTypeCheckBox.isChecked(),
                                lod_as=lod_as,
                                load_semantic_surfaces=self.dlg.semanticsLoadingCheckBox.isChecked(),
                                style_semantic_surfaces=self.dlg.semanticsLoadingCheckBox.isChecked()
                               )

        skipped_geometries = loader.load()

        # Show a message with the outcome of the loading process
        msg = QMessageBox()
        if skipped_geometries > 0:
            msg.setIcon(QMessageBox.Warning)
            msg.setText("CityJSON loaded with issues.")
            msg.setInformativeText("Some geometries were skipped.")
            msg.setDetailedText("{} geometries could not be loaded (p.s. "
                                "GeometryInstances are not supported yet).".format(skipped_geometries))
        else:
            msg.setIcon(QMessageBox.Information)
            msg.setText("CityJSON loaded successfully.")
        
        msg.setWindowTitle("CityJSON loading finished")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
