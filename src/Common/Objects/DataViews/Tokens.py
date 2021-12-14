import logging
from datetime import datetime
import webbrowser

import wx
import wx.grid
import wx.dataview as dv

from Common.GUIText import Filtering as GUIText
import Common.Constants as Constants
import Common.Objects.Datasets as Datasets
import Common.Objects.GUIs.Codes as CodesGUIs
import Common.Database as Database

class TokenGridTable(wx.grid.GridTableBase):
    def __init__(self, dataset, word_type):
        self.dataset = dataset
        self.word_type = word_type
        main_frame = wx.GetApp().GetTopWindow()
        
        self.search_term = ""
        self.sort_col = GUIText.FILTERS_NUM_WORDS
        self.sort_ascending = False

        db_conn = Database.DatabaseConnection(main_frame.current_workspace.name)
        if self.word_type == "Included":
            self.data = db_conn.GetIncludedStringTokens(self.dataset.key, self.search_term, self.sort_col, self.sort_ascending)
        else:
            self.data = db_conn.GetRemovedStringTokens(self.dataset.key, self.search_term, self.sort_col, self.sort_ascending)

        wx.grid.GridTableBase.__init__(self)
        self._rows = self.GetNumberRows()
        self.col_names = [GUIText.FILTERS_WORDS,
                          GUIText.FILTERS_POS,
                          GUIText.FILTERS_NUM_WORDS,
                          GUIText.FILTERS_NUM_DOCS,
                          GUIText.FILTERS_TFIDF_MIN,
                          GUIText.FILTERS_TFIDF_MAX]

        self._cols = len(self.col_names)

    def GetColLabelValue(self, col):
        name = str(self.col_names[col])
        return name
    
    def GetColTupleValue(self, col):
        return self.col_names[col]

    def GetNumberRows(self):
        """Return the number of rows in the grid"""
        return len(self.data)

    def GetNumberCols(self):
        """Return the number of columns in the grid"""
        return len(self.col_names)

    def GetTypeName(self, row, col):
        """Return the name of the data type of the value in the cell"""
        return wx.grid.GRID_VALUE_TEXT

    def GetValue(self, row, col):
        """Return the value of a cell"""
        row_data = self.data[row][:-1]
        if self.col_names[col] == GUIText.FILTERS_NUM_WORDS:
            return str(row_data[col]) +" (" +str(round((row_data[col]/self.dataset.total_tokens)*100, 4))+"%)"
        elif self.col_names[col] == GUIText.FILTERS_NUM_DOCS:
            return str(row_data[col]) +" (" +str(round((row_data[col]/self.dataset.total_docs)*100, 4))+"%)"
        else:
            return str(row_data[col])

    def SetValue(self, row, col, value):
        """Set the value of a cell"""
        pass

    def ResetView(self, grid):
        main_frame = wx.GetApp().GetTopWindow()
        db_conn = Database.DatabaseConnection(main_frame.current_workspace.name)
        if self.word_type == "Included":
            self.data = db_conn.GetIncludedStringTokens(self.dataset.key, self.search_term, self.sort_col, self.sort_ascending)
        else:
            self.data = db_conn.GetRemovedStringTokens(self.dataset.key, self.search_term, self.sort_col, self.sort_ascending)

        grid.BeginBatch()
        for current, new, delmsg, addmsg in [
            (self._rows, self.GetNumberRows(), wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED,
            wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED),
            (self._cols, self.GetNumberCols(), wx.grid.GRIDTABLE_NOTIFY_COLS_DELETED,
            wx.grid.GRIDTABLE_NOTIFY_COLS_APPENDED),
            ]:
            if new < current:
                msg = wx.grid.GridTableMessage(self, delmsg, new, current-new)
                grid.ProcessTableMessage(msg)
            elif new > current:
                msg = wx.grid.GridTableMessage(self, addmsg, new-current)
                grid.ProcessTableMessage(msg)
        self.UpdateValues(grid)
        grid.EndBatch()
        self._rows = self.GetNumberRows()
        self._cols = self.GetNumberCols()
        h,w = grid.GetSize()
        grid.SetSize((h+1, w))
        grid.SetSize((h, w))
        grid.ForceRefresh()
        self.UpdateValues(grid)
    
    def UpdateValues(self, grid):
        """Update all displayed values without changing the grid size"""
        msg = wx.grid.GridTableMessage(self, wx.grid.GRIDTABLE_REQUEST_VIEW_GET_VALUES)
        grid.ProcessTableMessage(msg)

class TokenGrid(wx.grid.Grid):
    def __init__(self, parent, dataset, word_type, size=wx.DefaultSize):
        logger = logging.getLogger(__name__+".TokenGrid.__init__")
        logger.info("Starting")
        wx.grid.Grid.__init__(self, parent, size=size)
        self.gridtable = TokenGridTable(dataset, word_type)
        self.SetTable(self.gridtable, takeOwnership=True)
        self.EnableEditing(False)
        self.UseNativeColHeader(True)
        self.HideRowLabels()
        self.SetSelectionMode(wx.grid.Grid.SelectRows)
        self.SetCellHighlightPenWidth(0)
        self.Bind(wx.grid.EVT_GRID_COL_SORT, self.OnSort)
        logger.info("Finished")

    def OnSort(self, event):
        logger = logging.getLogger(__name__+".TokenGrid.OnSort")
        logger.info("Starting")
        col = event.GetCol()
        col_string = self.gridtable.GetColTupleValue(event.GetCol())
        if col == self.GetSortingColumn():
            self.gridtable.sort_col = col_string
            if self.IsSortOrderAscending():
                self.gridtable.sort_ascending = True
            else:
                self.gridtable.sort_ascending = False
        else:
            self.SetSortingColumn(col)
            self.gridtable.sort_col = col_string
            self.gridtable.sort_ascending = True
        self.gridtable.ResetView(self)
        logger.info("Finish")

    def Update(self, search_term):
        logger = logging.getLogger(__name__+".TokenGrid.Update")
        logger.info("Starting")
        self.gridtable.search_term = search_term
        self.gridtable.ResetView(self)
        for i in range(0, len(self.gridtable.col_names)):
            self.SetColLabelValue(i, self.gridtable.GetColLabelValue(i))
        self.ForceRefresh()
        logger.info("Finish")

class DocumentListViewModel(dv.PyDataViewModel):
    def __init__(self, dataset, documents):
        dv.PyDataViewModel.__init__(self)
        self.dataset = dataset
        self.documents = documents
        self.UseWeakRefs(True)

        self.label_column_names = []
        self.label_column_types = []
        self.data_column_names = []
        self.data_column_types = []
        
        self.column_names = []
        self.UpdateColumnNames()
    
    def UpdateColumnNames(self):
        if hasattr(self.dataset, 'label_fields'):
            if len(self.dataset.label_fields) == 0:
                self.label_column_names.append('id')
                self.label_column_types.append('string')
            else:
                for key in self.dataset.label_fields:
                    field = self.dataset.label_fields[key]
                    self.label_column_names.append(field.name)
                    self.label_column_types.append(field.fieldtype)
        else:
            if self.dataset.dataset_source == "Reddit":
                self.label_column_names.append('url')
                self.label_column_types.append('url')
                if self.dataset.dataset_type == "discussion" or self.dataset.dataset_type == "submission":
                    self.label_column_names.append('title')
                    self.label_column_types.append('string')
                elif self.dataset.dataset_type == "comment":
                    self.label_column_names.append('body')
                    self.label_column_types.append('string')
            else:
                self.label_column_names.append('id')
                self.label_column_types.append('string')
        
        self.data_column_names.clear()
        self.data_column_types.clear()
        for key in self.dataset.computational_fields:
            field = self.dataset.computational_fields[key]
            if field.name not in self.label_column_names and field.name not in self.data_column_names:
                self.data_column_names.append(field.name)
                self.data_column_types.append(field.fieldtype)

    def GetColumnCount(self):
        '''Report how many columns this model provides data for.'''
        return len(self.label_column_names) + len(self.data_column_names)

    def GetChildren(self, parent, children):
        row_num = 0
        # If the parent item is invalid then it represents the hidden root
        # item, so we'll use the genre objects as its children and they will
        # end up being the collection of visible roots in our tree.
        if not parent:
            for document in self.documents:
                children.append(self.ObjectToItem(document))
        return len(children)

    def IsContainer(self, item):
        ''' Return True for MergedPart or Part, False otherwise for this model.'''
        # The hidden root is a container
        if not item:
            return True
        return False

    def GetParent(self, item):
        if not item:
            return dv.NullDataViewItem

        node = self.ItemToObject(item)
        if isinstance(node, Datasets.Document):
            return dv.NullDataViewItem

    def GetValue(self, item, col):
        ''''Fetch the data object for this item's column.'''
        node = self.ItemToObject(item)
        if isinstance(node, Datasets.Document):
            mapper = { }
            idx = 0
            for field_name in self.label_column_names:
                if field_name in node.parent.data[node.doc_id]:
                    value = node.parent.data[node.doc_id][field_name]
                    if self.label_column_types[idx] == 'url':
                        segmented_url = value.split("/")
                        if segmented_url[len(segmented_url)-1] != '':
                            segmented_id = segmented_url[len(segmented_url)-1]
                        else:
                            segmented_id = segmented_url[len(segmented_url)-2]
                        value = "<span color=\"#0645ad\"><u>"+segmented_id+"</u></span>"
                    elif self.label_column_types[idx] == 'UTC-timestamp':
                        if isinstance(value, list):
                            value_str = ""
                            for entry in value:
                                value_str = str(datetime.utcfromtimestamp(entry).strftime(Constants.DATETIME_FORMAT))+"UTC "
                                break
                            if len(value) > 1:
                                value = value_str + "..."
                            else:
                                value = value_str
                        else:
                            value = datetime.utcfromtimestamp(value).strftime(Constants.DATETIME_FORMAT)+"UTC"
                    elif self.label_column_types[idx] == 'int':
                        if isinstance(value, list):
                            value = value[0]
                        else:
                            value = value
                    else:
                        if isinstance(value, list):
                            first_entry = ""
                            for entry in value:
                                if entry != "":
                                    first_entry = ' '.join(entry.split())
                                    break
                            if len(value) > 1:
                                first_entry = str(first_entry) + " ..."
                            value = first_entry
                        value = str(value).split('\n')[0]
                else:
                    value = ""
                mapper[idx] = value
                idx = idx+1
            for field_name in self.data_column_names:
                if field_name not in self.label_column_names and field_name in node.parent.data[node.doc_id]:
                    value = node.parent.data[node.doc_id][field_name]
                    if self.data_column_types[idx-len(self.label_column_types)] == 'url':
                        segmented_url = value.split("/")
                        if segmented_url[len(segmented_url)-1] != '':
                            segment_id = segmented_url[len(segmented_url)-1]
                        else:
                            segment_id = segmented_url[len(segmented_url)-2]
                        value = "<span color=\"#0645ad\"><u>"+segment_id+"</u></span>"
                    elif self.data_column_types[idx-len(self.label_column_types)] == 'UTC-timestamp':
                        if isinstance(value, list):
                            value_str = ""
                            for entry in value:
                                value_str = str(datetime.utcfromtimestamp(entry).strftime(Constants.DATETIME_FORMAT))+"UTC "
                                break
                            if len(value) > 1:
                                value = value_str + "..."
                            else:
                                value = value_str
                        else:
                            value = datetime.utcfromtimestamp(value).strftime(Constants.DATETIME_FORMAT)+"UTC"
                    elif self.data_column_types[idx-len(self.label_column_types)] == 'int':
                        if isinstance(value, list):
                            value = value[0]
                        else:
                            value = value
                    else:
                        if isinstance(value, list):
                            first_entry = ""
                            for entry in value:
                                if entry != "":
                                    first_entry = ' '.join(entry.split())
                                    break
                            if len(value) > 1:
                                first_entry = str(first_entry) + " ..."
                            value = first_entry
                        value = str(value).split('\n')[0]
                else:
                    value = ""
                mapper[idx] = value
                idx = idx+1
            return mapper[col]
        else:
            raise RuntimeError("unknown node type")

    def GetAttr(self, item, col, attr):
        return False
    
    def HasContainerColumns(self, item):
        return True

#This view enables displaying datasets and how they are grouped
class DocumentListViewCtrl(dv.DataViewCtrl):
    def __init__(self, parent, model):
        dv.DataViewCtrl.__init__(self, parent, style=dv.DV_MULTIPLE|dv.DV_ROW_LINES|dv.DV_VARIABLE_LINE_HEIGHT)

        self.AssociateModel(model)
        model.DecRef()

        self.UpdateColumns()
        
        self.Bind(dv.EVT_DATAVIEW_ITEM_CONTEXT_MENU, self.OnShowPopup)
        self.Bind(dv.EVT_DATAVIEW_ITEM_ACTIVATED, self.OnOpen)
        self.Bind(wx.EVT_MENU, self.OnCopyItems, id=wx.ID_COPY)
        accel_tbl = wx.AcceleratorTable([(wx.ACCEL_CTRL, ord('C'), wx.ID_COPY)])
        self.SetAcceleratorTable(accel_tbl)

    def Expander(self, item, autosize_flg=True):
        model = self.GetModel()
        if item != None:
            self.Expand(item)
        children = []
        model.GetChildren(item, children)
        for child in children:
            self.Expander(child, False)
        if autosize_flg:
            self.AutoSize()
    
    def AutoSize(self):
        remaining_width = self.GetSize().GetWidth()*0.98
        col_count = self.GetColumnCount()
        col = 0
        for column in self.GetColumns():
            column.SetWidth(wx.COL_WIDTH_AUTOSIZE)
            col_width = column.GetWidth()
            if col_width > remaining_width/(col_count-col):
                col_width = remaining_width/(col_count-col)
                column.SetWidth(col_width)
            remaining_width = remaining_width - col_width
            col = col + 1

    def UpdateColumns(self):
        model = self.GetModel()
        self.ClearColumns()

        #add data columns
        idx = 0
        for field_name in model.label_column_names:
            if model.label_column_types[idx] == 'int':
                renderer = dv.DataViewTextRenderer(varianttype="long")
            elif model.label_column_types[idx] == 'url':
                renderer = dv.DataViewTextRenderer()
                renderer.EnableMarkup()
            else:
                renderer = dv.DataViewTextRenderer()
            column = dv.DataViewColumn(field_name, renderer, idx, align=wx.ALIGN_LEFT)
            self.AppendColumn(column)
            #column.SetWidth(wx.COL_WIDTH_AUTOSIZE)
            idx = idx+1

        for field_name in model.data_column_names:
            if model.label_column_types[idx-len(model.label_column_names)] == 'int':
                renderer = dv.DataViewTextRenderer(varianttype="long")
            elif model.label_column_types[idx-len(model.label_column_names)] == 'url':
                renderer = dv.DataViewTextRenderer()
                renderer.EnableMarkup()
            else:
                renderer = dv.DataViewTextRenderer()
            column = dv.DataViewColumn(field_name, renderer, idx, align=wx.ALIGN_LEFT)
            self.AppendColumn(column)
            #column.SetWidth(wx.COL_WIDTH_AUTOSIZE)
            idx = idx+1

        for column in self.Columns:
            column.Sortable = True
            column.Reorderable = True
            column.Resizeable = True
        
        self.Expander(None)

    def OnShowPopup(self, event):
        logger = logging.getLogger(__name__+".PartsViewCtrl.OnShowPopup")
        logger.info("Starting")
        menu = wx.Menu()
        menu.Append(1, GUIText.COPY)
        menu.Bind(wx.EVT_MENU, self.OnCopyItems)
        self.PopupMenu(menu)
        logger.info("Finished")

    def OnOpen(self, event):
        logger = logging.getLogger(__name__+".PartsViewCtrl.OnOpen")
        logger.info("Starting")
        model = self.GetModel()
        item = event.GetItem()
        node = model.ItemToObject(item)

        if isinstance(node, Datasets.Document):
            col = event.GetColumn()
            if 0 < col < len(model.label_column_names)+1 and model.label_column_types[col-1] == 'url':
                logger.info("Call to access url[%s]", node.url)
                webbrowser.open_new_tab(node.url)
            else:
                main_frame = wx.GetApp().GetTopWindow()
                if node.key not in main_frame.document_dialogs:
                    main_frame.document_dialogs[node.key] = CodesGUIs.DocumentDialog(main_frame, node)
                main_frame.document_dialogs[node.key].Show()
                main_frame.document_dialogs[node.key].SetFocus()
        logger.info("Finished")

    def OnCopyItems(self, event):
        logger = logging.getLogger(__name__+".PartsViewCtrl.OnCopyItems")
        logger.info("Starting")
        selected_items = []
        model = self.GetModel()
        for row in self.GetSelections():
            line = ''
            for col in range(0, model.label_column_names):
                line = line + str(model.GetValue(row, col)) + '\t'
            selected_items.append(line.strip())
        clipdata = wx.TextDataObject()
        clipdata.SetText("\n".join(selected_items))
        wx.TheClipboard.Open()
        wx.TheClipboard.SetData(clipdata)
        wx.TheClipboard.Close()
        logger.info("Finished")
