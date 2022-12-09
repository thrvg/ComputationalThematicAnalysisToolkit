import logging
import copy
from datetime import datetime

import wx
import wx.lib.scrolledpanel

from Common.GUIText import Collection as GUIText
import Common.CustomEvents as CustomEvents
import Common.Objects.Datasets as Datasets
import Common.Objects.DataViews.Datasets as DatasetsDataViews
import Common.Objects.Threads.Datasets as DatasetsThreads
import Common.Database as Database

class FieldsDialog(wx.Dialog):
    def __init__(self, parent, title, dataset, fields, label_fields=False, size=wx.DefaultSize):
        logger = logging.getLogger(__name__+".FieldsDialog["+str(dataset.key)+"].__init__")
        logger.info("Starting")
        wx.Dialog.__init__(self, parent, title=title, size=size, style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER|wx.MAXIMIZE_BOX|wx.MINIMIZE_BOX)
        sizer = wx.BoxSizer()
        self.dataset = dataset

        self.fields_panel = FieldsPanel(self, dataset, fields, label_fields_flg=label_fields,  size=self.GetSize())
        sizer.Add(self.fields_panel, 1, wx.EXPAND)
        self.SetSizer(sizer)
        logger.info("Finished")

class FieldsPanel(wx.Panel):
    def __init__(self, parent, dataset, fields, label_fields_flg=False, size=wx.DefaultSize):
        logger = logging.getLogger(__name__+".FieldsPanel.__init__")
        logger.info("Starting")
        wx.Panel.__init__(self, parent, size=size)

        splitter = wx.SplitterWindow(self)

        self.dataset = dataset
        self.fields = fields
        self.label_fields_flg = label_fields_flg
        self.tokenization_thread = None

        available_panel = wx.Panel(splitter)
        available_sizer = wx.StaticBoxSizer(wx.VERTICAL, available_panel, GUIText.FIELDS_AVAILABLE_LABEL)
        add_btn = wx.Button(available_panel, label=GUIText.ADD)
        add_btn.SetToolTip(GUIText.FIELDS_ADD_TOOLTIP)
        add_btn.Bind(wx.EVT_BUTTON, self.OnAddFields)
        available_sizer.Add(add_btn, proportion=0, flag=wx.ALL, border=5)
        self.available_fields_model = DatasetsDataViews.AvailableFieldsViewModel(dataset)
        self.available_fields_ctrl = DatasetsDataViews.FieldsViewCtrl(available_panel, self.available_fields_model)
        available_sizer.Add(self.available_fields_ctrl, proportion=1, flag=wx.EXPAND, border=5)
        available_panel.SetSizer(available_sizer)

        chosen_panel = wx.Panel(splitter)
        chosen_sizer = wx.StaticBoxSizer(wx.VERTICAL, chosen_panel, GUIText.FIELDS_INCLUDED_LABEL)
        #TODO Rework to be set of buttons to avoid Windows to OSX compatibility issues
        remove_btn = wx.Button(chosen_panel, label=GUIText.REMOVE)
        remove_btn.SetToolTip(GUIText.FIELDS_REMOVE_TOOLTIP)
        remove_btn.Bind(wx.EVT_BUTTON, self.OnRemoveFields)
        chosen_sizer.Add(remove_btn, proportion=0, flag=wx.ALL, border=5)
        self.chosen_fields_model = DatasetsDataViews.ChosenFieldsViewModel(fields)
        self.chosen_fields_ctrl = DatasetsDataViews.FieldsViewCtrl(chosen_panel, self.chosen_fields_model)
        chosen_sizer.Add(self.chosen_fields_ctrl, proportion=1, flag=wx.EXPAND, border=5)
        chosen_panel.SetSizer(chosen_sizer)

        splitter.SetMinimumPaneSize(20)
        splitter.SplitVertically(available_panel, chosen_panel)
        splitter.SetSashPosition(int(self.GetSize().GetWidth()/2))
        
        sizer = wx.BoxSizer()
        sizer.Add(splitter, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        self.SetSizer(sizer)

        CustomEvents.TOKENIZER_EVT_RESULT(self, self.OnTokenizerEnd)
        
        self.Layout()

        logger.info("Finished")

    def OnAddFields(self, event):
        logger = logging.getLogger(__name__+".FieldsPanel.OnAddFieldsStart")
        logger.info("Starting")
        tokenize_fields = []
        performed_flag = False

        def FieldAdder(field):
            add_flag = True
            if field.key in self.fields :
                wx.MessageBox(GUIText.FIELDS_EXISTS_ERROR+str(node.name),
                              GUIText.WARNING, wx.OK | wx.ICON_WARNING)
            elif add_flag:
                self.fields[field.key] = field
                self.last_changed_dt = datetime.now()
                nonlocal tokenize_fields
                if not self.label_fields_flg:
                    tokenize_fields.append(field)
                else:
                    nonlocal performed_flag
                    performed_flag = True


        main_frame = wx.GetApp().GetTopWindow()
        if main_frame.multiprocessing_inprogress_flag:
            wx.MessageBox(GUIText.MULTIPROCESSING_WARNING_MSG,
                          GUIText.WARNING, wx.OK | wx.ICON_WARNING)
            return
        if not self.label_fields_flg:
            main_frame.CreateProgressDialog(GUIText.ADDING_COMPUTATIONAL_FIELDS_BUSY_LABEL,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
        else:
            main_frame.CreateProgressDialog(GUIText.ADDING_LABEL_FIELDS_BUSY_LABEL,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)

        main_frame.StepProgressDialog(GUIText.ADDING_LABEL_FIELDS_BUSY_LABEL)
        for item in self.available_fields_ctrl.GetSelections():
            node = self.available_fields_model.ItemToObject(item)
            main_frame.PulseProgressDialog(GUIText.ADDING_FIELDS_BUSY_MSG+str(node.name))
            if isinstance(node, Datasets.Field):
                FieldAdder(node)
        if len(tokenize_fields) > 0:
            main_frame.multiprocessing_inprogress_flag = True
            self.tokenization_thread = DatasetsThreads.TokenizerThread(self, main_frame, self.dataset, tfidf_update=True)
        elif performed_flag:
            self.OnTokenizerEnd(None)
        else:
            main_frame.CloseProgressDialog(thaw=True)
            self.GetTopLevelParent().Enable()
            self.GetTopLevelParent().SetFocus()

    def OnRemoveFields(self, event):
        logger = logging.getLogger(__name__+".FieldsPanel.OnRemoveFields")
        logger.info("Starting")
        main_frame = self.GetGrandParent().GetTopLevelParent()
        performed_flag = False
        tokenize_flag = False

        def FieldRemover(field):
            item = self.chosen_fields_model.ObjectToItem(field)
            parent_item = self.chosen_fields_model.GetParent(item)
            self.chosen_fields_model.ItemDeleted(parent_item, item)
            if not self.label_fields_flg:
                db_conn.DeleteField(self.dataset.key, field.key)
                nonlocal tokenize_flag
                tokenize_flag = True
            else:
                nonlocal performed_flag
                performed_flag = True
            del self.fields[field.key]

        if not self.label_fields_flg:    
            main_frame.CreateProgressDialog(GUIText.REMOVING_COMPUTATIONAL_FIELDS_BUSY_LABEL,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
        else:
            main_frame.CreateProgressDialog(GUIText.REMOVING_LABEL_FIELDS_BUSY_LABEL,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)

        main_frame.StepProgressDialog(GUIText.REMOVING_FIELDS_BUSY_LABEL)
        db_conn = Database.DatabaseConnection(main_frame.current_workspace.name)
        for item in self.chosen_fields_ctrl.GetSelections():
            node = self.chosen_fields_model.ItemToObject(item)
            main_frame.PulseProgressDialog(GUIText.REMOVING_FIELDS_BUSY_MSG+str(node.name))
            if isinstance(node, Datasets.Field):
                FieldRemover(node)
        del db_conn
        if tokenize_flag:
            main_frame.multiprocessing_inprogress_flag = True
            self.tokenization_thread = DatasetsThreads.TokenizerThread(self, main_frame, self.dataset, tfidf_update=True)
        elif performed_flag:
            self.OnTokenizerEnd(None)
        else:
            main_frame.CloseProgressDialog(thaw=True)
            self.GetTopLevelParent().Enable()
            self.GetTopLevelParent().SetFocus()
        logger.info("Finished")

    def OnTokenizerEnd(self, event):
        logger = logging.getLogger(__name__+".FieldsPanel.OnAddFieldsEnd")
        logger.info("Starting")
        if self.tokenization_thread != None:
            self.tokenization_thread.join()
            self.tokenization_thread = None
        self.chosen_fields_model.Cleared()
        self.chosen_fields_ctrl.Expander(None)
        main_frame = wx.GetApp().GetTopWindow()
        main_frame.DatasetsUpdated()
        main_frame.CloseProgressDialog(thaw=True)
        main_frame.multiprocessing_inprogress_flag = False
        self.GetTopLevelParent().Enable()
        self.GetTopLevelParent().SetFocus()
        logger.info("Finished")

    def Load(self, saved_data):
        logger = logging.getLogger(__name__+".FieldsPanel.Load")
        logger.info("Starting")
        logger.info("Finished")

    def Save(self):
        logger = logging.getLogger(__name__+".FieldsPanel.Save")
        logger.info("Starting")
        saved_data = {}
        logger.info("Finished")
        return saved_data
