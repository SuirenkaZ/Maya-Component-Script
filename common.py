import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om
import maya.OpenMayaUI as omui
from PySide2.QtWidgets import QSizePolicy,QTabBar,QStackedWidget,QFrame,QAction,QComboBox,QListWidget,QDialog,QCheckBox,QTabWidget,QPushButton,QLabel,QLineEdit,QMainWindow,QDialog,QFileDialog,QMessageBox,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,QMenuBar,QMenu,QTableWidget,QScrollArea,QStyle
from PySide2.QtCore import Qt,Signal,QSize
from PySide2.QtWidgets import QApplication
from PySide2.QtGui import QFont,QIcon,QPixmap
from shiboken2 import wrapInstance
from collections import defaultdict
import os,sys,shutil,subprocess

def maya_main_window():
    try:
        main_window = omui.MQtUtil.mainWindow()
        if main_window is None:
            print("无法获取Maya主窗口")
            return None
        return wrapInstance(int(main_window),QWidget)
    except Exception as e:
        print(f"获取Maya主窗口失败:{e}")
        return None
        
class MaterialManager():
    
    def iter_all_children(self,root_transform=None, api_type=None):
        """
        从指定的 transform 节点开始，遍历其下所有 DAG 子节点，
        返回所有符合指定 API 类型的节点（MObject）。

        参数:
            root_transform (str)
                Maya 场景中的 transform 节点名称，例如:
                "|group1" 或 "group1"

            api_type (int)
                Maya API 中的节点功能类型枚举，例如:
                om.MFn.kMesh
                om.MFn.kTransform
                om.MFn.kCamera
                om.MFn.kLight

        返回:
            List[om.MObject]
                一个列表，列表中每一项都是一个 MObject，
                表示一个符合 api_type 的 DAG 节点。

                注意:
                - 返回的是“节点对象”，不是名字
                - 可直接用于 MFnDependencyNode / MFnMesh 等 API 类
        """

        # --------------------------------------------------
        # 1. 将节点名称转换为 MDagPath
        # --------------------------------------------------
        # MSelectionList 用于在“字符串名称”和“API 对象”之间转换
        sel = om.MSelectionList()
        sel.add(root_transform)

        # getDagPath 返回的是 MDagPath 类型
        # 代表 DAG 中的一个具体路径（包含 instance 信息）
        root_dag_path = sel.getDagPath(0)

        # --------------------------------------------------
        # 2. 创建 DAG 遍历器
        # --------------------------------------------------
        # kDepthFirst:
        #   深度优先遍历（先子节点，再兄弟节点）
        #
        # kInvalid:
        #   不限制节点类型，遍历所有 DAG 节点
        it = om.MItDag(
            om.MItDag.kDepthFirst,
            om.MFn.kInvalid
        )

        # reset 的作用是：
        #   指定遍历的“起始节点”
        #   否则会从世界根节点 | 开始遍历
        it.reset(root_dag_path)

        # --------------------------------------------------
        # 3. 遍历并筛选节点
        # --------------------------------------------------
        result = []

        while not it.isDone():

            # 获取当前遍历到的 DAG 路径
            # 返回类型: om.MDagPath
            dag_path = it.getPath()

            # 从 DAG 路径中取出节点对象
            # 返回类型: om.MObject
            node = dag_path.node()

            # 判断该节点是否支持指定的 API 功能类型
            # hasFn 返回 bool
            if node.hasFn(api_type):
                result.append(node)

            it.next()

        return result
    
    def get_mesh_shading_engine(self,mesh_shape_list):
        """
        mesh_shape_list : List[om.MObject] （mesh shape）
        return           : List[om.MObject] （shadingEngine）
        """

        if not mesh_shape_list:
            return []

        shading_engines = []

        for mesh_obj in mesh_shape_list:

            # 从 MObject 获取一个 MDagPath（instance-aware）
            dag_path = om.MDagPath.getAPathTo(mesh_obj)

            instance_number = dag_path.instanceNumber()

            mesh_fn = om.MFnMesh(dag_path)

            # shader_array : om.MObjectArray
            shader_array, _ = mesh_fn.getConnectedShaders(instance_number)

            for i in shader_array:
                shading_engines.append(i)

        return shading_engines

    
    def itter_shading_engine(self,sg_obj=None,api_type=None):
        '''
        遍历材质节点,提取所有file节点
        '''
        it = om.MItDependencyGraph(
            sg_obj,
            om.MItDependencyGraph.kUpstream,
            om.MItDependencyGraph.kBreadthFirst,
            om.MItDependencyGraph.kNodeLevel
        )
        
        file_texture_node = []
        file_node_name = None
        while not it.isDone():
            #返回mobj
            node = it.currentNode()
            #print(node)
            if node.apiType() == api_type:
                file_node_name = om.MFnDependencyNode(node).name()
                file_texture_node.append(file_node_name)
                
            it.next()
        
        return file_texture_node
    
    def get_texture_node(self,root_transform=None,api_type=None):
        '''
        获取输入transform节点下的所有贴图节点
        root_transform > 根节点
        api_type > 返回的节点类型
        '''
        mesh_mobj_list = self.iter_all_children(root_transform,api_type=api_type)
        #print("mesh_mobj_list>>>",mesh_mobj_list)
        shading_engine = self.get_mesh_shading_engine(mesh_mobj_list)
        #print("shading_engine>>>",shading_engine)
        
        temp_file_texture_node = []
        for sg_node in shading_engine:
            temp = self.itter_shading_engine(sg_obj = sg_node,api_type=om.MFn.kFileTexture)
            
            temp_file_texture_node.extend(temp)
        
        file_node = list(set(temp_file_texture_node))
        
        return file_node

class ExportManager():
    
    def __init__(self):
        pass
        
    def check_plugin(self,plugin_name = None):
        '''
        检测maya的plugin插件是否开启
        plugin_name > 要检测的插件名称
        '''
        
        if not plugin_name:
            raise "plugin name is None"
            
        is_loaded = cmds.pluginInfo(plugin_name,query=True,loaded=True)
        return is_loaded
        
    def assemble_file_path(self,scene = None,node_name=None,file_path=None,file_name=None,file_type="ma"):
        
        if not file_path:
            cmds.error("file path is None")
        
        if not file_name:
            cmds.error("file name is None")
        
        name = f"{scene}_{file_name}.{node_name}"
        
        path = f"{file_path}/{name}.{file_type}"
        
        return path
    
    def export_gpu_cache(self,file_path = None,file_name = None,node_name=None):
        '''
        导出gpucache
        file_path > 文件路径
        file_name > 导出文件路径  不能带文件后缀
        node_name > 导出物体    
        '''
        
        if not cmds.pluginInfo("gpuCache",query=True,loaded=True):
            cmds.error("Unload Plugin gpuCache")
        
        if file_path == None:
            cmds.error("file path is none")
        if file_name == None:
            cmds.error("file name is none")
        if node_name == None:
            cmds.error("export object is none")
        
        #gpuCache无法导出空组,导出前检查是否为空组
        if cmds.listRelatives(node_name,children=True):
            cmds.select(node_name)
            mel_cmd = f'gpuCache -optimize -writeMaterials -dataFormat "abc" -directory "{file_path}" -fileName "{file_name}" -startTime 1 -endTime 1 {node_name};'
            try:
                mel.eval(mel_cmd)
                print("导出gpuCache成功")
            except Exception as e:
                cmds.error(f"导出gpuCache错误 > {e}")
        else:
            print(f"{node_name}为空组,跳过")
        
    def export_arnold_ass(self,file_path = None,node_name = None,start_frame=1,end_frame=1):
        '''
        导出Arnold代理文件
        file_name > 导出文件名称  > 路径+文件名称+.ass > W:/WXR/temp/zjx/Script/temp/.test.ass
        selected > 是否导出选择代理
        
        '''
        if not file_path:
            cmds.error("file name is none")
            
        cmds.select(node_name)
        print(file_path)
        try:
            cmds.arnoldExportAss(filename = file_path,selected = True)
        except Exception as e:
            
            raise Exception(f"export ass error > {e}")
    
    def export_maya_file(self,object_name = None,file_path = None,file_format="ma"):
        '''
        根据file_path,file_name和file_format自动计算保存的文件path
        
        object_name > 导出物体名称 longName
        file_path > 导出文件路径
        file_format > 
            ma,mb
        '''
        
        if not object_name:
            cmds.error("object_name is None")
        
        if not file_path:
            cmds.error("file_path is None")
            
        file_type = None
        
        if file_format in ["ma","mb"]:
            if file_format == "ma":
                file_type = "mayaAscii"
            
            elif file_format == "mb":
                file_type = "mayaBinary"
        else:
            cmds.error("file_format type error")
        
        cmds.file(file_path,force=True,type=file_type,exportSelected=True)
    
    def export_abc(self,node_name = None,start_time=1,end_time=1,uv_write = True,file_path = None):
        if not self.check_plugin("AbcExport"):
            cmds.error("Plugin > Unloaded AbcExport")
        
        if not file_path:
            cmds.error("file path is None")
        
        job = " ".join([
        f"-frameRange {start_time} {end_time}",
        "-worldSpace",
        "-uvWrite",
        f"-root {node_name}",
        f'-file "{file_path}"'
        ])
        
        print("job",job)
        
        cmds.AbcExport(j = job)
    
class NodeCreator():
    
    def create_locator(self,node_name = "RootLocator",scale_x=0.5,scale_y=0.5,scale_z=0.5):
        '''
        创建定位器
        return
            Transform节点和Shape节点
        '''
        locator_temp = cmds.spaceLocator(name=node_name,position=[0,0,0])
        
        if not locator_temp:
            cmds.error("create_locator error")
        
        locator = cmds.listRelatives(locator_temp[0],children=True,fullPath=True)[0]

        cmds.setAttr(f"{locator}.localScaleX",scale_x)
        cmds.setAttr(f"{locator}.localScaleY",scale_y)
        cmds.setAttr(f"{locator}.localScaleZ",scale_z)
        
        return locator_temp[0],locator
    
    def create_group(self,node_name="DefaultGrp",parent=None,lock_transform=False):
        '''
        创建组
        '''
        
        if parent:
            group_node = cmds.group(name=node_name,empty=True,parent=parent)
        else:
            group_node = cmds.group(name=node_name,empty=True)
        
        if lock_transform:
            cmds.setAttr(f"{group_node}.translateX",lock=True)
            cmds.setAttr(f"{group_node}.translateY",lock=True)
            cmds.setAttr(f"{group_node}.translateZ",lock=True)
            
            cmds.setAttr(f"{group_node}.rotateX",lock=True)
            cmds.setAttr(f"{group_node}.rotateY",lock=True)
            cmds.setAttr(f"{group_node}.rotateZ",lock=True)
            
            cmds.setAttr(f"{group_node}.scaleX",lock=True)
            cmds.setAttr(f"{group_node}.scaleY",lock=True)
            cmds.setAttr(f"{group_node}.scaleZ",lock=True)

class UI(QMainWindow):
    
    def __init__(self,parent=maya_main_window(),file_path=None,project_code=None,scene_prefix=None):
        super().__init__(parent)
        self.setFixedSize(400,700)
        self.setWindowTitle("Component Tool 2022")
        central_widget = QWidget()
        self.central_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)
        
        self.resolution_type = ["proxyRes","midRes","hiRes"]
        self.operator = Operator(res_list=self.resolution_type)
        
        self.file_path = file_path
        self.project_code = project_code
        self.scene_prefix = scene_prefix

        self.create_ui()
        self.bind()
    
    def bind(self):
        self.create_locator_button.clicked.connect(self.operator.create_locator)
        self.export_selected_res_button.clicked.connect(self.export_selected_res_button_command)
        self.export_all_res_button.clicked.connect(self.export_all_res_button_command)
        self.update_source_button.clicked.connect(self.update_source_button_command)
        self.screen_btn.clicked.connect(self.screen_shot)
        
        self.import_abc_button.clicked.connect(lambda :self.import_cache(cache_type="abc"))
        self.import_gpu_button.clicked.connect(lambda :self.import_cache(cache_type="gpuCache"))
        self.import_ass_button.clicked.connect(lambda :self.import_cache(cache_type="ass"))
        
        self.switch_abc_res_button.clicked.connect(self.repalce_select_res_command)
        self.switch_gpu_res_button.clicked.connect(self.repalce_select_res_command)
        self.switch_ass_res_button.clicked.connect(self.repalce_select_res_command)
        
        self.replace_abc_res_button.clicked.connect(self.repalce_all_res_command)
        self.replace_gpu_res_button.clicked.connect(self.repalce_all_res_command)
        self.replace_ass_res_button.clicked.connect(self.repalce_all_res_command)
        
        self.import_custom_res_button.clicked.connect(self.import_source)
        self.import_source_button.clicked.connect(self.import_source)

    def create_ui(self):
        self.create_tab_bar()
        self.create_export_ui()
        self.create_import_ui()

    def create_button(self,text):
        button = QPushButton(text)
        button.setFixedHeight(40)
        return button
    
    def create_tab_bar(self):
        
        self.tab_bar = QTabBar()
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setFixedWidth(350)
        self.tab_bar.addTab("导出")
        self.tab_bar.addTab("导入")
        self.tab_bar.addTab("大纲")

        self.stack = QStackedWidget()
        import_widget = QWidget()
        self.import_layout = QVBoxLayout(import_widget)

        export_widget = QWidget()
        self.export_layout = QVBoxLayout(export_widget)
        
        preview_widget = QWidget()
        self.preview_widget = QVBoxLayout(preview_widget)

        self.stack.addWidget(export_widget)
        self.stack.addWidget(import_widget)
        self.stack.addWidget(preview_widget)
        self.central_layout.addWidget(self.tab_bar)
        self.central_layout.addWidget(self.stack)

        self.tab_bar.currentChanged.connect(self.stack.setCurrentIndex)

    def create_export_ui(self):
        
        input_widget = QWidget()
        
        init_label=QLabel("创建大纲层级")
        export_label = QLabel("导出文件类型选项")
        screen_label = QLabel("预览图")

        input_layout = QHBoxLayout(input_widget)
        input_label = QLabel("资产名称")
        self.input_text = QLineEdit()
        self.input_text.setPlaceholderText("请输入组件名称")
        input_layout.addWidget(input_label)
        input_layout.addWidget(self.input_text)

        self.create_locator_button = self.create_button("创建 Locator")

        check_box_widget_01 = QWidget()
        check_box_widget_02 = QWidget()
        check_box_layout_01 = QHBoxLayout(check_box_widget_01)
        check_box_layout_02 = QHBoxLayout(check_box_widget_02)
        self.check_ma = QCheckBox("导出 MA")
        self.check_ass = QCheckBox("导出 ASS")
        self.check_gpu_cache = QCheckBox("导出 GPU")
        self.check_abc = QCheckBox("导出 ABC")
        self.check_texture = QCheckBox("导出 TEX")
        
        self.check_ma.setChecked(True)
        self.check_ass.setChecked(True)
        self.check_gpu_cache.setChecked(True)
        self.check_abc.setChecked(True)
        self.check_texture.setChecked(True)

        check_box_layout_01.addWidget(self.check_ass)
        check_box_layout_01.addWidget(self.check_gpu_cache)
        check_box_layout_01.addWidget(self.check_abc)
        check_box_layout_01.addWidget(self.check_texture)
        check_box_layout_02.addWidget(self.check_ma)
        
        export_button_widget = QWidget()
        export_button_layout = QHBoxLayout(export_button_widget)
        export_button_layout.setContentsMargins(0,0,0,0)
        
        self.export_selected_res_button = self.create_button("导出选中 Res")
        self.export_all_res_button = self.create_button("导出所有 Res")
        export_button_layout.addWidget(self.export_selected_res_button)
        export_button_layout.addWidget(self.export_all_res_button)
        
        self.update_source_button = self.create_button("更新 Src")
        
        self.export_layout.addWidget(init_label)
        self.export_layout.addWidget(self.create_frame())
        self.export_layout.addWidget(self.create_locator_button)
        #self.export_layout.addSpacing(15)
        self.export_layout.addWidget(self.create_frame())
        
        self.export_layout.addWidget(input_widget)
        self.export_layout.addSpacing(15)
        
        self.export_layout.addWidget(export_label)
        self.export_layout.addWidget(self.create_frame())
        self.export_layout.addWidget(check_box_widget_01)
        self.export_layout.addWidget(check_box_widget_02)
        self.export_layout.addWidget(export_button_widget)
        #self.export_layout.addWidget(self.export_all_res_button)
        self.export_layout.addWidget(self.update_source_button)
        self.export_layout.addSpacing(15)
        
        self.export_layout.addWidget(screen_label)
        self.export_layout.addWidget(self.create_frame())
        
        screen_widget,self.preview_label,self.screen_btn = self.create_screen_shot_widget()
        
        self.export_layout.addWidget(screen_widget)

        self.export_layout.addStretch()

    def create_import_ui(self):
        import_abc_widget = QWidget()
        import_abc_layout = QHBoxLayout(import_abc_widget)
        import_abc_layout.setContentsMargins(2,2,2,2)
        
        switch_res_widget = QWidget()
        switch_res_layout = QHBoxLayout(switch_res_widget)
        switch_res_layout.setContentsMargins(2,2,2,2)
        
        replace_all_widget = QWidget()
        replace_all_layout = QHBoxLayout(replace_all_widget)
        replace_all_layout.setContentsMargins(2,2,2,2)
        
        import_label = QLabel("导入Cache选项")
        replace_label = QLabel("切换/替换Cache选项")
        import_ma_label = QLabel("导入当前选择Cache的Ma文件")
        replace_current_label = QLabel("切换当前选择节点")
        replace_all_label = QLabel("切换场景中所有节点")
        replace_all_label_widget = QWidget()
        replace_all_label_layout = QHBoxLayout(replace_all_label_widget)
        replace_all_label_layout.setContentsMargins(0,0,0,0)
        
        self.enabled_instance_check_box = QCheckBox("启用实例")
        self.enabled_instance_check_box.setChecked(True)
        self.enabled_instance_check_box.setToolTip("勾选后,将以实例对象替换场景中的节点")
        
        replace_all_label_layout.addWidget(replace_all_label)
        replace_all_label_layout.addSpacing(15)
        replace_all_label_layout.addWidget(self.enabled_instance_check_box)
        replace_all_label_layout.addStretch()
        
        self.import_abc_button = self.create_button("导入 Abc")
        self.import_gpu_button = self.create_button("导入 GPU Cache")
        self.import_ass_button = self.create_button("导入 Arnold Ass")
        
        self.switch_abc_res_button = self.create_button("切换选择 Res Abc")
        self.switch_abc_res_button.setProperty("action","abc")
        
        self.switch_gpu_res_button = self.create_button("切换选择 Res GPU")
        self.switch_gpu_res_button.setProperty("action","gpuCache")
        
        self.switch_ass_res_button = self.create_button("切换选择 Res Ass")
        self.switch_ass_res_button.setProperty("action","ass")
        
        self.replace_abc_res_button = self.create_button("切换全部 Res Abc")
        self.replace_abc_res_button.setToolTip("替换场景中所有Abc为选择的res")
        self.replace_abc_res_button.setProperty("action","abc")
        
        self.replace_gpu_res_button = self.create_button("切换全部 Res GPU")
        self.replace_gpu_res_button.setToolTip("替换场景中所有GPU为选择的res")
        self.replace_gpu_res_button.setProperty("action","gpuCache")
        
        self.replace_ass_res_button = self.create_button("切换全部 Res Ass")
        self.replace_ass_res_button.setToolTip("替换场景中所有Ass为选择的res")
        self.replace_ass_res_button.setProperty("action","ass")
        
        import_abc_layout.addWidget(self.import_abc_button)
        import_abc_layout.addWidget(self.import_gpu_button)
        import_abc_layout.addWidget(self.import_ass_button)
        
        switch_res_layout.addWidget(self.switch_abc_res_button)
        switch_res_layout.addWidget(self.switch_gpu_res_button)
        switch_res_layout.addWidget(self.switch_ass_res_button)
        
        replace_all_layout.addWidget(self.replace_abc_res_button)
        replace_all_layout.addWidget(self.replace_gpu_res_button)
        replace_all_layout.addWidget(self.replace_ass_res_button)

        self.list_widget = QListWidget()
        self.list_widget.addItems(self.resolution_type)
        self.list_widget.setCurrentRow(0)
        self.list_widget.setFixedHeight(100)
        
        self.import_custom_res_button = self.create_button("导入选择Res ma文件")
        self.import_custom_res_button.setProperty("action","res")
        self.import_custom_res_button.setToolTip("选择一个或者多个缓存类型,替换为指定的Res对应的ma文件")
        
        self.import_source_button = self.create_button("导入Source ma文件")
        self.import_source_button.setProperty("action","source")
        self.import_source_button.setToolTip("选择一个或者多个缓存类型,替换为Source ma文件")
        
        self.import_layout.addWidget(import_label)
        self.import_layout.addWidget(self.create_frame())
        self.import_layout.addWidget(import_abc_widget)
        self.import_layout.addSpacing(15)
        
        self.import_layout.addWidget(replace_label)
        self.import_layout.addWidget(self.create_frame())
        self.import_layout.addWidget(self.list_widget)
        self.import_layout.addWidget(replace_current_label)
        
        self.import_layout.addWidget(self.create_frame())
        
        self.import_layout.addWidget(switch_res_widget)
        self.import_layout.addSpacing(15)
        self.import_layout.addWidget(replace_all_label_widget)
        self.import_layout.addWidget(self.create_frame())
        self.import_layout.addWidget(replace_all_widget)
        self.import_layout.addSpacing(15)
        
        self.import_layout.addWidget(import_ma_label)
        self.import_layout.addWidget(self.create_frame())
        self.import_layout.addWidget(self.import_custom_res_button)
        self.import_layout.addWidget(self.import_source_button)
        
        self.import_layout.addStretch()

    def create_frame(self):
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator
    
    def create_screen_shot_widget(self):
        screen_widget = QWidget()
        layout = QVBoxLayout(screen_widget)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        preview_label = QLabel("调整相机角度后点击截图生成图片预览")
        preview_label.setFixedSize(288,162)
        preview_label.setStyleSheet(
            "QLabel{border:1px solid rgba(255,255,255,40); border-radius:6px;}"
        )
        preview_label.setAlignment(Qt.AlignCenter)
       # preview_label.setMinimumSize(QSize(x_size=200, y_size=200))
        #preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        capture_btn = QPushButton("截屏")
        capture_btn.setFixedHeight(40)

        layout.addWidget(preview_label,alignment=Qt.AlignCenter)
        layout.addWidget(capture_btn)
        
        return screen_widget,preview_label,capture_btn
    
    def get_user_input(self):
                    
        return self.input_text.text()
    
    def export_selected_res_button_command(self):
        '''
        导出当前选择组
        导出前将把组的parent变换设置为0,并且检查povit轴心
        '''
        sel = cmds.ls(selection=True,long=True)
        if not sel:
            cmds.error("未选择任何节点")
            
        node_name = sel[0]
        asset_name = self.get_user_input()
        if not asset_name:
            om.MGlobal.displayError("资产名称不能为空!")
            return
        #获取父对象locator的transform节点
        parent_node = cmds.listRelatives(node_name,parent=True,fullPath=True)
        #保存原始位置
        original_pos,original_rot,original_scale = self.operator.get_transform(parent_node)
        
        try:
            #将物体移动到世界坐标中心
            self.operator.reset_transform(parent_node)
            #检查物体轴心是否在坐标原点
            if self.operator.check_pivot(parent_node):
            
                if self.check_ma.isChecked():
                    self.operator.export_select_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "ma"
                        )
                
                if self.check_abc.isChecked():
                    self.operator.export_select_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "abc"
                        )
                
                if self.check_gpu_cache.isChecked():
                    self.operator.export_select_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "gpuCache"
                        )
                        
                if self.check_ass.isChecked():
                    self.operator.export_select_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "ass"
                        )
        
        finally:
            #将物体设置回原始坐标
            self.operator.set_transform(parent_node,original_pos,original_rot,original_scale)
                
    def export_all_res_button_command(self):
        '''
        导出当前root下的所有组
        '''
        sel = cmds.ls(selection=True,long=True)
        if not sel:
            cmds.error("未选择任何节点")
            
        node_name = sel[0]
        asset_name = self.get_user_input()
        if not asset_name:
            om.MGlobal.displayError("资产名称不能为空!")
            return
            
        #保存原始位置
        original_pos,original_rot,original_scale = self.operator.get_transform(node_name)
        
        try:
            #将物体移动到世界坐标中心
            self.operator.reset_transform(node_name)
            #检查物体轴心是否在坐标原点
            if self.operator.check_pivot(node_name):
        
                if self.check_texture.isCheckable():
                    self.operator.copy_texture_to_target_file(node_name = node_name,path = self.file_path,project_code = self.project_code,
                                    scene=self.scene_prefix,asset_name=self.input_text.text())
                
                if self.check_ma.isChecked():
                    self.operator.export_child_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "ma"
                        )
                
                if self.check_abc.isChecked():
                    self.operator.export_child_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "abc"
                        )
                
                if self.check_gpu_cache.isChecked():
                    self.operator.export_child_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "gpuCache"
                        )
                        
                if self.check_ass.isChecked():
                    self.operator.export_child_res(node_name = node_name,
                                file_path = self.file_path,
                                asset_name = self.input_text.text(),
                                project_code = self.project_code,
                                scene = self.scene_prefix,
                                file_type = "ass"
                        )
        finally:
            
            #将物体设置回原始坐标
            self.operator.set_transform(node_name,original_pos,original_rot,original_scale)
    
    def repalce_select_res_command(self):
        current_clicked_button = self.sender()
        target_file_format = current_clicked_button.property("action")
        node_list = cmds.ls(selection=True,long=True)
        
        if node_list:
            for node in node_list:
                self.replace_select_res(sel_node = node,target_file_format = target_file_format)
        else:
            om.MGlobal.displayError("未选择任何节点!")
    
    def replace_select_res(self,sel_node=None,target_file_format=None):
        '''
        替换选择的分辨率组件
        如果用户选择的节点类型和需要替换的类型一致,则直接替换
        如果不一致,则删除掉原始节点后,重新导入
        导入后继承原始的变换以及parent层级
        node_list > 需要替换的节点
        target_file_format > 目标文件类型
        '''
        #记录不同类型切换导入时,重新parent的节点路径
        full_path = None
        #记录原始节点parent层级
        parent = cmds.listRelatives(sel_node,parent=True,fullPath=True)
        #记录导入的节点
        import_transform=None
    
        #获取当前选择节点的类型
        current_node_format = self.operator.get_file_format(sel_node)
        
        #后续添加导入信息报告可以修改
        if not current_node_format:
            #如果当前选择的物体不为插件导入的,则返回,不执行操作
            print(f"{current_node_format} 不为插件导入的节点,跳过")
            return
        
        #获取用户需要切换的分辨率
        target_res = self.list_widget.currentItem().text()
        
        #如果是同类型fileFormat节点替换,则修改路径
        if current_node_format == target_file_format:
            #print("相同类型节点")
            if target_file_format == "ass":
                self.operator.replace_ass_res(transform_node = sel_node,target_res_type=target_res)

                import_transform = sel_node
            elif target_file_format == "gpuCache":
                self.operator.replace_gpu_cache_res(transform_node = sel_node,target_res_type=target_res)

                import_transform = sel_node
            elif target_file_format == "abc":
                #获取abc Node节点的变换坐标
                original_pos,original_rotate,original_scale = self.operator.get_transform(sel_node)
                #导入新的res,并且继承变换坐标
                import_transform = self.operator.replace_abc_res(transform_node = sel_node,target_res_type=target_res,
                                target_pos=original_pos,target_rotate = original_rotate,
                                target_scale=original_scale)
        
            full_path = import_transform
                                
        #不同类型节点的替换
        else:
            '''
            获取节点属性,反求出不带fileFormat的文件路径
            如果为不同节点类型的替换,则删除掉原来节点,重新导入用户指定的节点类型
            并继承变换和父子层级
            '''
            #分离路径 [Z:,project,DFH,Asset,component,DFH_fhsj_test]
            asset_dir_split = cmds.getAttr(f"{sel_node}.assetDir").split("/")[0:-1]
            #拼接路径,没有后面asset_type的路径
            asset_dir = "/".join(asset_dir_split)
            
            asset_name = cmds.getAttr(f"{sel_node}.assetName")
            res_type = cmds.getAttr(f"{sel_node}.resolutionType")
            current_res = cmds.getAttr(f"{sel_node}.resolutionType")
            
            #记录选择节点,方便后续还原位置
            original_pos,original_rotate,original_scale = self.operator.get_transform(sel_node)
            
            new_asset_name = asset_name.replace(current_res,target_res)
            
            if target_file_format == "ass":
                #反求新的res资产名称
                
                new_asset_file = f"{asset_dir}/ass/{new_asset_name}.ass"
                if os.path.isfile(new_asset_file):
                    
                    #导入新的ass节点,并且获取节点名称
                    import_transform = self.operator.import_ass(new_asset_file)
                    #继承原来的变换坐标
                    self.operator.set_transform(import_transform,translation = original_pos,
                                    rotation = original_rotate,scale = original_scale)
                                    
                    cmds.select(clear=True)
                    cmds.delete(sel_node)
                    if parent:
                        cmds.parent(import_transform,parent)
                else:
                    om.MGlobal.displayError(f"{new_asset_file} 文件路径不存在")
                
                
            elif target_file_format == "gpuCache":
                new_asset_file = f"{asset_dir}/cache/{new_asset_name}.abc"
                
                if os.path.isfile(new_asset_file):
                    
                    #导入新的ass节点,并且获取节点名称
                    import_transform = self.operator.import_gpu_cache(new_asset_file)
                    #继承原来的变换坐标
                    self.operator.set_transform(import_transform,translation = original_pos,
                                    rotation = original_rotate,scale = original_scale)
                    cmds.select(clear=True)
                    cmds.delete(sel_node)
                    
                    if parent:
                        cmds.parent(import_transform,parent)
                    
                else:
                    om.MGlobal.displayError(f"{new_asset_file} 文件路径不存在")
            
            elif target_file_format == "abc":
                new_asset_file = f"{asset_dir}/alembic/{new_asset_name}.abc"
                
                if os.path.isfile(new_asset_file):
                    #导入新的ass节点,并且获取节点名称
                    import_transform = self.operator.import_abc(new_asset_file)
                    #继承原来的变换坐标
                    self.operator.set_transform(import_transform,translation = original_pos,
                                    rotation = original_rotate,scale = original_scale)
                                    
                    cmds.select(clear=True)                
                    cmds.delete(sel_node)
                    
                    if parent:
                        cmds.parent(import_transform,parent)
                    
                else:
                    om.MGlobal.displayError(f"{new_asset_file} 文件路径不存在")
            if parent:
                p = parent[0]
                full_path = f"{p}|{import_transform}"
            else:
                full_path = f"{import_transform}"

        return full_path
              
    def repalce_all_res_command(self):
        all_component_node_dict = self.operator.get_component_node()
        
        #print("all_component_node_dict >>> ",all_component_node_dict)
        
        current_clicked_button = self.sender()
        target_file_format = current_clicked_button.property("action")
        print(all_component_node_dict)
        
        if all_component_node_dict:
            self.repalce_all_res(node_dict = all_component_node_dict,target_file_format = target_file_format)
        
        else:
            om.MGlobal.displayError("场景中无任何节点可以替换")
                
    def repalce_all_res(self,node_dict=None,target_file_format=None):
        '''
        替换场景中所有的节点为指定类型的节点
        node_dict > {资产名:资产节点...}
        target_file_format > 需要替换的分辨率类型
        '''
        for asset_name,node_list in node_dict.items():
            #如果只有单个,则重新替换,不检测实例
            if len(node_list)==1:
                #记录原始变换信息
                original_pos,original_rotation,original_scale = self.operator.get_transform(node_list[0])
                new_master_node = self.replace_select_res(node_list[0],target_file_format = target_file_format)
                self.operator.set_transform(new_master_node,translation = original_pos,rotation = original_rotation,
                                scale=original_scale)
                cmds.select(clear=True)
                #cmds.delete(node_list[0])
                self.operator.set_transform(new_master_node)
                print("只有单个节点 >>>>>>>>>>>>>>>>>>>>>")
                continue
            
            #启用实例替换
            #导入组第一个对象,其余对象使用第一个对象instance
            if self.enabled_instance_check_box.isChecked():
                master_node = node_list[0]
                instance_node = node_list[1:]
                print(f"master_node  >>>>>>>>>>>>> {master_node}")
                print(f"instance_node  >>>>>>>>>>>>> {instance_node}")
                
                #返回新的导入节点路径
                new_master_node = self.replace_select_res(master_node,target_file_format)
                
                count=0
                for ins_node in instance_node:
                    #记录原始变换信息
                    original_pos,original_rotation,original_scale = self.operator.get_transform(ins_node)
                    #获取物体父层级节点
                    parent = cmds.listRelatives(ins_node,parent=True,fullPath=True)
                    
                    count = count+1
                    short_name = ins_node.split("|")[-1]
                    #asset_name = cmds.getAttr(f"{ins_node}.assetName")
                    
                    #复制父实例对象
                    node = cmds.instance(new_master_node)[0]
                    new_node = cmds.rename(node,f"{asset_name}_{target_file_format}{count}",ignoreShape=True)
                    self.operator.reset_transform(new_node)
                    #删除原始节点
                    cmds.select(clear=True)
                    cmds.delete(ins_node)
                    #继承原始节点坐标
                    self.operator.set_transform(new_node,original_pos,original_rotation,original_scale)
                    
                    #如果有层级,则继承原来的层级
                    # if parent:
                    #     print(cmds.nodeType(parent[0]))
                    #     print(f"ins_node  {ins_node}")
                    #     print(f"new_node  {new_node}")
                    #     print(f"parent  ",parent[0])
                    #     cmds.parent(new_node,parent[0],shape=True)
            else:
                count=0
                for dup_node in node_list:
                    #记录原始变换信息
                    original_pos,original_rotation,original_scale = self.operator.get_transform(dup_node,space="object")
                    #获取物体父层级节点
                    parent = cmds.listRelatives(dup_node,parent=True,fullPath=True)
                    
                    count = count+1
                    short_name = ins_node.split("|")[-1]
                    #删除原始节点
                    
                    #复制父实例对象
                    new_node = cmds.duplicate(new_master_node,name=f"{short_name}_dup{count}",renameChildren=True)
                    cmds.select(clear=True)
                    cmds.delete(dup_node)
                    #继承原始节点坐标
                    self.operator.set_transform(new_node,original_pos,original_rotation,original_scale)
                    
                    # #如果有层级,则继承原来的层级
                    # if parent:
                    #     cmds.parent(new_node,parent)
                        
        
    def screen_shot(self):
        '''
        生成图片保存路径和名称
        拍屏后将图片保存到指定路径
        label标签生成预览图
        '''
        asset_name = self.get_user_input()
        if not asset_name:
            om.MGlobal.displayError("资产名称不能为空!")
            return
        output_path = f"{self.file_path}/{self.project_code}_{self.scene_prefix}_{asset_name}/{self.project_code}_{self.scene_prefix}_{asset_name}_preview.png"
        print(output_path)
        self.operator.screen_shot(output_path)
        
        if not os.path.exists(output_path):
            om.MGlobal.displayError("截图文件路径不存在")
        
        pix = QPixmap(output_path)
        self.preview_label.setPixmap(pix)
        self.preview_label.setScaledContents(True)
        
    
    def update_source_button_command(self):
        
        if not self.get_user_input():
            om.MGlobal.displayError("输入名称不能为空")
            return
        
        sel = cmds.ls(selection=True,long=True)
        
        if not sel:
            om.MGlobal.displayError("未选择任何物体")
            return

        node_name = sel[0]
        
        if not cmds.nodeType(node_name) =="transform":
            om.MGlobal.displayError("所选节点类型错误")
            return
        
        #保存原始位置
        original_pos,original_rot,original_scale = self.operator.get_transform(node_name)
        try:
            
            self.operator.reset_transform(node_name)
            #检查轴
            self.operator.check_pivot(node_name)

            self.operator.export_source(node_name = node_name,
                            file_path = self.file_path,
                            asset_name = self.get_user_input(),
                            project_code = self.project_code,
                            scene = self.scene_prefix
                    )
        
        finally:
            
            self.operator.set_transform(node_name,translation = original_pos,
                            rotation = original_rot,
                            scale = original_scale)
    
    def file_dialog(self,parent=None,title = None,file_filter = None):
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            title,
            self.file_path,
            file_filter
        )
        if not file_path:
            return
            
        return file_path.replace("\\","/")
    
    def import_cache(self,cache_type = None):
        
        '''
        导入cache,并创建属性
            isComponent
            assetName
            assetDir
            fileFormat
            resolutionType
        '''
        
        if cache_type =="abc":
            file_path = self.file_dialog(parent=self,title = "选择一个Abc文件",
                            file_filter = "Alembic (*.abc)"
                    )
            if not file_path:
                return
            self.operator.import_abc(file_path)
                    
        elif cache_type == "gpuCache":
            file_path = self.file_dialog(parent=self,title = "选择一个gpuCache文件",
                            file_filter = "gpuCache (*.abc)"
                    )
            if not file_path:
                return
            self.operator.import_gpu_cache(file_path)
        
        elif cache_type == "ass":
            file_path = self.file_dialog(parent=self,title = "选择一个gpuCache文件",
                            file_filter = "Arnold ASS (*.ass)"
                    )
            if not file_path:
                return
            self.operator.import_ass(file_path)
    
    def import_source(self):
        
        current_clicked_button = self.sender()
        target_res = self.list_widget.currentItem().text()
        ma_type = current_clicked_button.property("action")
        
        sel_node = cmds.ls(selection=True,long=True)
        for node in sel_node:
            self.operator.import_select_res_ma(select_node = node,target_res = target_res,
                                ma_type = ma_type)
    
class Operator():
    
    def __init__(self,res_list=None):
        self.exportor = ExportManager()
        self.node_creator = NodeCreator()
        self.material_manager = MaterialManager()
        
        self.res_list = res_list
    
    def check_pivot(self,transform_node,x=0,y=0,z=0):
        '''
        api om.MFnTransform检查物体旋转轴心和缩放轴心(两个轴心的位置需要完全一样)
        检查物体的轴心
        '''
        #用户指定轴心位置
        pivot_vector = om.MVector(x,y,z)
        
        sel_fn=om.MSelectionList()
        sel_fn.add(transform_node)
        
        dep_fn = sel_fn.getDependNode(0)
        
        #是否为transfrom接顶点
        if dep_fn.hasFn(om.MFn.kTransform):
        
            dag_obj = sel_fn.getDagPath(0)
            transform_fn = om.MFnTransform(dag_obj)
            scale_pivot = om.MVector(transform_fn.scalePivot(om.MSpace.kWorld))
            rotate_pivot = om.MVector(transform_fn.rotatePivot(om.MSpace.kWorld))
            
            if scale_pivot == rotate_pivot:
                if pivot_vector == scale_pivot:
                    print("轴心正确")
                    return True
                else:
                    om.MGlobal.displayError("物体轴心不在世界坐标中心")
            else:
                #print("轴心错误")
                om.MGlobal.displayError("旋转轴和缩放轴不一致")
                return
    
    def get_file_format(self,transform_node):
        '''
        获取选择插件节点的file format文件格式
        '''
        if self.is_component_node(transform_node):
            
            return cmds.getAttr(f"{transform_node}.fileFormat")
            
        else:
            return
            om.MGlobal.displayError("所选择节点不是使用Component Tool导入的节点!")
    
    def set_transform(self,node_name=None,translation=[0,0,0],rotation=[0,0,0],scale=[1,1,1]):
        
        cmds.setAttr(f"{node_name}.translateX",translation[0])
        cmds.setAttr(f"{node_name}.translateY",translation[1])
        cmds.setAttr(f"{node_name}.translateZ",translation[2])
        
        cmds.setAttr(f"{node_name}.rotateX",rotation[0])
        cmds.setAttr(f"{node_name}.rotateY",rotation[1])
        cmds.setAttr(f"{node_name}.rotateZ",rotation[2])
        
        cmds.setAttr(f"{node_name}.scaleX",scale[0])
        cmds.setAttr(f"{node_name}.scaleY",scale[1])
        cmds.setAttr(f"{node_name}.scaleZ",scale[2])
    
    def get_component_node(self):
        '''
        获取场景中所有插件导入的节点(属性有isComponent的节点)
        返回{资产名:对应资产节点}
        '''
        all_component_node = cmds.ls("*.isComponent",long=True,objectsOnly=True)

        all_component_node_dict = defaultdict(list)
        for node in all_component_node:
            
            asset_name = cmds.getAttr(f"{node}.assetName")
            
            all_component_node_dict[asset_name].append(node)
        
        return all_component_node_dict
    
    def reset_transform(self,node_name=None):
        '''
        将传递的节点的transform设置为0
        '''
        translate = cmds.xform(node_name,query=True,translation=True,worldSpace=True)
        rotate = cmds.xform(node_name,query=True,rotation=True,worldSpace=True)
        scale = cmds.xform(node_name,query=True,scale=True,worldSpace=True)
        
        if not(translate == [0.0,0.0,0.0]):
            cmds.setAttr(f"{node_name}.translateX",0)
            cmds.setAttr(f"{node_name}.translateY",0)
            cmds.setAttr(f"{node_name}.translateZ",0)
            
        if not(rotate == [0.0,0.0,0.0]):
            cmds.setAttr(f"{node_name}.rotateX",0)
            cmds.setAttr(f"{node_name}.rotateY",0)
            cmds.setAttr(f"{node_name}.rotateZ",0)
        
        if not(scale == [1,1,1]):
            cmds.setAttr(f"{node_name}.scaleX",1)
            cmds.setAttr(f"{node_name}.scaleY",1)
            cmds.setAttr(f"{node_name}.scaleZ",1)
    
    def get_transform(self,node_name=None,space="world"):
        '''
        获取节点的变换坐标
        return:
            translation,rotation,scale
        例如:
            [10.24026411883034, 2.88950739199462, -1.8756257191008743]
            [74.34381086048975, -77.99000053880275, -57.57194043830288]
            [0.7992232046510029, 0.7992232046510024, 0.7992232046510026]
            
        '''
        sel_fn = om.MSelectionList()
        sel_fn.add(node_name)
        
        dep_fn = sel_fn.getDagPath(0)
        
        if dep_fn.hasFn(om.MFn.kTransform):
            if space == "world":
                translation = cmds.xform(node_name, q=True, translation=True, worldSpace=True)
                rotation = cmds.xform(node_name, q=True, rotation=True, worldSpace=True)
                scale = cmds.xform(node_name, q=True, scale=True, worldSpace=True)
                
            elif space == "object":
                translation = cmds.xform(node_name, q=True, translation=True, objectSpace=True)
                rotation = cmds.xform(node_name, q=True, rotation=True, objectSpace=True)
                scale = cmds.xform(node_name, q=True, scale=True, objectSpace=True)
            
            return translation,rotation,scale
        
        else:
            om.MGlobal.displayError("选择节点类型错误")
    
    def replace_ass_res(self,transform_node=None,target_res_type=None,target_pos=None,target_rotate=None,target_scale=None,parent=None):
        '''
        替换选择的ass代理为指定的分辨率
            1 > 判断用户选择的节点类型与用户想切换的节点类型是否为相同cache类型   如果相同则直接切换res路径,并且修改res属性
                如果文件不存在,则提示用户文件不存在,并取消替换
                
                
            2 > 如果为不同cache则获取节点属性以及用户要切换的cache类型,反求出文件名称
                然后执行导入操作,继承原始的变换和层级,并且删除掉原节点
        
        transform_node > children节点为Arnold代理的transform节点
        res_type > 要替换的res分辨率type
        '''
        if cmds.listRelatives(transform_node,children=True,fullPath=True):
            ass_node = cmds.listRelatives(transform_node,children=True,fullPath=True)[0]
        else:
            om.MGlobal.displayError("所选择节点类型错误或为空组")
        
        #判断是否为插件导入的节点
        if self.is_component_node(transform_node):
            #判断子节点的类型是否为Arnold代理节点
            if cmds.nodeType(ass_node) == "aiStandIn":
                #获取arnold节点路径
                ass_file_path = cmds.getAttr(f"{ass_node}.dso")
                dir_name = os.path.dirname(ass_file_path)
                base_name = os.path.splitext(os.path.basename(ass_file_path))[0]
                current_res_type = base_name.split("_")[-1]
                
                if target_res_type != current_res_type:
                    #目标res和当前res不一样,则修改当前res名称为目标res
                    new_asset_name = base_name.replace(current_res_type,target_res_type)
                    new_ass_file_path = f"{dir_name}/{new_asset_name}.ass"
                    
                    #判断目标文件是否存在,如果存在则直接替换
                    if os.path.isfile(new_ass_file_path):
                        cmds.setAttr(f"{ass_node}.dso",new_ass_file_path,type="string")
                        #更新
                        cmds.setAttr(f"{transform_node}.assetName",new_asset_name,type="string")
                        cmds.setAttr(f"{transform_node}.resolutionType",target_res_type,type="string")
                        return
                    
                    else:
                        #如果文件不存在,则返回当前代理节点的transform
                        #用于后续提示用户替换内容是否成功信息
                        print(f"{new_ass_file_path} 文件路径不存在")
                        return False

            else:
                om.MGlobal.displayError("请选择一个Arnold代理节点")
        
        else:
            om.MGlobal.displayError("替换失败!所选择节点不是使用Component Tool导入的节点!")
        
        
    def replace_gpu_cache_res(self,transform_node=None,target_res_type=None,target_pos=None,target_rotate=None,target_scale=None,parent=None):
        
        if cmds.listRelatives(transform_node,children=True,fullPath=True):
            gpu_node = cmds.listRelatives(transform_node,children=True,fullPath=True)[0]
        else:
            om.MGlobal.displayError("所选择节点类型错误或为空组")
        
        #判断是否为插件导入的节点
        if self.is_component_node(transform_node):
            #判断子节点的类型是否为gpuCache代理节点
            if cmds.nodeType(gpu_node) == "gpuCache":
                #获取gpuCache节点路径
                ass_file_path = cmds.getAttr(f"{gpu_node}.cacheFileName")
                dir_name = os.path.dirname(ass_file_path)
                base_name = os.path.splitext(os.path.basename(ass_file_path))[0]
                current_res_type = base_name.split("_")[-1]
                
                if target_res_type != current_res_type:
                    #目标res和当前res不一样,则修改当前res名称为目标res
                    new_asset_name = base_name.replace(current_res_type,target_res_type)
                    new_gpu_cache_file_path = f"{dir_name}/{new_asset_name}.abc"
                    #判断目标文件是否存在,如果存在则直接替换
                    if os.path.isfile(new_gpu_cache_file_path):
                        cmds.setAttr(f"{gpu_node}.cacheFileName",new_gpu_cache_file_path,type="string")
                        
                        #更新transform节点信息
                        cmds.setAttr(f"{transform_node}.assetName",new_asset_name,type="string")
                        cmds.setAttr(f"{transform_node}.resolutionType",target_res_type,type="string")
                        return True
                    
                    else:
                        #如果文件不存在,则返回当前代理节点的transform
                        #用于后续提示用户替换内容是否成功信息
                        print(f"{new_gpu_cache_file_path} 文件路径不存在")
                        return False

            else:
                om.MGlobal.displayError("请选择一个Arnold代理节点")
        
        else:
            om.MGlobal.displayError("替换失败!所选择节点不是使用Component Tool导入的节点!")
    
    def replace_abc_res(self,transform_node=None,target_res_type=None,target_pos=None,target_rotate=None,target_scale=None,parent=None):
        '''
        abc 缓存导入后,没有特殊节点,因此需要根据组的属性判断是否为插件导入的abc
            fileFormat > abc
            isComponent > True
        '''
        if cmds.listRelatives(transform_node,children=True,fullPath=True):
            gpu_node = cmds.listRelatives(transform_node,children=True,fullPath=True)[0]
        else:
            om.MGlobal.displayError("所选择节点类型错误或为空组")
        
        if self.is_component_node(transform_node):
            if cmds.getAttr(f"{transform_node}.fileFormat") == "abc":
                
                #获取当前节点的信息
                current_res_type = cmds.getAttr(f"{transform_node}.resolutionType")
                current_asset_name = cmds.getAttr(f"{transform_node}.assetName")
                current_asset_path = cmds.getAttr(f"{transform_node}.assetDir")
                
                #根据目标res反求新的res类型名称
                new_asset_name = current_asset_name.replace(current_res_type,target_res_type)
                new_asset_path = f"{current_asset_path}/{new_asset_name}.abc"
                
                if os.path.isfile(new_asset_path):
                    if current_res_type != target_res_type:
                        #删除旧的abc文件
                        cmds.select(clear=True)
                        cmds.delete(transform_node)
                        #重写导入新的abc文件
                        abc_node = self.import_abc(abc_path=new_asset_path)
                        return abc_node
                else:
                    #如果文件不存在,则返回当前代理节点的transform
                    #用于后续提示用户替换内容是否成功信息
                    raise FileExistsError("文件不存在!")

            else:
                om.MGlobal.displayError("替换失败!所选择节点不是abc类型的节点!")
        
        else:
            om.MGlobal.displayError("替换失败!所选择节点不是使用Component Tool导入的节点!")
    
    def is_component_node(self,node):
        '''
        检查传入的节点是否为插件生成的对象
        如果有属性isComponent=True属性,则返回True,否则返回False
        '''
        if cmds.attributeQuery("isComponent",node = node,exists=True):
            return True
        else:
            return False
    
    def create_locator(self):
        '''
        创建基础locator,初始化空组
        '''
        locator_transform,locator_shape = self.node_creator.create_locator()
        #生成对应list的Group
        for group_name in self.res_list:
            
            self.node_creator.create_group(node_name=group_name,parent=locator_transform,lock_transform=True)

    def create_attribute(self,project_dir = None,node_name = None,project_code = None,asset_name = None,scene = None):
        
        #记录所属项目
        if not cmds.attributeQuery("assetDir",node=node_name,exists=True):
            cmds.addAttr(node_name,longName="assetDir",dataType="string")
            
        if not cmds.attributeQuery("projectCode",node=node_name,exists=True):
            cmds.addAttr(node_name,longName="projectCode",dataType="string")
            
        #记录资产名称
        if not cmds.attributeQuery("assetName",node=node_name,exists=True):
            cmds.addAttr(node_name,longName="assetName",dataType="string")
        
        if not cmds.attributeQuery("scene",node=node_name,exists=True):
            cmds.addAttr(node_name,longName="scene",dataType="string")
        
        if not cmds.attributeQuery("isComponent",node=node_name,exists=True):
            cmds.addAttr(node_name,longName="isComponent",attributeType="bool")
        
        cmds.setAttr(f"{node_name}.assetDir",project_dir,type="string")
        cmds.setAttr(f"{node_name}.projectCode",project_code,type="string")
        cmds.setAttr(f"{node_name}.assetName",asset_name,type="string")
        cmds.setAttr(f"{node_name}.scene",scene,type="string")
        cmds.setAttr(f"{node_name}.isComponent",True)
    
    def export_select_res(self,node_name = None,file_path=None,file_name=None,asset_name=None,project_code=None,scene=None,file_type="ma"):
        '''
        导出选择节点为ma 到指定的文件路径
        并在选择组和该组的parent设置属性
        node_name > 要导出的节点名称
        file_path > 文件保存路径
        file_name > 保存文件名称
        asset_name > 资产名称
        project_code > 项目缩写
        file_type > 文件类型  ma,mb,ass,gpucache,abc
        '''
        #node_name = node_name.split(":")[-1]
        res_type = node_name.split("|")[-1]
        print("node_name",node_name)
        
        parent = cmds.listRelatives(node_name,parent=True,fullPath=True)
        if not parent:
            cmds.error("节点层级错误!")
        
        #if cmds.listRelatives(parent)
        parent_locator_transform_node = cmds.listRelatives(node_name,parent=True,fullPath=True)[0]
        child_node = cmds.listRelatives(parent_locator_transform_node,shapes=True)[0]
        
        if not cmds.nodeType(cmds.listRelatives(parent_locator_transform_node)[0]) == "locator":
            cmds.error("当前层级结构错误")
        
        if not cmds.listRelatives(node_name,children=True,fullPath=True):
            print(f"{node_name}子节点为空,跳过导出")
            return

        try:
            if file_type == "ma":
                #选择组时,自动选择parent父节点的locator
                #selection_list = [parent_locator_transform_node,child_node,node_name]
                selection_list = [child_node,node_name]
                print("selection_list >>>>>>>>>> ",selection_list)
                cmds.select(selection_list)
                
                output_file = f"{file_path}/{project_code}_{scene}_{asset_name}/{project_code}_{scene}_{asset_name}_{res_type}.ma"
                component_name = os.path.splitext(os.path.basename(output_file))[0]
                component_path = os.path.dirname(output_file)
                self.create_attribute(node_name = parent[0],project_dir = component_path,project_code=project_code,asset_name=component_name,scene=scene)
                
                base_dir = os.path.dirname(output_file)
                if not os.path.exists(base_dir):
                    os.makedirs(base_dir)
                
                self.exportor.export_maya_file(object_name = node_name,file_path = output_file)
                cmds.inViewMessage(assistMessage=f"{node_name} > 文件导出成功",position="topCenter",fade=True,fadeStayTime=1000)
                
            elif file_type == "abc":
                output_file = f"{file_path}/{project_code}_{scene}_{asset_name}/alembic/{project_code}_{scene}_{asset_name}_{res_type}.abc"
                
                #检查对应路径是否存在,如果不存在则创建相对应路径
                base_dir = os.path.dirname(output_file)
                if not os.path.exists(base_dir):
                    os.makedirs(base_dir)
                
                selection_list = [child_node,node_name]
                #print("selection_list >>>>>>>>>> ",selection_list)
                cmds.select(selection_list)
                    
                self.exportor.export_abc(node_name = node_name,file_path=output_file)
                
            elif file_type == "gpuCache":
                
                output_file = f"{file_path}/{project_code}_{scene}_{asset_name}/cache"
                if not os.path.exists(output_file):
                    os.makedirs(output_file)
                
                output_name = f"{project_code}_{scene}_{asset_name}_{res_type}"
                
                self.exportor.export_gpu_cache(node_name = node_name,file_path=output_file,file_name=output_name)
            
            elif file_type == "ass":
                output_file = f"{file_path}/{project_code}_{scene}_{asset_name}/ass/{project_code}_{scene}_{asset_name}_{res_type}.ass"
                
                base_dir = os.path.dirname(output_file)
                if not os.path.exists(base_dir):
                    os.makedirs(base_dir)
                
                self.exportor.export_arnold_ass(file_path=output_file,node_name=node_name)
        
        except Exception as e:
            cmds.error(f"导出文件失败 > {e}")
        
        finally:
            cmds.select(None)
    
    def export_child_res(self,node_name = None,file_path=None,asset_name=None,project_code=None,scene=None,file_type="ma"):
        '''
        导出选择的RootLocator的所有child组
        '''
        #获取子组的长名称,防止重命名
        child_node = cmds.listRelatives(node_name,children=True,fullPath=True)
        
        if child_node:
            
            new_child_node=[]
            #清洗命名空间
            for name in child_node:
                temp_name = name.split(":")[-1]
                #获取长名称后面的组名,用于判断组名称规范
                new_child_node.append(temp_name.split("|")[-1])
            
            if cmds.nodeType(cmds.listRelatives(node_name,children=True)[0]) == "locator":
                print(new_child_node)
                if set(self.res_list).issubset(set(new_child_node)):
                    #切片,去除所有子集的第一个shape节点留下transform
                    res_group = child_node[1:]
                    for child_group in res_group:
                        self.export_select_res(node_name=child_group,file_path=file_path,
                            asset_name=asset_name,project_code=project_code,scene=scene,file_type=file_type)
                
                else:
                    cmds.error("结构层级错误")
            
            else:
                 cmds.error("请选择正确的Locator节点")
        
        else:
            cmds.error("所选择节点为空") 
    
    def export_source(self,node_name = None,file_path=None,asset_name=None,project_code=None,scene=None,file_type="ma"):
        
        child_node = cmds.listRelatives(node_name,fullPath=True,children=True)
        if not child_node:
            om.MGlobal.displayError("所选节点为空")
            return
        
        if cmds.nodeType(child_node[0]) == "locator":
            
            output_file = f"{file_path}/{project_code}_{scene}_{asset_name}/{project_code}_{scene}_{asset_name}_src.ma"
            
            base_dir = os.path.dirname(output_file)
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
            cmds.select(node_name)
            self.exportor.export_maya_file(object_name = node_name,file_path = output_file)
            cmds.inViewMessage(assistMessage=f"{node_name} > 文件导出成功",position="topCenter",fade=True,fadeStayTime=1000)
        else:
            om.MGlobal.displayError("请选择一个符合规范的locator节点")
            
    def copy_texture_to_target_file(self,node_name = None,path = None,project_code=None,scene=None,asset_name=None):
        '''
        dir_texture_path > 目标贴图路径
        '''
        dir_texture_path = f"{path}/{project_code}_{scene}_{asset_name}/textures"
        print("dir_texture_path",dir_texture_path)
        
        if not os.path.exists(dir_texture_path):
            os.makedirs(dir_texture_path)
        
        # file_node=cmds.ls(type="file")
        file_node = self.material_manager.get_texture_node(root_transform=node_name,api_type=om.MFn.kMesh)
        
        #re规则，匹配10##的UDIM数字字符串
        pattern=r'10\d{2}'  
        os.makedirs(dir_texture_path,exist_ok=True)
        for node in file_node:
            file_path=cmds.getAttr(node + ".fileTextureName")
            tiling_attri=cmds.getAttr(node + ".uvTilingMode")
            color_space = cmds.getAttr(node + ".colorSpace")
            file_name=os.path.basename(file_path)
            file_dir = os.path.dirname(file_path)
            
            #判断贴图是否已经在目标路径
            #如果不在贴图目标贴图路径则
            #贴图节点为非UDIM多象限
            if tiling_attri == 0:
                print("贴图不是多象限")
                if not os.path.isfile(dir_texture_path + "\\" + file_name):
                    shutil.copy2(file_path,dir_texture_path)
                    print("复制贴图{0}到  >>>>  {1}  <<<<    成功".format(file_name,dir_texture_path))
                    cmds.setAttr(node + ".fileTextureName",dir_texture_path + "\\" + file_name,type="string")
                    cmds.setAttr(node + ".ignoreColorSpaceFileRules ",True)
                    cmds.setAttr(node + ".colorSpace",color_space,type="string")
                else:
                    print("贴图为重复使用，已经存在目标文件夹，不执行复制。")
                    cmds.setAttr(node + ".fileTextureName",dir_texture_path + "\\" + file_name,type="string")
                    cmds.setAttr(node + ".ignoreColorSpaceFileRules ",True)
                    cmds.setAttr(node + ".colorSpace",color_space,type="string")
                
            #如果贴图格式是UDIM多象限
            else:
                print("贴图是UDIM多象限节点")
                original_tex_folder_list = os.listdir(file_dir)
                
                tex_file_pattern = r'10\d{2}'
                

                #udim_match = re.findall(tex_file_pattern,file_name)[0]
                udim_match = re.findall(tex_file_pattern,file_name)[0]
                file_name_split = file_name.split(udim_match)
                file_name_prefix = file_name_split[0]
                file_name_suffix = file_name_split[1]
                
                udim_pattern = rf'{file_name_prefix}10\d{{2}}{file_name_suffix}'
                for tex_file in original_tex_folder_list:
                    if re.match(udim_pattern,tex_file):
                        #判断每个符合规则的文件是否都存在指定路径
                        if not os.path.isfile(dir_texture_path + "\\" + tex_file):
                            original_tex_file = file_dir + "\\" + tex_file
                            shutil.copy2(original_tex_file,dir_texture_path)
                            print("复制 UDIM 贴图{0}到  >>>>  {1}  <<<<    成功".format(tex_file,dir_texture_path))
                            cmds.setAttr(node + ".fileTextureName",dir_texture_path + "\\" + file_name,type="string")
                            cmds.setAttr(node + ".ignoreColorSpaceFileRules",True)
                            cmds.setAttr(node + ".colorSpace",color_space,type="string")
                            print(original_tex_file)
                            print(tex_file)
                        else:
                            print("贴图为重复使用，已经存在目标文件夹，不执行复制。")
                            cmds.setAttr(node + ".fileTextureName",dir_texture_path + "\\" + file_name,type="string")
                            cmds.setAttr(node + ".ignoreColorSpaceFileRules ",True)
                            cmds.setAttr(node + ".colorSpace",color_space,type="string")
    
    def screen_shot(self,output_png,width=1280,height=720,frame=None,show_ornaments=False,offscreen=True,cleanup_variants=True):
        """
        Maya 视口截屏到 PNG（用 playblast），返回最终生成的图片路径（可能是 xxx.0000.png 这种变体）

        Args:
            output_png (str): 目标路径，必须以 .png 结尾（例如 D:/tmp/a.png）
            width/height (int): 输出分辨率
            frame (float|int|None): 指定帧；None 则用当前时间
            show_ornaments (bool): 是否显示HUD/ornaments
            offscreen (bool): 是否离屏
            cleanup_variants (bool): 截图前是否删除同名前缀的旧 png（含序列变体）

        Returns:
            str|None: 实际生成的 png 文件路径；失败返回 None
        """
        if not output_png.lower().endswith(".png"):
            raise ValueError("output_png must end with .png")

        out_dir = os.path.dirname(output_png)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir)

        if frame is None:
            frame = cmds.currentTime(q=True)

        try:
            cmds.playblast(
                completeFilename=output_png,
                format="image",
                compression="png",
                frame=frame,
                viewer=False,
                showOrnaments=show_ornaments,
                percent=100,
                quality=100,
                offScreen=offscreen,
                framePadding=0,
                clearCache=True,
                forceOverwrite=True,
                widthHeight=[int(width), int(height)],
            )
        except Exception as e:
            print(u"// Warning: playblast failed: {} //".format(e))
            return None

        # 1) 精确文件名
        if os.path.exists(output_png):
            return output_png

        # 2) 兜底：找同名前缀的最新 png（可能是序列名）
        candidates = glob.glob(output_png[:-4] + "*.png")
        if candidates:
            candidates.sort(key=lambda p: os.path.getmtime(p))
            return candidates[-1]

        print(u"// Warning: 截图输出未找到（playblast 没生成 png）。 //")
        return None
        
    ##########################################################################
    
    def set_import_attribute(self,node_name = None,dir_name=None,asset_name=None,file_format=None,resolution_type=None,asset_type=None):
        
        if not cmds.attributeQuery("assetDir",node = node_name,exists = True):
            cmds.addAttr(node_name,longName = "assetDir",dataType="string")
            
        if not cmds.attributeQuery("assetName",node = node_name,exists = True):
            cmds.addAttr(node_name,longName = "assetName",dataType="string")
        
        if not cmds.attributeQuery("fileFormat",node = node_name,exists = True):
            cmds.addAttr(node_name,longName = "fileFormat",dataType="string")
        
        if not cmds.attributeQuery("resolutionType",node = node_name,exists = True):
            cmds.addAttr(node_name,longName = "resolutionType",dataType="string")
        
        if not cmds.attributeQuery("isComponent",node = node_name,exists = True):
            cmds.addAttr(node_name,longName = "isComponent",attributeType="bool")
        
        cmds.setAttr(f"{node_name}.assetDir",dir_name,type="string")
        cmds.setAttr(f"{node_name}.assetName",asset_name,type="string")
        cmds.setAttr(f"{node_name}.fileFormat",file_format,type="string")
        cmds.setAttr(f"{node_name}.resolutionType",resolution_type,type="string")
        cmds.setAttr(f"{node_name}.isComponent",True)
    
    def import_abc(self,abc_path=None):
        '''
        生成新空组后将导入的abc文件reparent到新建的空组中,并创建路径属性
        abc_path > abc路径
        transfrom > 是否获取当前组件的transfrom
        position > 目标组件的世界坐标位置
        '''
        dir_name = os.path.dirname(abc_path)
        base_name = os.path.splitext(os.path.basename(abc_path))[0]
        resolution_type = base_name.split("_")[-1]
        
        empty_group = cmds.group(name = "abc_import",empty = True)
        #导入abc,并将设置为指定组的子节点
        cmds.AbcImport(abc_path,mode="import",reparent=empty_group)
        
        #将空组重命名为资产名
        new_group = cmds.rename(empty_group,base_name + "_abc")
        
        self.set_import_attribute(new_group,dir_name=dir_name,asset_name=base_name,
                        file_format="abc",resolution_type=resolution_type,asset_type="abc")
        
        return new_group
    
    def import_ass(self,ass_path = None):
        
        ass_dir = os.path.dirname(ass_path)
        
        ass_name = os.path.splitext(os.path.basename(ass_path))[0]
        resolution_type = ass_name.split("_")[-1]
        
        #创建ass节点,命名为asset_name
        ass_node = cmds.createNode("aiStandIn",name=ass_name + "_ass")
        parent_transform = cmds.rename(cmds.listRelatives(ass_node,parent=True,fullPath=True)[0],f"{ass_name}_ass")
        
        #设置属性
        cmds.setAttr(f"{parent_transform}.dso",ass_path,type="string")
        self.set_import_attribute(node_name = parent_transform,dir_name = ass_dir,
                        asset_name = ass_name,file_format = "ass",
                        resolution_type = resolution_type,asset_type="ass")
        
        return parent_transform
        
    def import_gpu_cache(self,gpu_path = None):
        
        ass_dir = os.path.dirname(gpu_path)
        
        gpu_name = os.path.splitext(os.path.basename(gpu_path))[0]
        resolution_type = gpu_name.split("_")[-1]
        
        #创建gpuCache节点,命名为asset_name
        ass_node = cmds.createNode("gpuCache",name=gpu_name + "_gpuCache")
        cmds.setAttr(f"{ass_node}.cacheFileName",gpu_path,type="string")
        parent_transform = cmds.rename(cmds.listRelatives(ass_node,parent=True,fullPath=True)[0],f"{gpu_name}_gpuCache")
        
        #设置属性
        self.set_import_attribute(node_name = parent_transform,dir_name = ass_dir,
                        asset_name = gpu_name,file_format = "gpuCache",
                        resolution_type = resolution_type,asset_type="gpuCache")
        
        return parent_transform
    
    def import_ma(self,file_path = None):
        
        dir_name = os.path.dirname(file_path)
        ma_name = os.path.splitext(os.path.basename(gpu_path))[0]
        resolution_type = ma_name.split("_")[-1]
        
        return_node = cmds.file(file_path,i=True,returnNewNodes=True)

        transform_node =[node for node in return_node if cmds.nodeType(node) == "transform"]
        
        for node in transform_node:
            if not cmds.listRelatives(node,parent=True,fullPath=True):
                cmds.select(node)
                
        self.set_import_attribute(node_name = node,dir_name=dir_name,
                        asset_name = ma_name,file_format="mayaAscii",
                        resolution_type=resolution_type
                )
        
        return node
    
    def import_select_res_ma(self,select_node = None,target_res = None,ma_type="res"):
        '''
        将选择的节点替换为用户选择分辨率的ma文件
        select_node >  用户当前选择的节点
        taget_res > 用户要替换的目标分辨率
        ma_type >
            res > 用户当前选择的restype类型
            source > 导入source文件
        '''
        
        #获取当前资产路径
        dir_temp = cmds.getAttr(f"{select_node}.assetDir").split("/")[:-1]
        #拼装路径名称(不带assetFormat)
        asset_dir = "/".join(dir_temp)
        
        #当前资产名称
        asset_name = cmds.getAttr(f"{select_node}.assetName")
        #当前分辨率类型
        current_res_type = cmds.getAttr(f"{select_node}.resolutionType")
        
        if ma_type == "res":
            #构建新资产名称
            new_asset_name = asset_name.replace(current_res_type,target_res)
            new_asset_path = f"{asset_dir}/{new_asset_name}.ma"
            
        elif ma_type == "source":
            new_asset_name = asset_name.replace(current_res_type,"src")
            new_asset_path = f"{asset_dir}/{new_asset_name}.ma"
        
        #如果文件存在
        if os.path.isfile(new_asset_path):
            #导入文件获取返回节点
            return_node = cmds.file(new_asset_path,i=True,returnNewNodes=True)
            #过滤保留transform
            transform_node =[node for node in return_node if cmds.nodeType(node) == "transform"]
        
            for node in transform_node:
                if not cmds.listRelatives(node,parent=True,fullPath=True):
                    root_locator = node
            
            #获取原始节点变换信息
            original_pos,original_rotate,original_scale = self.get_transform(select_node)
            
            self.set_transform(root_locator,translation=original_pos,rotation=original_rotate,
                        scale=original_scale)
            
        else:
            om.MGlobal.displayError(f"{new_asset_path} 文件路径不存在")
        

if __name__ == "__main__":
    
    #文件保存路径
    file_path = r"Z:\Project\DFH\Asset\component"
    #项目代号缩写
    project_code = "DFH"
    #场景名称缩写
    scene_prefix = "fhsj"
    
    path = file_path.replace("\\","/")
    window = UI(file_path = path, project_code = project_code,scene_prefix = scene_prefix)
    window.show()
    
    #####################################################
    
    

    
    
    
    