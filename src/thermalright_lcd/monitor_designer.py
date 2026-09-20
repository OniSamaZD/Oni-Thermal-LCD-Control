from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QSize
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QFont, QImage, QPixmap, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QFrame, QGraphicsItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QFileDialog, QInputDialog,
    QSplitter, QToolBox, QVBoxLayout, QWidget, QColorDialog, QFontComboBox,
    QToolButton, QMenu,
)

from .hardware_monitor import MonitorElement, MonitorLayout, MonitorRenderer, WIDGET_KINDS, templates
from .sensors import resolve_semantic_sensor
from .layout_editing import LayoutEditController


class ElementItem(QGraphicsRectItem):
    def __init__(self, element: MonitorElement, scene):
        super().__init__(0, 0, element.width, element.height);self.element=element;self.designer_scene=scene
        self.setPos(element.x,element.y);self.setZValue(element.z_index);self.setFlags(QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemSendsGeometryChanges|QGraphicsItem.ItemIsFocusable)
        self._resizing=False;self._resize_origin=None
        self._sync_flags();self.setVisible(element.visible);self.setToolTip("Drag to position · use Properties for pixel-precise editing")
    def _sync_flags(self):self.setFlag(QGraphicsItem.ItemIsMovable,not self.element.locked)
    def itemChange(self,change,value):
        if change==QGraphicsItem.ItemPositionChange and self.scene() and not self.element.locked:
            point=value;layout=self.designer_scene.layout
            if layout.snap_to_grid and layout.grid_size>1:
                point.setX(round(point.x()/layout.grid_size)*layout.grid_size);point.setY(round(point.y()/layout.grid_size)*layout.grid_size)
            point.setX(max(0,min(layout.width-self.element.width,point.x())));point.setY(max(0,min(layout.height-self.element.height,point.y())))
            if self.element.group_id and not self.designer_scene.moving_group:
                delta=point-self.pos();self.designer_scene.move_group(self.element.group_id,self,delta)
            return point
        if change==QGraphicsItem.ItemPositionHasChanged:
            self.element.x=round(self.pos().x());self.element.y=round(self.pos().y());self.designer_scene.changed.emit()
        if change==QGraphicsItem.ItemSelectedHasChanged and bool(value):self.designer_scene.elementSelected.emit(self.element.id)
        return super().itemChange(change,value)
    def paint(self,painter,option,widget=None):
        # The complete dashboard is painted once by DesignerScene using the
        # production MonitorRenderer. Items are transparent hit targets so the
        # editor cannot replace gauges/graphs/bars with placeholder boxes.
        painter.setRenderHint(QPainter.Antialiasing);painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#7183ff" if self.isSelected() else "#40506a"),2 if self.isSelected() else 1,Qt.DashLine if not self.isSelected() else Qt.SolidLine));painter.drawRoundedRect(self.rect(),8,8)
        if self.element.locked:
            painter.setPen(QColor("#f2f6ff"));painter.drawText(self.rect().adjusted(4,4,-4,-4),Qt.AlignRight|Qt.AlignTop,"LOCK")
        if self.isSelected() and not self.element.locked:
            painter.setBrush(QColor("#f2f6ff"));painter.setPen(QPen(QColor("#7183ff"),1));painter.drawRect(self.rect().right()-9,self.rect().bottom()-9,9,9)
    def mousePressEvent(self,event):
        self.designer_scene.controller.begin_external()
        corner=self.rect().adjusted(self.rect().width()-16,self.rect().height()-16,0,0)
        self._resizing=not self.element.locked and corner.contains(event.pos())
        if self._resizing:self._resize_origin=(event.scenePos(),self.element.width,self.element.height);event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self._resizing:
            start,w,h=self._resize_origin;delta=event.scenePos()-start;grid=self.designer_scene.layout.grid_size if self.designer_scene.layout.snap_to_grid else 1
            width=max(10,min(self.designer_scene.layout.width-self.element.x,round((w+delta.x())/grid)*grid));height=max(10,min(self.designer_scene.layout.height-self.element.y,round((h+delta.y())/grid)*grid))
            self.prepareGeometryChange();self.element.width=int(width);self.element.height=int(height);self.setRect(0,0,width,height);self.designer_scene.changed.emit();event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self._resizing:self._resizing=False;self._resize_origin=None;self.designer_scene.controller.end_external();event.accept();return
        super().mouseReleaseEvent(event);self.designer_scene.controller.end_external()


class DesignerScene(QGraphicsScene):
    elementSelected=Signal(str);changed=Signal();deleteRequested=Signal();duplicateRequested=Signal()
    def __init__(self,layout,parent=None):
        super().__init__(parent);self.layout=layout;self.controller=LayoutEditController(layout);self.controller.set_enabled(True);self.items_by_id={};self.live_values={};self.moving_group=False;self.clipboard=[];self.setSceneRect(0,0,layout.width,layout.height);self.reload()
    def reload(self):
        self.clear();self.items_by_id={}
        for element in self.layout.elements:
            item=ElementItem(element,self);self.addItem(item);self.items_by_id[element.id]=item
        self.update()
    def drawBackground(self,painter,rect):
        rendered=MonitorRenderer(self.layout).render(self.live_values)
        data=rendered.tobytes("raw","RGB");image=QImage(data,rendered.width,rendered.height,rendered.width*3,QImage.Format_RGB888).copy();rendered.close()
        painter.drawImage(self.sceneRect(),image)
        if self.layout.snap_to_grid and self.layout.grid_size>1:
            painter.setPen(QPen(QColor(70,82,104,70),0));step=self.layout.grid_size
            x=int(rect.left())-int(rect.left())%step
            while x<rect.right():painter.drawLine(x,rect.top(),x,rect.bottom());x+=step
            y=int(rect.top())-int(rect.top())%step
            while y<rect.bottom():painter.drawLine(rect.left(),y,rect.right(),y);y+=step
    def drawForeground(self,painter,rect):
        if not self.layout.alignment_guides:return
        selected=[x for x in self.selectedItems() if isinstance(x,ElementItem)]
        if not selected:return
        item=selected[0];painter.setPen(QPen(QColor("#ff4fc8"),1,Qt.DashLine))
        cx=item.sceneBoundingRect().center().x();cy=item.sceneBoundingRect().center().y()
        if abs(cx-self.layout.width/2)<6:painter.drawLine(self.layout.width/2,0,self.layout.width/2,self.layout.height)
        if abs(cy-self.layout.height/2)<6:painter.drawLine(0,self.layout.height/2,self.layout.width,self.layout.height/2)
        for other in self.items_by_id.values():
            if other is item:continue
            box=other.sceneBoundingRect();mine=item.sceneBoundingRect()
            if abs(mine.left()-box.left())<4:painter.drawLine(box.left(),0,box.left(),self.layout.height)
            if abs(mine.top()-box.top())<4:painter.drawLine(0,box.top(),self.layout.width,box.top())
    def move_group(self,group_id,source,delta):
        if delta.isNull():return
        self.moving_group=True
        try:
            for item in self.items_by_id.values():
                if item is not source and item.element.group_id==group_id and not item.element.locked:item.setPos(item.pos()+delta)
        finally:self.moving_group=False
    def selected_elements(self):return [item.element for item in self.selectedItems() if isinstance(item,ElementItem)]
    def _controller_selection(self):self.controller.selected_ids={e.id for e in self.selected_elements()}
    def scale_selected(self,factor:float):
        self._controller_selection()
        if self.controller.scale(factor):self.reload();self.changed.emit()
    def align_selected(self,edge:str):
        self._controller_selection()
        if self.controller.align(edge):self.reload();self.changed.emit()
    def distribute_selected(self,axis):
        self._controller_selection()
        if self.controller.distribute(axis):self.reload();self.changed.emit()
    def undo(self):
        if self.controller.undo():self.reload();self.changed.emit()
    def redo(self):
        if self.controller.redo():self.reload();self.changed.emit()
    def set_live_values(self,values):self.live_values=dict(values);self.update()
    def keyPressEvent(self,event):
        selected=[x for x in self.selectedItems() if isinstance(x,ElementItem)]
        if event.key()==Qt.Key_C and event.modifiers()&Qt.ControlModifier:self.clipboard=[deepcopy(x.element) for x in selected];event.accept();return
        if event.key()==Qt.Key_V and event.modifiers()&Qt.ControlModifier:
            copies=[]
            for source in self.clipboard:
                item=deepcopy(source);item.id=uuid4().hex;item.x=min(self.layout.width-item.width,item.x+self.layout.grid_size);item.y=min(self.layout.height-item.height,item.y+self.layout.grid_size);item.group_id="";copies.append(item)
            if copies:self.layout.elements.extend(copies);self.reload();[self.items_by_id[x.id].setSelected(True) for x in copies];self.changed.emit()
            event.accept();return
        if event.key()==Qt.Key_Delete:self.deleteRequested.emit();event.accept();return
        if event.key()==Qt.Key_D and event.modifiers()&Qt.ControlModifier:self.duplicateRequested.emit();event.accept();return
        movement={Qt.Key_Left:(-1,0),Qt.Key_Right:(1,0),Qt.Key_Up:(0,-1),Qt.Key_Down:(0,1)}.get(event.key())
        if movement:
            scale=10 if event.modifiers()&Qt.ShiftModifier else 1
            for item in selected:
                if not item.element.locked:item.setPos(item.pos().x()+movement[0]*scale,item.pos().y()+movement[1]*scale)
            event.accept();return
        super().keyPressEvent(event)


class CanvasView(QGraphicsView):
    def __init__(self,scene,parent=None):
        super().__init__(scene,parent);self.setRenderHint(QPainter.Antialiasing);self.setDragMode(QGraphicsView.RubberBandDrag);self.setAcceptDrops(True);self.setMinimumSize(680,270);self.setFrameShape(QFrame.NoFrame)
    def resizeEvent(self,event):super().resizeEvent(event);self.fitInView(self.sceneRect(),Qt.KeepAspectRatio)


class HomeQuickEditor(QWidget):
    """Compact Home surface backed by the same scene and mutation controller."""
    changed=Signal();closeRequested=Signal()
    def __init__(self,layout,parent=None):
        super().__init__(parent);self.layout=layout;root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(3)
        bar=QHBoxLayout();actions=(("↶ Undo",lambda:self.scene.undo()),("↷ Redo",lambda:self.scene.redo()),("⎘ Duplicate",self.duplicate),("✕ Delete",self.delete))
        for label,callback in actions:b=QPushButton(label);b.setFixedHeight(26);b.clicked.connect(callback);bar.addWidget(b)
        arrange=QToolButton();arrange.setText("Arrange ▾");arrange.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(arrange)
        for label,callback in (("Scale up 10%",lambda:self.scene.scale_selected(1.1)),("Scale down 10%",lambda:self.scene.scale_selected(1/1.1)),("Align left",lambda:self.scene.align_selected('left')),("Align top",lambda:self.scene.align_selected('top')),("Distribute horizontally",lambda:self.scene.distribute_selected('horizontal')),("Distribute vertically",lambda:self.scene.distribute_selected('vertical')),("Bring forward",lambda:self.z(1)),("Send backward",lambda:self.z(-1))):menu.addAction(label).triggered.connect(callback)
        arrange.setMenu(menu);bar.addWidget(arrange)
        self.save_state=QLabel("Saved");self.save_state.setObjectName("editState");self.autosave_state=QLabel("");self.autosave_state.setObjectName("muted");self.autosave_state.setToolTip("Layout edits are preserved as a local draft until you explicitly save the profile.");done=QPushButton("Done");done.setFixedHeight(24);done.clicked.connect(self.closeRequested);bar.addStretch();bar.addWidget(self.save_state);bar.addWidget(self.autosave_state);bar.addWidget(done);root.addLayout(bar)
        self.scene=DesignerScene(layout,self);self.canvas=CanvasView(self.scene,self);self.canvas.setMinimumSize(0,180);self.properties=PropertiesPanel(self);self.properties.setMinimumWidth(260);self.properties.setMaximumWidth(360);self.splitter=QSplitter();self.splitter.addWidget(self.canvas);self.splitter.addWidget(self.properties);self.splitter.setSizes([720,300]);root.addWidget(self.splitter,1)
        self.scene.changed.connect(self._scene_changed);self.scene.elementSelected.connect(self.select_element);self.properties.changed.connect(self.property_changed)
        self.scene.deleteRequested.connect(self.delete);self.scene.duplicateRequested.connect(self.duplicate)
    def selected_ids(self):return {e.id for e in self.scene.selected_elements()}
    def mutate(self,callback):
        self.scene._controller_selection()
        if callback():self.scene.reload();self.changed.emit()
    def duplicate(self):self.mutate(self.scene.controller.duplicate)
    def delete(self):self.mutate(self.scene.controller.delete)
    def z(self,delta):self.mutate(lambda:self.scene.controller.change_z(delta))
    def _scene_changed(self):
        selected=self.scene.selected_elements()
        if len(selected)==1:self.properties.set_element(selected[0])
        self.save_state.setText("Modified");self.autosave_state.setText("· Draft autosaved");self.changed.emit()
    def mark_saved(self):self.save_state.setText("Saved");self.autosave_state.clear()
    def select_element(self,element_id):
        element=next((item for item in self.layout.elements if item.id==element_id),None)
        if element:self.properties.set_element(element)
    def property_changed(self):
        element=self.properties.element
        if not element:return
        item=self.scene.items_by_id.get(element.id)
        if item:
            item.prepareGeometryChange();item.setRect(0,0,element.width,element.height);snap=self.layout.snap_to_grid;self.layout.snap_to_grid=False
            try:item.setPos(element.x,element.y)
            finally:self.layout.snap_to_grid=snap
            item.setZValue(element.z_index);item._sync_flags();item.update()
        self.scene.update();self._scene_changed()


class ColorField(QWidget):
    changed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(4);self.edit=QLineEdit();self.button=QPushButton("●");self.button.setFixedWidth(34);row.addWidget(self.edit,1);row.addWidget(self.button);self.edit.editingFinished.connect(self.changed);self.button.clicked.connect(self.choose)
    def text(self):return self.edit.text()
    def setText(self,value):self.edit.setText(str(value));self._swatch()
    def _swatch(self):
        color=QColor(self.edit.text());self.button.setStyleSheet(f"color:{color.name() if color.isValid() else '#ffffff'}")
    def choose(self):
        initial=QColor(self.edit.text());color=QColorDialog.getColor(initial if initial.isValid() else QColor("white"),self,"Choose color",QColorDialog.ShowAlphaChannel)
        if color.isValid():self.edit.setText(color.name(QColor.HexArgb) if color.alpha()<255 else color.name());self._swatch();self.changed.emit()


class PropertiesPanel(QScrollArea):
    changed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.element=None;self.loading=False;body=QWidget();outer=QVBoxLayout(body);self.selected_title=QLabel("SELECT AN ELEMENT");self.selected_title.setObjectName("inspectorTitle");self.selected_title.setWordWrap(True);outer.addWidget(self.selected_title);self.toolbox=QToolBox();outer.addWidget(self.toolbox);self.controls={};self.forms={};self.setWidget(body);self.setWidgetResizable(True);self.setMinimumWidth(330)
        for name in ("Content","Position & Size","Appearance","Formatting","Advanced"):
            page=QWidget();self.forms[name]=QFormLayout(page);self.toolbox.addItem(page,name)
        self.form=self.forms["Content"]
        self._combo("kind",WIDGET_KINDS);self._line("text");self._line("sensor_id");self._line("provider");self._line("custom_label");self._line("format_string");self._line("unit");self._spin("decimals",0,8);self._line("prefix");self._line("suffix")
        self.form=self.forms["Position & Size"];self._spin("x",0,4000);self._spin("y",0,2000);self._spin("width",1,4000);self._spin("height",1,2000);self._combo("align",("left","center","right"));self._combo("vertical_align",("top","middle","bottom"))
        self.form=self.forms["Appearance"];self._font("font_family");self._spin("font_size",6,300);self._spin("font_weight",100,900);self._check("bold");self._combo("text_style",("normal","italic","bold italic"));self._color("color");self._spin("opacity",0,255);self._color("background");self._color("border_color");self._spin("border_width",0,30);self._spin("rotation",-360,360);self._spin("brightness",0,200);self._check("preserve_aspect");self._color("outline_color");self._spin("outline_width",0,20);self._color("shadow_color");self._spin("shadow_offset",0,30)
        self.form=self.forms["Formatting"];self._spin("padding",0,100);self._spin("spacing",0,50)
        self.form=self.forms["Advanced"];self._double("minimum",-1000000,1000000);self._double("maximum",-1000000,1000000);self._line("visibility_condition");self._line("image");self._check("visible");self._check("locked");self._spin("z_index",-1000,1000)
    def _line(self,name):w=QLineEdit();w.editingFinished.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _font(self,name):w=QFontComboBox();w.currentFontChanged.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _color(self,name):w=ColorField();w.changed.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _spin(self,name,low,high):w=QSpinBox();w.setRange(low,high);w.valueChanged.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _double(self,name,low,high):w=QDoubleSpinBox();w.setRange(low,high);w.setDecimals(3);w.valueChanged.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _combo(self,name,values):w=QComboBox();w.addItems(values);w.currentTextChanged.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def _check(self,name):w=QCheckBox();w.toggled.connect(self.apply);self.controls[name]=w;self.form.addRow(name.replace("_"," ").title(),w)
    def set_element(self,element):
        self.element=element;self.loading=True;label=element.custom_label or element.text or element.sensor_id or element.kind;self.selected_title.setText(f"SELECTED  ·  {label}")
        for name,w in self.controls.items():
            value=getattr(element,name)
            if isinstance(w,(QLineEdit,ColorField)):w.setText(str(value))
            elif isinstance(w,QFontComboBox):w.setCurrentFont(QFont(str(value)))
            elif isinstance(w,QComboBox):w.setCurrentText(str(value))
            elif isinstance(w,QCheckBox):w.setChecked(bool(value))
            else:w.setValue(value)
        self.loading=False
        self._apply_relevance(element.kind)
    def _apply_relevance(self,kind):
        sensor_kinds={"text value","label + value","horizontal bar","vertical bar","gauge","line graph","sparkline","percentage","icon + value"};text_kinds={"text value","label + value","percentage","icon + value","static label","clock","date"};range_kinds={"horizontal bar","vertical bar","gauge","line graph","sparkline","percentage"}
        visibility={
            "text":kind in {"static label"},"sensor_id":kind in sensor_kinds,"provider":kind in sensor_kinds,"custom_label":kind in sensor_kinds,"format_string":kind in sensor_kinds|{"clock","date"},"unit":kind in sensor_kinds,"decimals":kind in sensor_kinds,"prefix":kind in sensor_kinds,"suffix":kind in sensor_kinds,
            "font_family":kind in text_kinds,"font_size":kind in text_kinds,"font_weight":kind in text_kinds,"bold":kind in text_kinds,"text_style":kind in text_kinds,"align":kind in text_kinds,"vertical_align":kind in text_kinds,"minimum":kind in range_kinds,"maximum":kind in range_kinds,"image":kind in {"image","icon + value"},"rotation":kind=="image","brightness":kind=="image","preserve_aspect":kind=="image","outline_color":kind in text_kinds,"outline_width":kind in text_kinds,"shadow_color":kind in text_kinds,"shadow_offset":kind in text_kinds,
        }
        for name,shown in visibility.items():
            widget=self.controls[name];widget.setVisible(shown);label=next((form.labelForField(widget) for form in self.forms.values() if form.labelForField(widget)),None)
            if label:label.setVisible(shown)
    def apply(self,*_):
        if self.loading or not self.element:return
        for name,w in self.controls.items():
            value=w.text() if isinstance(w,(QLineEdit,ColorField)) else w.currentFont().family() if isinstance(w,QFontComboBox) else w.currentText() if isinstance(w,QComboBox) else w.isChecked() if isinstance(w,QCheckBox) else w.value();setattr(self.element,name,value)
        self.changed.emit()


class SensorBrowser(QWidget):
    sensorChosen=Signal(object);bindingRequested=Signal(str,object);favoritesChanged=Signal();snapshotUpdated=Signal(object)
    RECOMMENDED=(
        ("CPU","CPU Temperature","cpu_temp"),("CPU","CPU Usage","cpu_usage"),("CPU","CPU Clock","cpu_clock"),("CPU","CPU Power","cpu_power"),
        ("GPU","GPU Temperature","gpu_temp"),("GPU","GPU Hotspot","gpu_hotspot"),("GPU","GPU Usage","gpu_usage"),("GPU","GPU Clock","gpu_clock"),("GPU","GPU Memory Clock","gpu_memory_clock"),("GPU","GPU Power","gpu_power"),("GPU","VRAM Usage","vram_usage"),
        ("Memory","RAM Usage","ram_usage"),("Storage","SSD Temperature","ssd_temp"),("Network","Network Download","network_download"),("Network","Network Upload","network_upload"),
        ("FPS / Frametime","FPS","fps"),("FPS / Frametime","Frametime","frametime"),("Cooling","Fan RPM","fan_rpm"),("Cooling","Pump RPM","pump_rpm"),
    )
    SEMANTIC_IDS={"cpu_temp":"cpu.temperature","cpu_usage":"cpu.usage","cpu_clock":"cpu.clock","cpu_power":"cpu.power","gpu_temp":"gpu.temperature","gpu_hotspot":"gpu.hotspot","gpu_usage":"gpu.usage","gpu_clock":"gpu.clock","gpu_memory_clock":"gpu.memory_clock","gpu_power":"gpu.power","vram_usage":"gpu.memory_used","ram_usage":"memory.usage","ssd_temp":"storage.temperature","network_download":"network.download","network_upload":"network.upload","fps":"game.fps","frametime":"game.frametime","fan_rpm":"fan.rpm","pump_rpm":"pump.rpm"}
    def __init__(self,favorites,recent,parent=None):
        super().__init__(parent);self.favorites=favorites;self.recent=recent;self.records=[];self.snapshot=None;v=QVBoxLayout(self);self.provider_status=QLabel("Sensor providers have not been scanned");self.provider_status.setWordWrap(True);self.provider_status.setObjectName("muted");v.addWidget(self.provider_status);filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText("Search recommended sensors");self.provider=QComboBox();self.provider.addItem("All providers");self.category=QComboBox();self.category.addItems(["Recommended","CPU","GPU","Memory","Storage","Cooling","Network","FPS / Frametime","Favorites","All / Advanced"]);scan=QPushButton("Refresh");filters.addWidget(self.search);filters.addWidget(self.provider);filters.addWidget(self.category);filters.addWidget(scan);v.addLayout(filters);self.list=QListWidget();self.list.setSelectionMode(QAbstractItemView.SingleSelection);v.addWidget(self.list);row=QHBoxLayout();assign=QPushButton("Use selected sensor");self.alias=QLineEdit();self.alias.setPlaceholderText("formula alias, e.g. gpu_power");bind=QPushButton("Bind alias");favorite=QPushButton("★ Favorite / Unfavorite");row.addWidget(assign);row.addWidget(self.alias);row.addWidget(bind);row.addWidget(favorite);row.addStretch();v.addLayout(row);scan.clicked.connect(lambda:self.refresh(force=True));self.search.textChanged.connect(self.filter);self.provider.currentTextChanged.connect(self.filter);self.category.currentTextChanged.connect(self.filter);assign.clicked.connect(self.choose);bind.clicked.connect(self.bind_alias);favorite.clicked.connect(self.toggle_favorite);self.list.itemDoubleClicked.connect(lambda _:self.choose());self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(1000);self.refresh_timer.timeout.connect(self.refresh)
    def refresh(self,force=False):
        from .sensors import Aida64Provider,AfterburnerProvider,CachedSensorService,HwinfoProvider,NativeBasicProvider,RtssProvider
        if not hasattr(self,"sensor_service"):self.sensor_service=CachedSensorService((HwinfoProvider(),AfterburnerProvider(),RtssProvider(),Aida64Provider(),NativeBasicProvider()))
        snapshot=self.sensor_service.poll(force=force);self.snapshot=snapshot;self.records=list(snapshot.values);hw=next((x for x in snapshot.provider_status if x.name=="HWiNFO"),None);self.provider_status.setText(f"HWiNFO connected · {hw.values_read} live sensors" if hw and hw.available else "HWiNFO unavailable — start HWiNFO and enable Settings → Shared Memory Support. Oni reconnects automatically.");self.provider.blockSignals(True);self.provider.clear();self.provider.addItems(["All providers",*sorted({x.provider for x in self.records})]);self.provider.blockSignals(False);self.filter();self.snapshotUpdated.emit(snapshot)
    def showEvent(self,event):super().showEvent(event);self.refresh(force=True);self.refresh_timer.start()
    def hideEvent(self,event):self.refresh_timer.stop();super().hideEvent(event)
    def filter(self,*_):
        needle=self.search.text().casefold();provider=self.provider.currentText();category=self.category.currentText();self.list.clear()
        if category!="All / Advanced":
            for group,label,alias in self.RECOMMENDED:
                resolved=resolve_semantic_sensor(alias,self.records);qid=resolved.definition.qualified_id if resolved else "";is_favorite=qid in self.favorites
                if category=="Favorites" and not is_favorite:continue
                if category not in {"Recommended","Favorites",group}:continue
                actual=f"{resolved.provider} · {resolved.name}  {resolved.value} {resolved.unit}" if resolved else "Not currently available · --"
                text=f"{'★ ' if is_favorite else ''}{label}\n    {actual}"
                if needle not in text.casefold() or resolved and provider not in {"All providers",resolved.provider}:continue
                item=QListWidgetItem(text);item.setData(Qt.UserRole,resolved);item.setData(Qt.UserRole+1,alias);self.list.addItem(item)
            return
        ordered=sorted(self.records,key=lambda x:(x.definition.qualified_id not in self.favorites,x.definition.qualified_id not in self.recent,x.provider,x.category,x.name))
        for value in ordered:
            text=f"{'★ ' if value.definition.qualified_id in self.favorites else ''}{value.provider} · {value.category} · {value.name}  {value.value} {value.unit}"
            if needle not in text.casefold() or provider not in {"All providers",value.provider}:continue
            item=QListWidgetItem(text);item.setData(Qt.UserRole,value);self.list.addItem(item)
        if not self.records:self.list.addItem("No active provider currently exposes sensor values")
    def choose(self):
        item=self.list.currentItem();value=item.data(Qt.UserRole) if item else None;alias=item.data(Qt.UserRole+1) if item else None
        if value:
            qid=value.definition.qualified_id
            if qid in self.recent:self.recent.remove(qid)
            self.recent.insert(0,qid);del self.recent[20:];self.sensorChosen.emit(value)
        elif alias:self.sensorChosen.emit({"semantic_id":self.SEMANTIC_IDS[alias],"label":item.text().splitlines()[0].lstrip("★ ")})
    def toggle_favorite(self):
        item=self.list.currentItem();value=item.data(Qt.UserRole) if item else None
        if not value:return
        qid=value.definition.qualified_id
        if qid in self.favorites:self.favorites.remove(qid)
        else:self.favorites.append(qid)
        self.favoritesChanged.emit();self.filter()
    def bind_alias(self):
        item=self.list.currentItem();value=item.data(Qt.UserRole) if item else None;alias=self.alias.text().strip()
        if value and alias and alias.replace("_","").isalnum():self.bindingRequested.emit(alias,value)


class BackgroundSettingsDialog(QDialog):
    """Edits only the background layer; sensor/image geometry is untouched."""
    def __init__(self,layout,parent=None):
        super().__init__(parent);self.layout=layout;self.setWindowTitle("Theme Background");form=QFormLayout(self);self.source=QLineEdit(layout.background_image);choose=QPushButton("Choose…");row=QWidget();rh=QHBoxLayout(row);rh.setContentsMargins(0,0,0,0);rh.addWidget(self.source);rh.addWidget(choose);form.addRow("Image",row);self.fit=QComboBox();self.fit.addItems(("Fit","Fill","Center"));self.fit.setCurrentText(layout.background_fit.title());form.addRow("Mode",self.fit)
        self.x=QSpinBox();self.x.setRange(-4000,4000);self.x.setValue(layout.background_x);self.y=QSpinBox();self.y.setRange(-2000,2000);self.y.setValue(layout.background_y);self.zoom=QDoubleSpinBox();self.zoom.setRange(.1,8);self.zoom.setSingleStep(.05);self.zoom.setValue(layout.background_zoom);self.rotation=QSpinBox();self.rotation.setRange(-360,360);self.rotation.setValue(layout.background_rotation);self.opacity=QSpinBox();self.opacity.setRange(0,100);self.opacity.setValue(layout.background_opacity);self.brightness=QSpinBox();self.brightness.setRange(0,200);self.brightness.setValue(layout.background_brightness);self.dim=QSpinBox();self.dim.setRange(0,100);self.dim.setValue(layout.background_darken)
        for label,widget in (("X",self.x),("Y",self.y),("Zoom",self.zoom),("Rotation",self.rotation),("Opacity",self.opacity),("Background brightness",self.brightness),("Dim overlay",self.dim)):form.addRow(label,widget)
        actions=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel|QDialogButtonBox.Reset);form.addRow(actions);choose.clicked.connect(self.choose);actions.accepted.connect(self.accept);actions.rejected.connect(self.reject);actions.button(QDialogButtonBox.Reset).clicked.connect(self.reset)
    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose theme background","","Images (*.png *.jpg *.jpeg *.webp)")
        if path:self.source.setText(path)
    def reset(self):self.source.clear();self.fit.setCurrentText("Fill");self.x.setValue(0);self.y.setValue(0);self.zoom.setValue(1);self.rotation.setValue(0);self.opacity.setValue(100);self.brightness.setValue(100);self.dim.setValue(0)
    def apply(self):
        self.layout.background_source="custom_image" if self.source.text().strip() else "template_artwork";self.layout.background_image=self.source.text().strip();self.layout.background_fit=self.fit.currentText().casefold();self.layout.background_x=self.x.value();self.layout.background_y=self.y.value();self.layout.background_zoom=self.zoom.value();self.layout.background_rotation=self.rotation.value();self.layout.background_opacity=self.opacity.value();self.layout.background_brightness=self.brightness.value();self.layout.background_darken=self.dim.value()


class HardwareMonitorDesigner(QDialog):
    def __init__(self,settings,store,parent=None):
        super().__init__(parent);self.settings=settings;self.store=store;self.setWindowTitle("Hardware Monitor Designer");self.resize(1450,880)
        if len(settings.designer_geometry)==4:self.setGeometry(*settings.designer_geometry)
        self.current_target="0416:5408";self.current_profile=settings.active_profile;self.layout=None;self.template_previewing=False
        root=QVBoxLayout(self);top=QHBoxLayout();self.target=QComboBox();self.target.addItem('9.16" LCD',"0416:5408");self.target.addItem('6" LCD',"0416:5302");self.profile=QComboBox();self.profile.addItems(settings.profiles.keys());self.profile.setCurrentText(self.current_profile);self.template=QComboBox();self.layout_name=QLineEdit("Custom");self.layout_name.setMaximumWidth(180);load_template=QPushButton("Load template as editable");blank=QPushButton("New blank");save=QPushButton("Save layout");rename=QPushButton("Rename");remove=QPushButton("Delete");refresh=QPushButton("Refresh");top.addWidget(QLabel("LCD"));top.addWidget(self.target);top.addWidget(QLabel("Profile"));top.addWidget(self.profile);top.addWidget(QLabel("Layout"));top.addWidget(self.template);top.addWidget(self.layout_name);top.addWidget(load_template);top.addWidget(blank);top.addWidget(rename);top.addWidget(remove);top.addWidget(refresh);top.addStretch();top.addWidget(save);root.addLayout(top)
        toolbar=QHBoxLayout();add=QToolButton();add.setText("＋ Add Element");add.setPopupMode(QToolButton.InstantPopup);add_menu=QMenu(add)
        for label,callback in (("Sensor value",self.add_element),("Text",self.add_text),("Image / logo",self.add_image),("Bar",lambda:self.add_kind("horizontal bar")),("Gauge",lambda:self.add_kind("gauge")),("Graph",lambda:self.add_kind("line graph")),("Clock",lambda:self.add_kind("clock")),("Date",lambda:self.add_kind("date"))):add_menu.addAction(label).triggered.connect(callback)
        add.setMenu(add_menu);toolbar.addWidget(add);actions=(("Background",self.choose_background),("Reset background",self.reset_background),("Duplicate",self.duplicate),("Delete",self.delete),("Lock / Unlock",self.toggle_lock),("Group",self.group),("Ungroup",self.ungroup),("Bring forward",lambda:self.change_z(1)),("Send backward",lambda:self.change_z(-1)))
        for label,callback in actions:b=QPushButton(label);b.clicked.connect(callback);toolbar.addWidget(b)
        self.snap=QCheckBox("Snap to grid");self.guides=QCheckBox("Alignment guides");self.grid=QSpinBox();self.grid.setRange(1,100);toolbar.addWidget(self.snap);toolbar.addWidget(QLabel("Grid"));toolbar.addWidget(self.grid);toolbar.addWidget(self.guides);toolbar.addStretch();root.addLayout(toolbar)
        self.splitter=QSplitter();root.addWidget(self.splitter,1);self.layers=QListWidget();self.layers.setMinimumWidth(190);self.layers.setMaximumWidth(260);self.layers.setToolTip("Layers · check to show/hide; click to select; use Lock, Delete and z-order tools above");self.splitter.addWidget(self.layers);canvas_holder=QWidget();cv=QVBoxLayout(canvas_holder);self.scene=None;self.canvas=None;self.splitter.addWidget(canvas_holder);self.properties=PropertiesPanel();self.splitter.addWidget(self.properties);self.splitter.setSizes([210,820,360]);self.canvas_layout=cv;self.layers.itemClicked.connect(self.select_layer);self.layers.itemChanged.connect(self.layer_visibility_changed)
        self.browser=SensorBrowser(settings.sensor_favorites,settings.recent_sensors);root.addWidget(self.browser);runtime=QHBoxLayout();play=QPushButton("Play layout on selected LCD");overlay=QPushButton("Overlay on existing media");stop=QPushButton("Stop monitor output");runtime.addWidget(play);runtime.addWidget(overlay);runtime.addWidget(stop);runtime.addStretch();root.addLayout(runtime);buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Close);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);root.addWidget(buttons);play.clicked.connect(self.play_on_lcd);overlay.clicked.connect(self.overlay_on_lcd);stop.clicked.connect(self.stop_on_lcd)
        self.target.currentIndexChanged.connect(self.switch_target);self.profile.currentTextChanged.connect(self.switch_profile);self.template.currentTextChanged.connect(self.preview_template);load_template.clicked.connect(self.load_template);blank.clicked.connect(self.new_blank);save.clicked.connect(self.save);rename.clicked.connect(self.rename_layout);remove.clicked.connect(self.delete_layout);refresh.clicked.connect(self.refresh_layout_choices);self.snap.toggled.connect(self.canvas_options);self.guides.toggled.connect(self.canvas_options);self.grid.valueChanged.connect(self.canvas_options);self.properties.changed.connect(self.property_changed);self.browser.sensorChosen.connect(self.use_sensor);self.browser.bindingRequested.connect(self.bind_formula_alias);self.browser.favoritesChanged.connect(lambda:self.store.save(self.settings));self.browser.snapshotUpdated.connect(self.sensor_snapshot);self.refresh_layout_choices();self.load_layout()
    def sensor_snapshot(self,snapshot):
        values={value.definition.qualified_id:value.value for value in snapshot.values}
        roles={"cpu.usage":"cpu_usage","cpu.temperature":"cpu_temp","cpu.clock":"cpu_clock","cpu.power":"cpu_power","gpu.usage":"gpu_usage","gpu.temperature":"gpu_temp","gpu.hotspot":"gpu_hotspot","gpu.clock":"gpu_clock","gpu.memory_clock":"gpu_memory_clock","gpu.power":"gpu_power","gpu.memory_used":"vram_usage","memory.usage":"ram_usage","storage.temperature":"ssd_temp","network.download":"network_download","network.upload":"network_upload","game.fps":"fps","game.frametime":"frametime","fan.rpm":"fan_rpm","pump.rpm":"pump_rpm"}
        for semantic,alias in roles.items():
            resolved=resolve_semantic_sensor(alias,snapshot.values);values[semantic]=resolved.value if resolved else None
        self.scene.set_live_values(values)
    def play_on_lcd(self):
        if not self.save():return
        owner=self.parent()
        if owner and hasattr(owner,"start_monitor_layout"):owner.start_monitor_layout(self.current_target,deepcopy(self.layout))
    def overlay_on_lcd(self):
        if not self.save():return
        owner=self.parent()
        if owner and hasattr(owner,"start_monitor_overlay"):owner.start_monitor_overlay(self.current_target,deepcopy(self.layout))
    def stop_on_lcd(self):
        owner=self.parent()
        if owner and hasattr(owner,"stop_monitor_layout"):owner.stop_monitor_layout(self.current_target)
    def saved_raw(self):return self.settings.monitor_layouts.get(self.current_profile,{}).get(self.current_target)
    def load_layout(self):
        self.template_previewing=False
        raw=self.saved_raw();self.layout=MonitorLayout.from_dict(raw) if raw else MonitorLayout("Custom",self.current_target,1920 if self.current_target.endswith("5408") else 1280,462 if self.current_target.endswith("5408") else 480)
        self.layout_name.setText(self.layout.name)
        if self.canvas:self.canvas_layout.removeWidget(self.canvas);self.canvas.deleteLater()
        self.scene=DesignerScene(self.layout,self);self.canvas=CanvasView(self.scene);self.canvas_layout.addWidget(self.canvas);self.scene.elementSelected.connect(self.select_element);self.scene.changed.connect(self.canvas_changed);self.scene.deleteRequested.connect(self.delete);self.scene.duplicateRequested.connect(self.duplicate);self.snap.setChecked(self.layout.snap_to_grid);self.guides.setChecked(self.layout.alignment_guides);self.grid.setValue(self.layout.grid_size);self.refresh_layers()
    def save_current(self):
        if not self.template_previewing:self.settings.monitor_layouts.setdefault(self.current_profile,{})[self.current_target]=self.layout.to_dict()
    def layout_library(self):return self.settings.monitor_layout_library.setdefault(self.current_target,{})
    def refresh_layout_choices(self,selected=None):
        selected=selected or self.template.currentText() or "Custom";names=["Custom",*sorted(templates(self.current_target)),*sorted(name for name in self.layout_library() if name not in templates(self.current_target))]
        self.template.blockSignals(True);self.template.clear();self.template.addItems(names);self.template.setCurrentText(selected if selected in names else "Custom");self.template.blockSignals(False)
        owner=self.parent()
        if owner and hasattr(owner,"_refresh_monitor_template_options"):
            for card in owner.card_by_id.values():owner._refresh_monitor_template_options(card)
    def save(self):
        entered=self.layout_name.text().strip();name=self.layout.name.strip() if entered in {"","Custom"} and self.layout.name.strip() not in {"","Custom"} else entered or self.layout.name.strip()
        if not name or name=="Custom":
            name,ok=QInputDialog.getText(self,"Save monitor layout","Layout name:",text="My Monitor Layout")
            if not ok or not name.strip():return False
            name=name.strip()
        if name in templates(self.current_target):QMessageBox.warning(self,"Reserved layout name","Choose a name different from the built-in layouts.");return False
        self.template_previewing=False;self.layout.name=name;raw=self.layout.to_dict();self.layout_library()[name]=deepcopy(raw);self.settings.monitor_layouts.setdefault(self.current_profile,{})[self.current_target]=deepcopy(raw);self.settings.monitor_templates[self.current_target]=name;self.store.save(self.settings);self.layout_name.setText(name);self.refresh_layout_choices(name);return True
    def rename_layout(self):
        old=self.layout.name
        if old not in self.layout_library():QMessageBox.information(self,"User layout required","Select or save a user layout before renaming it.");return False
        name,ok=QInputDialog.getText(self,"Rename monitor layout","Layout name:",text=old)
        if not ok or not name.strip() or name.strip()==old:return False
        name=name.strip()
        if name in templates(self.current_target) or name in self.layout_library():QMessageBox.warning(self,"Name already used","Choose a unique user layout name.");return False
        raw=self.layout_library().pop(old);raw["name"]=name;self.layout_library()[name]=raw;self.layout.name=name;self.layout_name.setText(name)
        for profile_layouts in self.settings.monitor_layouts.values():
            active=profile_layouts.get(self.current_target)
            if active and active.get("name")==old:profile_layouts[self.current_target]=deepcopy(raw)
        if self.settings.monitor_templates.get(self.current_target)==old:self.settings.monitor_templates[self.current_target]=name
        self.store.save(self.settings);self.refresh_layout_choices(name);return True
    def delete_layout(self):
        name=self.layout.name
        if name not in self.layout_library():QMessageBox.information(self,"User layout required","Only saved user layouts can be deleted.");return False
        if QMessageBox.question(self,"Delete monitor layout",f"Delete '{name}'?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return False
        self.layout_library().pop(name,None)
        for profile_layouts in self.settings.monitor_layouts.values():
            active=profile_layouts.get(self.current_target)
            if active and active.get("name")==name:profile_layouts[self.current_target]=MonitorLayout("Custom",self.current_target,1920 if self.current_target.endswith("5408") else 1280,462 if self.current_target.endswith("5408") else 480).to_dict()
        if self.settings.monitor_templates.get(self.current_target)==name:self.settings.monitor_templates.pop(self.current_target,None)
        self.store.save(self.settings);self.refresh_layout_choices("Custom");self.load_layout();return True
    def done(self,result):
        geometry=self.normalGeometry();self.settings.designer_geometry=[geometry.x(),geometry.y(),geometry.width(),geometry.height()];self.save_current();self.store.save(self.settings);super().done(result)
    def switch_target(self):self.save_current();self.current_target=self.target.currentData();self.refresh_layout_choices();self.load_layout()
    def switch_profile(self,name):self.save_current();self.current_profile=name;self.load_layout()
    def new_blank(self):
        if QMessageBox.question(self,"New blank layout","Replace the current canvas with a blank editable layout?")!=QMessageBox.Yes:return
        self.template_previewing=False;self.layout=MonitorLayout("Custom",self.current_target,1920 if self.current_target.endswith("5408") else 1280,462 if self.current_target.endswith("5408") else 480);self.layout_name.setText("Custom");self.load_scene()
    def preview_template(self,name):
        if name=="Custom":self.load_layout();return
        user=self.layout_library().get(name)
        if user:self.template_previewing=False;self.layout=MonitorLayout.from_dict(deepcopy(user));self.layout_name.setText(name);self.load_scene();return
        catalog=templates(self.current_target)
        if name in catalog:self.template_previewing=True;self.layout=deepcopy(catalog[name]);self.layout_name.setText(name);self.load_scene()
    def load_template(self):
        name=self.template.currentText()
        if name=="Custom":return
        user=self.layout_library().get(name);self.template_previewing=False;self.layout=MonitorLayout.from_dict(deepcopy(user)) if user else deepcopy(templates(self.current_target)[name])
        if not user:self.layout.name="Custom";self.layout_name.setText("Custom");self.template.blockSignals(True);self.template.setCurrentText("Custom");self.template.blockSignals(False)
        else:self.layout_name.setText(name)
        self.load_scene()
    def load_scene(self):self.scene.layout=self.layout;self.scene.controller=LayoutEditController(self.layout);self.scene.controller.set_enabled(True);self.scene.setSceneRect(0,0,self.layout.width,self.layout.height);self.scene.reload();self.snap.setChecked(self.layout.snap_to_grid);self.grid.setValue(self.layout.grid_size);self.guides.setChecked(self.layout.alignment_guides);self.refresh_layers()
    def add_element(self):
        z=max((x.z_index for x in self.layout.elements),default=0)+1;e=MonitorElement("label + value",40,40,z_index=z,custom_label="Sensor",format_string="{label} {value}{unit}");self.layout.elements.append(e);self.scene.reload();self.scene.items_by_id[e.id].setSelected(True)
        self.refresh_layers()
    def add_kind(self,kind):
        z=max((x.z_index for x in self.layout.elements),default=0)+1;width,height=(360,160) if kind in {"gauge","line graph"} else (360,64);e=MonitorElement(kind,self.layout.width//2-width//2,self.layout.height//2-height//2,width,height,sensor_id="cpu.usage" if kind not in {"clock","date"} else "",custom_label=kind.title(),z_index=z);self.layout.elements.append(e);self.scene.reload();self.scene.items_by_id[e.id].setSelected(True);self.refresh_layers()
    def add_text(self):
        z=max((x.z_index for x in self.layout.elements),default=0)+1;e=MonitorElement("static label",40,40,360,80,text="Custom text",font_size=36,z_index=z);self.layout.elements.append(e);self.scene.reload();self.scene.items_by_id[e.id].setSelected(True);self.refresh_layers()
    def add_image(self):
        path,_=QFileDialog.getOpenFileName(self,"Add image layer","","Images (*.png *.jpg *.jpeg *.webp)")
        if not path:return
        z=max((x.z_index for x in self.layout.elements),default=0)+1;e=MonitorElement("image",self.layout.width//2-120,self.layout.height//2-80,240,160,image=path,z_index=z,preserve_aspect=True);self.layout.elements.append(e);self.scene.reload();self.scene.items_by_id[e.id].setSelected(True);self.refresh_layers()
    def choose_background(self):
        dialog=BackgroundSettingsDialog(self.layout,self)
        if dialog.exec()==QDialog.Accepted:dialog.apply();self.load_scene()
    def reset_background(self):self.layout.background_source="template_artwork";self.layout.background_image="";self.load_scene()
    def refresh_layers(self):
        self.layers.blockSignals(True);self.layers.clear();background=QListWidgetItem("▣  Background");background.setFlags(background.flags() & ~Qt.ItemIsSelectable);self.layers.addItem(background)
        for element in sorted(self.layout.elements,key=lambda x:x.z_index,reverse=True):
            label=element.custom_label or element.text or element.sensor_id or element.kind;item=QListWidgetItem(f"{'🔒' if element.locked else '◉'}  {label}");item.setData(Qt.UserRole,element.id);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if element.visible else Qt.Unchecked);self.layers.addItem(item)
        self.layers.blockSignals(False)
    def layer_visibility_changed(self,item):
        element_id=item.data(Qt.UserRole)
        element=next((e for e in self.layout.elements if e.id==element_id),None)
        if element is None:return
        if self.scene.controller.set_visibility(element_id,item.checkState()==Qt.Checked):
            self.scene.reload();self.scene.changed.emit();self.refresh_layers()
    def select_layer(self,item):
        element_id=item.data(Qt.UserRole)
        if not element_id:return
        self.scene.clearSelection();scene_item=self.scene.items_by_id.get(element_id)
        if scene_item:scene_item.setSelected(True);self.select_element(element_id)
    def selected(self):return self.scene.selected_elements()
    def select_element(self,element_id):self.properties.set_element(next(x for x in self.layout.elements if x.id==element_id))
    def property_changed(self):
        if not self.properties.element:return
        item=self.scene.items_by_id[self.properties.element.id];item.prepareGeometryChange();item.setRect(0,0,self.properties.element.width,self.properties.element.height);snap=self.layout.snap_to_grid;self.layout.snap_to_grid=False
        try:item.setPos(self.properties.element.x,self.properties.element.y)
        finally:self.layout.snap_to_grid=snap
        item.setZValue(self.properties.element.z_index);item._sync_flags();item.update();self.scene.update()
    def canvas_changed(self):
        selected=self.selected()
        if len(selected)==1:self.properties.set_element(selected[0])
    def duplicate(self):
        copies=[]
        for source in self.selected():
            raw=deepcopy(source);raw.id=uuid4().hex;raw.x=min(self.layout.width-raw.width,raw.x+self.layout.grid_size);raw.y=min(self.layout.height-raw.height,raw.y+self.layout.grid_size);raw.group_id="";copies.append(raw)
        self.layout.elements.extend(copies);self.scene.reload()
        for e in copies:self.scene.items_by_id[e.id].setSelected(True)
    def delete(self):
        ids={x.id for x in self.selected()};self.layout.elements[:]=[x for x in self.layout.elements if x.id not in ids];self.scene.reload();self.refresh_layers()
    def toggle_lock(self):
        for e in self.selected():e.locked=not e.locked
        self.scene.reload()
    def group(self):
        selected=self.selected()
        if len(selected)<2:return
        gid=uuid4().hex
        for e in selected:e.group_id=gid
    def ungroup(self):
        for e in self.selected():e.group_id=""
    def change_z(self,delta):
        for e in self.selected():e.z_index+=delta
        self.scene.reload()
    def canvas_options(self,*_):
        if not self.layout:return
        self.layout.snap_to_grid=self.snap.isChecked();self.layout.grid_size=self.grid.value();self.layout.alignment_guides=self.guides.isChecked();self.scene.update()
    def use_sensor(self,value):
        selected=self.selected()
        if selected:e=selected[0]
        else:self.add_element();e=self.selected()[0]
        if isinstance(value,dict):e.sensor_id=value["semantic_id"];e.provider="Semantic auto-bind";e.custom_label=value["label"]
        else:e.sensor_id=value.definition.qualified_id;e.provider=value.provider;e.unit=value.unit;e.custom_label=value.name
        e.format_string="{label} {value}{unit}";self.properties.set_element(e);self.scene.items_by_id[e.id].update();self.scene.update()
    def bind_formula_alias(self,alias,value):
        self.layout.bindings[alias]=value.definition.qualified_id
        if value.definition.qualified_id in self.settings.recent_sensors:self.settings.recent_sensors.remove(value.definition.qualified_id)
        self.settings.recent_sensors.insert(0,value.definition.qualified_id);del self.settings.recent_sensors[20:]


class ThemeGalleryDialog(QDialog):
    """Visual factory-theme browser; applying always stores an editable copy."""
    def __init__(self,settings,store,parent=None):
        super().__init__(parent);self.settings=settings;self.store=store;self.setWindowTitle("Oni Sensor Themes");self.resize(1180,760)
        root=QVBoxLayout(self);header=QHBoxLayout();header.addWidget(QLabel("<h1>Sensor Themes</h1><span style='color:#8290a4'>Original Oni designs · choose, apply, then customize</span>"));header.addStretch();self.target=QComboBox();self.target.addItem('Trofeo Vision 9.16 · 1920×480',"0416:5408");self.target.addItem('Trofeo Vision 6.86 · 1280×480',"0416:5302");header.addWidget(self.target);root.addLayout(header)
        self.list=QListWidget();self.list.setViewMode(QListWidget.IconMode);self.list.setResizeMode(QListWidget.Adjust);self.list.setMovement(QListWidget.Static);self.list.setIconSize(QSize(420,126));self.list.setGridSize(QSize(450,176));self.list.setSpacing(10);root.addWidget(self.list,1)
        row=QHBoxLayout();self.apply_button=QPushButton("Apply Theme");self.edit_button=QPushButton("Edit Copy in Designer");close=QPushButton("Close");row.addStretch();row.addWidget(self.apply_button);row.addWidget(self.edit_button);row.addWidget(close);root.addLayout(row)
        self.target.currentIndexChanged.connect(self.reload);self.apply_button.clicked.connect(self.apply);self.edit_button.clicked.connect(self.edit);self.list.itemDoubleClicked.connect(lambda _:self.edit());close.clicked.connect(self.accept);self.reload()
    def _icon(self,layout):
        values={"cpu.temperature":58,"cpu.usage":42,"cpu.power":88,"gpu.temperature":63,"gpu.usage":87,"gpu.power":286,"gpu.memory_used":9.4,"memory.usage":54,"game.fps":144,"game.frametime":6.9,"network.download":412}
        image=MonitorRenderer(layout).render(values);image.thumbnail((420,126));data=image.tobytes("raw","RGB");q=QImage(data,image.width,image.height,image.width*3,QImage.Format_RGB888).copy();return QIcon(QPixmap.fromImage(q))
    def reload(self):
        self.list.clear()
        for name,layout in templates(self.target.currentData()).items():
            if name in {"Gaming","Performance","Temperatures","Minimal"}:continue
            item=QListWidgetItem(self._icon(layout),name);item.setData(Qt.UserRole,name);item.setToolTip("Factory master remains unchanged; Apply creates an editable profile copy.");self.list.addItem(item)
        if self.list.count():self.list.setCurrentRow(0)
    def selected_layout(self):
        item=self.list.currentItem();return deepcopy(templates(self.target.currentData())[item.data(Qt.UserRole)]) if item else None
    def apply(self):
        layout=self.selected_layout()
        if not layout:return
        self.settings.monitor_layouts.setdefault(self.settings.active_profile,{})[self.target.currentData()]=layout.to_dict();self.settings.monitor_templates[self.target.currentData()]=layout.name;self.store.save(self.settings)
        owner=self.parent()
        if owner and hasattr(owner,"card_by_id"):owner.card_by_id[self.target.currentData()].monitor_template.setCurrentText(layout.name)
    def edit(self):
        self.apply();designer=HardwareMonitorDesigner(self.settings,self.store,self.parent());designer.current_target=self.target.currentData();designer.target.setCurrentIndex(max(0,designer.target.findData(designer.current_target)));designer.load_layout();designer.exec();self.reload()
