from qgis.core import QgsProject
from qgis.utils import iface
from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QKeySequence

def advance_layer():
    """Hides current layer and shows next without changing zoom or editing state."""
    root = QgsProject.instance().layerTreeRoot()
    nodes = root.findLayers()
    
    current_index = None
    for i, node in enumerate(nodes):
        if node.isVisible():
            current_index = i
            break
            
    if current_index is not None:
        # 1. Hide the current layer
        nodes[current_index].setItemVisibilityChecked(False)
        
        # 2. Move to the next layer in the list
        next_index = (current_index + 1) % len(nodes)
        next_node = nodes[next_index]
        
        # 3. Show the next layer and set it as the active target
        next_node.setItemVisibilityChecked(True)
        iface.setActiveLayer(next_node.layer())
        
        # We specifically omit setExtent() and startEditing() here
    else:
        # If nothing is on, turn on the first layer
        if nodes:
            nodes[0].setItemVisibilityChecked(True)
            iface.setActiveLayer(nodes[0].layer())

def openProject():
    # Clean up any existing "Advance Layer" actions to prevent duplicates
    for action in iface.mainWindow().findChildren(QAction):
        if action.text() == "Advance Layer":
            iface.mainWindow().removeAction(action)

    action = QAction("Advance Layer", iface.mainWindow())
    action.setShortcut(QKeySequence("Ctrl+Space"))
    action.triggered.connect(advance_layer)
    iface.mainWindow().addAction(action)

def saveProject():
    pass

def closeProject():
    pass