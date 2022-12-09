import logging
import os.path
import tweepy
import chardet
import pytz
import csv
import re

import wx
import wx.adv
import wx.grid

import Common.Constants as Constants
from Common.GUIText import Collection as GUIText
import Common.CustomEvents as CustomEvents
import Common.Database as Database
import Common.Objects.GUIs.Generic as GenericGUIs
import Collection.CollectionThreads as CollectionThreads

class AbstractRetrieverDialog(wx.Dialog):
    def OnRetrieveEnd(self, event):
        logger = logging.getLogger(__name__+".AbstractRetrieverDialog.OnRetrieveEnd")
        logger.info("Starting")
        main_frame = wx.GetApp().GetTopWindow()
        if event.data['status_flag']:
            if 'dataset' in event.data:
                dataset_key = event.data['dataset_key']
                if dataset_key in main_frame.datasets:
                    main_frame.datasets[dataset_key].DestroyObject()
                    Database.DatabaseConnection(main_frame.current_workspace.name).DeleteDataset(dataset_key)
                main_frame.datasets[dataset_key] = event.data['dataset']
            elif 'datasets' in event.data:
                for dataset_key in event.data['datasets']:
                    i = 0
                    new_dataset_key = dataset_key
                    while new_dataset_key in main_frame.datasets:
                        i += 1
                        new_dataset_key = (dataset_key[0]+"_"+str(i), dataset_key[1], dataset_key[2])
                    main_frame.datasets[new_dataset_key] = event.data['datasets'][dataset_key]
            main_frame.DatasetsUpdated()
            self.Destroy()
        else:
            wx.MessageBox(event.data['error_msg'],
                          GUIText.ERROR,
                          wx.OK | wx.ICON_ERROR)
            self.Thaw()
            self.Enable()
            self.Show()
            self.SetFocus()
        self.retrieval_thread = None
        main_frame.CloseProgressDialog(thaw=True)
        logger.info("Finished")

class RedditDatasetRetrieverDialog(AbstractRetrieverDialog):
    def __init__(self, parent):
        logger = logging.getLogger(__name__+".RedditRetrieverDialog.__init__")
        logger.info("Starting")
        wx.Dialog.__init__(self, parent, title=GUIText.REDDIT_RETRIEVE_LABEL, style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.retrieval_thread = None
        self.available_fields = {}

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.error_label = wx.StaticText(self, label="")
        self.error_label.SetForegroundColour(wx.Colour(255, 0, 0))
        sizer.Add(self.error_label, 0, wx.ALL, 5)
        self.error_label.Hide()
        
        main_frame = wx.GetApp().GetTopWindow()
        if main_frame.options_dict['multipledatasets_mode']:
            name_label = wx.StaticText(self, label=GUIText.NAME + " ")
            name_info = GenericGUIs.InfoIcon(self, GUIText.NAME_TOOLTIP)
            self.name_ctrl = wx.TextCtrl(self)
            self.name_ctrl.SetToolTip(GUIText.NAME_TOOLTIP)
            name_sizer = wx.BoxSizer(wx.HORIZONTAL)
            name_sizer.Add(name_label, 0, wx.ALIGN_CENTRE_VERTICAL)
            name_sizer.Add(name_info, 0, wx.ALIGN_CENTRE_VERTICAL)
            name_sizer.Add(self.name_ctrl)
            sizer.Add(name_sizer, 0, wx.ALL, 5)

        datasetconfig_box = wx.StaticBox(self, label=GUIText.DATASET_CONFIGURATIONS)
        datasetconfig_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        datasetconfig_sizer = wx.StaticBoxSizer(datasetconfig_box, wx.VERTICAL)
        sizer.Add(datasetconfig_sizer, 0, wx.ALL|wx.EXPAND, 5)

        #TODO enhance ability to integrate multiple subreddits
        subreddit_label = wx.StaticText(self, label=GUIText.REDDIT_SUBREDDIT)
        subreddit_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_SUBREDDIT_TOOLTIP)
        self.subreddit_ctrl = wx.TextCtrl(self)
        self.subreddit_ctrl.SetToolTip(GUIText.REDDIT_SUBREDDIT_TOOLTIP)
        subreddit_sizer = wx.BoxSizer(wx.HORIZONTAL)
        subreddit_sizer.Add(subreddit_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        subreddit_sizer.Add(subreddit_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        subreddit_sizer.Add(self.subreddit_ctrl, 1, wx.EXPAND)
        datasetconfig_sizer.Add(subreddit_sizer, 0, wx.ALL|wx.EXPAND, 5)

        h_sizer = wx.BoxSizer()
        datasetconfig_sizer.Add(h_sizer)
        #choose type of dataset to retrieve
        dataset_type_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dataset_type_label = wx.StaticText(self, label=GUIText.TYPE+" ")
        info_text = GUIText.REDDIT_DISCUSSIONS +" - " + GUIText.REDDIT_DISCUSSIONS_TOOLTIP + "\n"\
                    ""+GUIText.REDDIT_SUBMISSIONS +" - " + GUIText.REDDIT_SUBMISSIONS_TOOLTIP + "\n"\
                    ""+GUIText.REDDIT_COMMENTS +" - " + GUIText.REDDIT_COMMENTS_TOOLTIP
        dataset_type_info = GenericGUIs.InfoIcon(self, info_text)
        self.dataset_type_choice = wx.Choice(self, choices=[GUIText.REDDIT_DISCUSSIONS,
                                                            GUIText.REDDIT_SUBMISSIONS,
                                                            GUIText.REDDIT_COMMENTS])
        self.dataset_type_choice.Bind(wx.EVT_CHOICE, self.OnDatasetTypeChosen)
        dataset_type_sizer.Add(dataset_type_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        dataset_type_sizer.Add(dataset_type_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        dataset_type_sizer.Add(self.dataset_type_choice)
        h_sizer.Add(dataset_type_sizer, 0, wx.ALL, 5)

        language_label = wx.StaticText(self, label=GUIText.LANGUAGE+" ")
        #language_info = GenericGUIs.InfoIcon(self, GUIText.LANGUAGE_TOOLTIP)
        self.language_ctrl = wx.Choice(self, choices=Constants.AVAILABLE_DATASET_LANGUAGES2)
        self.language_ctrl.Select(0)
        language_sizer = wx.BoxSizer(wx.HORIZONTAL)
        language_sizer.Add(language_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        #language_sizer.Add(language_type_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        language_sizer.Add(self.language_ctrl)
        h_sizer.Add(language_sizer, 0, wx.ALL, 5)

        dataconstraints_box = wx.StaticBox(self, label=GUIText.DATA_CONSTRAINTS)
        dataconstraints_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        dataconstraints_sizer = wx.StaticBoxSizer(dataconstraints_box, wx.VERTICAL)
        sizer.Add(dataconstraints_sizer, 0, wx.ALL|wx.EXPAND, 5)

        start_date_label = wx.StaticText(self, label=GUIText.START_DATE+" ")
        start_date_info = GenericGUIs.InfoIcon(self, GUIText.START_DATE_TOOLTIP)
        self.start_date_ctrl = wx.adv.DatePickerCtrl(self, name="startDate",
                                                style=wx.adv.DP_DROPDOWN|wx.adv.DP_SHOWCENTURY)
        self.start_date_ctrl.SetToolTip(GUIText.START_DATE_TOOLTIP)
        end_date_label = wx.StaticText(self, label=GUIText.END_DATE+" ")
        end_date_info = GenericGUIs.InfoIcon(self, GUIText.END_DATE_TOOLTIP)
        self.end_date_ctrl = wx.adv.DatePickerCtrl(self, name="endDate",
                                              style=wx.adv.DP_DROPDOWN|wx.adv.DP_SHOWCENTURY)
        self.end_date_ctrl.SetToolTip(GUIText.END_DATE_TOOLTIP)
        date_sizer = wx.BoxSizer(wx.HORIZONTAL)
        date_sizer.Add(start_date_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        date_sizer.Add(start_date_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        date_sizer.Add(self.start_date_ctrl)
        date_sizer.AddSpacer(10)
        date_sizer.Add(end_date_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        date_sizer.Add(end_date_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        date_sizer.Add(self.end_date_ctrl)
        dataconstraints_sizer.Add(date_sizer, 0, wx.ALL, 5)

        #TODO enhance integration of search to allow complex queries (currently only supports literial string entered in text box)
        search_label = wx.StaticText(self, label=GUIText.REDDIT_CONTAINS_TEXT+"(Optional) ")
        search_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_CONTAINS_TEXT_TOOLTIP)
        self.search_ctrl = wx.TextCtrl(self)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_sizer.Add(search_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        search_sizer.Add(search_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        search_sizer.Add(self.search_ctrl, 1, wx.EXPAND)
        dataconstraints_sizer.Add(search_sizer, 0, wx.ALL|wx.EXPAND, 5)

        #control the subsource of where data is retrieved from
        source_box = wx.StaticBox(self, label=GUIText.SOURCE)
        source_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        source_sizer = wx.StaticBoxSizer(source_box, wx.VERTICAL)
        self.update_pushshift_radioctrl = wx.RadioButton(self, label=GUIText.REDDIT_UPDATE_PUSHSHIFT, style=wx.RB_GROUP)
        self.update_pushshift_radioctrl.SetToolTip(GUIText.REDDIT_UPDATE_PUSHSHIFT_TOOLTIP)
        self.update_pushshift_radioctrl.SetValue(True)
        update_pushshift_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_UPDATE_PUSHSHIFT_TOOLTIP)
        update_pushshift_sizer = wx.BoxSizer(wx.HORIZONTAL)
        update_pushshift_sizer.Add(self.update_pushshift_radioctrl)
        update_pushshift_sizer.Add(update_pushshift_info, 0, wx.ALIGN_CENTER_VERTICAL)
        source_sizer.Add(update_pushshift_sizer, 0, wx.ALL, 5)
        #TODO add ability to dynamically update from reddit information like Score
        #self.update_redditapi_radioctrl = wx.RadioButton(self, label=GUIText.REDDIT_API)
        #self.update_redditapi_radioctrl.SetToolTipString(GUIText.REDDIT_UPDATE_REDDITAPI_TOOLTIP)
        #update_redditapi_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_UPDATE_REDDITAPI_TOOLTIP)
        #update_redditapi_sizer = wx.BoxSizer(wx.HORIZONTAL)
        #update_redditapi_sizer.Add(self.update_redditapi_radioctrl)
        #update_redditapi_sizer.Add(update_redditapi_info, 0, wx.ALIGN_CENTER_VERTICAL)
        #source_sizer.Add(update_redditapi_sizer, 0, wx.ALL, 5)
        #self.full_redditapi_radioctrl = wx.RadioButton(self, label=GUIText.REDDIT_API)
        #self.full_redditapi_radioctrl.SetToolTipString(GUIText.REDDIT_FULL_REDDITAPI_TOOLTIP)
        #full_redditapi_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_FULL_REDDITAPI_TOOLTIP)
        #full_redditapi_sizer = wx.BoxSizer(wx.HORIZONTAL)
        #full_redditapi_sizer.Add(self.full_redditapi_radioctrl)
        #full_redditapi_sizer.Add(full_redditapi_info, 0, wx.ALIGN_CENTER_VERTICAL)
        #source_sizer.Add(full_redditapi_sizer, 0, wx.ALL, 5)
        self.archived_radioctrl = wx.RadioButton(self, label=GUIText.REDDIT_ARCHIVED)
        self.archived_radioctrl.SetToolTip(GUIText.REDDIT_ARCHIVED_TOOLTIP)
        archived_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_ARCHIVED_TOOLTIP)
        archived_sizer = wx.BoxSizer(wx.HORIZONTAL)
        archived_sizer.Add(self.archived_radioctrl)
        archived_sizer.Add(archived_info, 0, wx.ALIGN_CENTER_VERTICAL)
        source_sizer.Add(archived_sizer, 0, wx.ALL, 5)
        self.full_pushshift_radioctrl = wx.RadioButton(self, label=GUIText.REDDIT_FULL_PUSHSHIFT)
        self.full_pushshift_radioctrl.SetToolTip(GUIText.REDDIT_FULL_PUSHSHIFT_TOOLTIP)
        full_pushshift_info = GenericGUIs.InfoIcon(self, GUIText.REDDIT_FULL_PUSHSHIFT_TOOLTIP)
        full_pushshift_sizer = wx.BoxSizer(wx.HORIZONTAL)
        full_pushshift_sizer.Add(self.full_pushshift_radioctrl)
        full_pushshift_sizer.Add(full_pushshift_info, 0, wx.ALIGN_CENTER_VERTICAL)
        source_sizer.Add(full_pushshift_sizer, 0, wx.ALL, 5)
        sizer.Add(source_sizer, 0, wx.ALL|wx.EXPAND, 5)

        label_fields_label = wx.StaticText(self, label=GUIText.LABEL_FIELDS)
        label_fields_info = GenericGUIs.InfoIcon(self, GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.label_fields_ctrl.AppendColumn(GUIText.FIELD)
        self.label_fields_ctrl.AppendColumn(GUIText.DESCRIPTION)
        self.label_fields_ctrl.AppendColumn(GUIText.TYPE)
        self.label_fields_ctrl.SetToolTip(GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_ctrl.EnableCheckBoxes()
        label_fields_sizer = wx.BoxSizer(wx.VERTICAL)
        label_fields_sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        label_fields_sizer2.Add(label_fields_label)
        label_fields_sizer2.Add(label_fields_info)
        label_fields_sizer.Add(label_fields_sizer2, 0, wx.ALL)
        label_fields_sizer.Add(self.label_fields_ctrl, 1, wx.EXPAND)
        if main_frame.options_dict['adjustable_label_fields_mode']:
            sizer.Add(label_fields_sizer, 1, wx.ALL|wx.EXPAND, 5)
        else:
            label_fields_sizer.ShowItems(False)

        computational_fields_label = wx.StaticText(self, label=GUIText.COMPUTATIONAL_FIELDS)
        computational_fields_info = GenericGUIs.InfoIcon(self, GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computational_fields_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.computational_fields_ctrl.AppendColumn(GUIText.FIELD)
        self.computational_fields_ctrl.AppendColumn(GUIText.DESCRIPTION)
        self.computational_fields_ctrl.AppendColumn(GUIText.TYPE)
        self.computational_fields_ctrl.SetToolTip(GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computational_fields_ctrl.EnableCheckBoxes()
        computational_fields_sizer = wx.BoxSizer(wx.VERTICAL)
        computational_fields_sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        computational_fields_sizer2.Add(computational_fields_label)
        computational_fields_sizer2.Add(computational_fields_info)
        computational_fields_sizer.Add(computational_fields_sizer2, 0, wx.ALL)
        computational_fields_sizer.Add(self.computational_fields_ctrl, 1, wx.EXPAND)
        if main_frame.options_dict['adjustable_computation_fields_mode']:
            sizer.Add(computational_fields_sizer, 1, wx.ALL|wx.EXPAND, 5)
        else:
            computational_fields_sizer.ShowItems(False)

        ethics_box = wx.StaticBox(self, label=GUIText.ETHICAL_CONSIDERATIONS)
        ethics_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        ethics_sizer = wx.StaticBoxSizer(ethics_box, wx.VERTICAL)
        self.ethics_community1_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY1_REDDIT)
        ethics_sizer.Add(self.ethics_community1_ctrl, 0, wx.ALL, 5)
        self.ethics_community2_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY2_REDDIT)
        ethics_sizer.Add(self.ethics_community2_ctrl, 0, wx.ALL, 5)
        self.ethics_research_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_RESEARCH)
        ethics_sizer.Add(self.ethics_research_ctrl, 0, wx.ALL, 5)
        self.ethics_institution_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_INSTITUTION)
        ethics_sizer.Add(self.ethics_institution_ctrl, 0, wx.ALL, 5)
        self.ethics_reddit_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_REDDIT)
        ethics_reddit_url = wx.adv.HyperlinkCtrl(self, label="1", url=GUIText.ETHICS_REDDIT_URL)
        ethics_redditapi_url = wx.adv.HyperlinkCtrl(self, label="2", url=GUIText.ETHICS_REDDITAPI_URL)
        ethics_reddit_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ethics_reddit_sizer.Add(self.ethics_reddit_ctrl)
        ethics_reddit_sizer.Add(ethics_reddit_url)
        ethics_reddit_sizer.AddSpacer(5)
        ethics_reddit_sizer.Add(ethics_redditapi_url)
        ethics_sizer.Add(ethics_reddit_sizer, 0, wx.ALL, 5)
        self.ethics_pushshift_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_PUSHSHIFT)
        ethics_sizer.Add(self.ethics_pushshift_ctrl, 0, wx.ALL, 5)
        sizer.Add(ethics_sizer, 0, wx.ALL, 5)

        #Retriever button to collect the requested data
        controls_sizer = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        ok_button = wx.FindWindowById(wx.ID_OK, self)
        ok_button.SetLabel(GUIText.DATASETS_RETRIEVE_REDDIT)
        sizer.Add(controls_sizer, 0, wx.ALIGN_RIGHT|wx.ALL, 5)

        self.SetSizer(sizer)
        self.Layout()
        self.Fit()

        #fix since some operatign systems default to first element of the list instead of blank like windows
        if self.dataset_type_choice.GetStringSelection() != '':
            self.OnDatasetTypeChosen(None)

        ok_button.Bind(wx.EVT_BUTTON, self.OnRetrieveStart)
        CustomEvents.RETRIEVE_EVT_RESULT(self, self.OnRetrieveEnd)

        logger.info("Finished")

    def OnDatasetTypeChosen(self, event):
        logger = logging.getLogger(__name__+".RedditRetrieverDialog.OnDatasetTypeChosen")
        logger.info("Starting")
        dataset_type = self.dataset_type_choice.GetStringSelection()
        if dataset_type == GUIText.REDDIT_DISCUSSIONS:
            dataset_type = 'discussion'
        elif dataset_type == GUIText.REDDIT_SUBMISSIONS:
            dataset_type = 'submission'
        elif dataset_type == GUIText.REDDIT_COMMENTS:
            dataset_type = 'comment'

        self.available_fields = Constants.available_fields[('Reddit', dataset_type,)]

        self.label_fields_ctrl.DeleteAllItems()
        self.computational_fields_ctrl.DeleteAllItems()
        idx = 0
        for key in self.available_fields:
            self.label_fields_ctrl.Append([key, self.available_fields[key]['desc'], self.available_fields[key]['type']])
            if self.available_fields[key]['label_fields_default']:
                self.label_fields_ctrl.CheckItem(idx)
            self.computational_fields_ctrl.Append([key, self.available_fields[key]['desc'], self.available_fields[key]['type']])
            if self.available_fields[key]['computation_fields_default']:
                self.computational_fields_ctrl.CheckItem(idx)
            idx = idx+1

        self.Layout()
        self.Fit()
        logger.info("Finished")

    def OnRetrieveStart(self, event):
        logger = logging.getLogger(__name__+".RedditRetrieverDialog.OnRetrieveStart")
        logger.info("Starting")

        error_messages = []

        main_frame = wx.GetApp().GetTopWindow()
        if main_frame.options_dict['multipledatasets_mode']:
            name = self.name_ctrl.GetValue()
            if name == "":
                error_messages.append(GUIText.NAME_MISSING_ERROR)
                logger.warning('No name entered')
        else:
            name = self.subreddit_ctrl.GetValue() 
        subreddit = self.subreddit_ctrl.GetValue()

        if subreddit == "":
            error_messages.append(GUIText.REDDIT_SUBREDDIT_MISSING_ERROR)
            logger.warning('No subreddit entered')
        else:
            subreddits = str(subreddit).split(',')
            if len(subreddits) > 0:
                for i in range(len(subreddits)):
                    subreddits[i] = str(subreddits[i]).strip()

        dataset_type_id = self.dataset_type_choice.GetSelection()
        dataset_type = ""
        if dataset_type_id is wx.NOT_FOUND:
            error_messages.append(GUIText.TYPE_ERROR)
            logger.warning("No Data type was selected for retrieval")
        else:
            dataset_type = self.dataset_type_choice.GetString(dataset_type_id)
        if dataset_type == GUIText.REDDIT_DISCUSSIONS:
            dataset_type = 'discussion'
        elif dataset_type == GUIText.REDDIT_SUBMISSIONS:
            dataset_type = 'submission'
        elif dataset_type == GUIText.REDDIT_COMMENTS:
            dataset_type = 'comment'
        
        language = Constants.AVAILABLE_DATASET_LANGUAGES1[self.language_ctrl.GetSelection()]
        
        start_date = str(self.start_date_ctrl.GetValue().Format("%Y-%m-%d"))
        end_date = str(self.end_date_ctrl.GetValue().Format("%Y-%m-%d"))
        if start_date > end_date:
            error_messages.append(GUIText.DATE_ERROR)
            logger.warning("Start Date[%s] not before End Date[%s]",
                           str(start_date), str(end_date))
        
        search = self.search_ctrl.GetValue()
        
        #determine what type of retrieval is to be performed
        replace_archive_flg = self.full_pushshift_radioctrl.GetValue() #or  self.full_redditapi_radioctrl.GetValue()
        pushshift_flg = self.full_pushshift_radioctrl.GetValue() or self.update_pushshift_radioctrl.GetValue()
        redditapi_flg = False
        #redditapi_flg = self.update_redditapi_radioctrl.GetValue() or self.full_redditapi_radioctrl.GetValue()
        
        label_fields_list = []
        item = self.label_fields_ctrl.GetNextItem(-1)
        if len(subreddits) > 1 and not main_frame.options_dict['adjustable_label_fields_mode']:
            if dataset_type == 'discussion':
                label_fields_list.append(('submission.subreddit', self.available_fields['submission.subreddit'],))
            elif dataset_type == 'submission' or dataset_type == 'submission':
                label_fields_list.append(('subreddit', self.available_fields['subreddit'],))
        while item != -1:
            if self.label_fields_ctrl.IsItemChecked(item):
                field_name = self.label_fields_ctrl.GetItemText(item, 0)
                label_fields_list.append((field_name, self.available_fields[field_name],))
            item = self.label_fields_ctrl.GetNextItem(item)
        
        computational_fields_list = []
        item = self.computational_fields_ctrl.GetNextItem(-1)
        while item != -1:
            if self.computational_fields_ctrl.IsItemChecked(item):
                field_name = self.computational_fields_ctrl.GetItemText(item, 0)
                computational_fields_list.append((field_name, self.available_fields[field_name],))
            item = self.computational_fields_ctrl.GetNextItem(item)

        if not self.ethics_community1_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY1_REDDIT)
            logger.warning('Ethics not checked')
        if not self.ethics_community2_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY2_REDDIT)
            logger.warning('Ethics not checked')
        if not self.ethics_research_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_RESEARCH)
            logger.warning('Ethics not checked')
        if not self.ethics_institution_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_INSTITUTION)
            logger.warning('Ethics not checked')
        if not self.ethics_reddit_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_REDDIT)
            logger.warning('Ethics not checked')
        if not self.ethics_pushshift_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_PUSHSHIFT)
            logger.warning('Ethics not checked')

        if len(error_messages) == 0:
            main_frame.CreateProgressDialog(title=GUIText.RETRIEVING_LABEL+name,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
            self.error_label.Hide()
            self.Layout()
            self.Fit()
            self.Hide()
            self.Disable()
            self.Freeze()
            main_frame.PulseProgressDialog(GUIText.RETRIEVING_BEGINNING_MSG)
            self.retrieval_thread = CollectionThreads.RetrieveRedditDatasetThread(self, main_frame, name, language, subreddits, search, start_date, end_date,
                                                                                  replace_archive_flg, pushshift_flg, redditapi_flg, dataset_type,
                                                                                  list(self.available_fields.items()), label_fields_list, computational_fields_list)
        else:
            error_text = "-" + "\n-".join(error_messages)
            self.error_label.SetLabel(error_text)
            self.error_label.Show()
            self.Layout()
            self.Fit()
        logger.info("Finished")

class TwitterDatasetRetrieverDialog(AbstractRetrieverDialog):
    def __init__(self, parent):
        logger = logging.getLogger(__name__+".TwitterRetrieverDialog.__init__")
        logger.info("Starting")
        wx.Dialog.__init__(self, parent, title=GUIText.TWITTER_RETRIEVE_LABEL, style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.retrieval_thread = None
        self.available_fields = {}
        self.dataset_type = "tweet"

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.SetMinSize(Constants.TWITTER_DIALOG_SIZE)
        
        main_frame = wx.GetApp().GetTopWindow()
        if main_frame.options_dict['multipledatasets_mode']:
            name_label = wx.StaticText(self, label=GUIText.NAME + ": ")
            name_info = GenericGUIs.InfoIcon(self, GUIText.NAME_TOOLTIP)
            self.name_ctrl = wx.TextCtrl(self)
            self.name_ctrl.SetToolTip(GUIText.NAME_TOOLTIP)
            name_sizer = wx.BoxSizer(wx.HORIZONTAL)
            name_sizer.Add(name_label)
            name_sizer.Add(name_info)
            name_sizer.Add(self.name_ctrl)
            sizer.Add(name_sizer, 0, wx.ALL, 5)

        # ethics/terms of use
        self.ethics_community1_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY1)
        self.ethics_community2_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY2)
        self.ethics_research_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_RESEARCH)
        self.ethics_institution_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_INSTITUTION)
        self.ethics_twitter_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_TWITTER)
        self.ethics_twitter_url = wx.adv.HyperlinkCtrl(self, label="1", url=GUIText.ETHICS_TWITTER_URL)
        ethics_sizer = wx.BoxSizer(wx.VERTICAL)
        ethics_sizer.Add(self.ethics_community1_ctrl)
        ethics_sizer.Add(self.ethics_community2_ctrl)
        ethics_sizer.Add(self.ethics_research_ctrl)
        ethics_sizer.Add(self.ethics_institution_ctrl)
        ethics_twitter_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ethics_twitter_sizer.Add(self.ethics_twitter_ctrl)
        ethics_twitter_sizer.Add(self.ethics_twitter_url)
        ethics_sizer.Add(ethics_twitter_sizer)
        sizer.Add(ethics_sizer, 0, wx.ALL, 5)

        consumer_key_label = wx.StaticText(self, label=GUIText.CONSUMER_KEY + ": ")
        consumer_key_info = GenericGUIs.InfoIcon(self, GUIText.CONSUMER_KEY_TOOLTIP)
        self.consumer_key_ctrl = wx.TextCtrl(self)
        if 'twitter_consumer_key' in main_frame.options_dict:
            self.consumer_key_ctrl.SetValue(main_frame.options_dict['twitter_consumer_key'])
        self.consumer_key_ctrl.SetToolTip(GUIText.CONSUMER_KEY_TOOLTIP)
        consumer_key_sizer = wx.BoxSizer(wx.HORIZONTAL)
        consumer_key_sizer.Add(consumer_key_label)
        consumer_key_sizer.Add(consumer_key_info)
        consumer_key_sizer.Add(self.consumer_key_ctrl, wx.EXPAND)
        sizer.Add(consumer_key_sizer, 0, wx.EXPAND | wx.ALL, 5)
    
        consumer_secret_label = wx.StaticText(self, label=GUIText.CONSUMER_SECRET + ": ")
        consumer_secret_info = GenericGUIs.InfoIcon(self, GUIText.CONSUMER_SECRET_TOOLTIP)
        self.consumer_secret_ctrl = wx.TextCtrl(self)
        if 'twitter_consumer_secret' in main_frame.options_dict:
            self.consumer_secret_ctrl.SetValue(main_frame.options_dict['twitter_consumer_secret'])
        self.consumer_secret_ctrl.SetToolTip(GUIText.CONSUMER_SECRET_TOOLTIP)
        consumer_secret_sizer = wx.BoxSizer(wx.HORIZONTAL)
        consumer_secret_sizer.Add(consumer_secret_label)
        consumer_secret_sizer.Add(consumer_secret_info)
        consumer_secret_sizer.Add(self.consumer_secret_ctrl, wx.EXPAND)
        sizer.Add(consumer_secret_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.search_by_map = []

        # search by query
        self.query_radioctrl = wx.RadioButton(self, label=GUIText.TWITTER_QUERY+": ", style=wx.RB_GROUP)
        self.query_radioctrl.SetToolTip(GUIText.TWITTER_QUERY_RADIOBUTTON_TOOLTIP)
        self.query_radioctrl.SetValue(True)
        query_info = GenericGUIs.InfoIcon(self, GUIText.TWITTER_QUERY_RADIOBUTTON_TOOLTIP)

        self.query_hyperlink_ctrl = wx.adv.HyperlinkCtrl(self, label="2", url=GUIText.TWITTER_QUERY_HYPERLINK)

        self.query_ctrl = wx.TextCtrl(self)
        self.query_ctrl.SetHint(GUIText.TWITTER_QUERY_PLACEHOLDER)
        self.query_ctrl.SetToolTip(GUIText.TWITTER_QUERY_TOOLTIP)

        query_items_sizer = wx.BoxSizer(wx.HORIZONTAL)
        query_items_sizer.Add(self.query_hyperlink_ctrl)
        query_items_sizer.AddSpacer(10)
        query_items_sizer.Add(self.query_ctrl, wx.EXPAND)

        query_sizer = wx.BoxSizer(wx.HORIZONTAL)
        query_sizer.Add(self.query_radioctrl)
        query_sizer.Add(query_info)
        query_sizer.Add(query_items_sizer, wx.EXPAND)

        # search by tweet attributes
        self.attributes_radioctrl = wx.RadioButton(self, label=GUIText.TWITTER_TWEET_ATTRIBUTES+": ")
        self.attributes_radioctrl.SetToolTip(GUIText.TWITTER_TWEET_ATTRIBUTES_RADIOBUTTON_TOOLTIP)
        attributes_info = GenericGUIs.InfoIcon(self, GUIText.TWITTER_TWEET_ATTRIBUTES_RADIOBUTTON_TOOLTIP)

        self.keywords_checkbox_ctrl = wx.CheckBox(self, label=GUIText.TWITTER_KEYWORDS+": ")
        self.keywords_ctrl = wx.TextCtrl(self)
        self.keywords_ctrl.SetHint(GUIText.TWITTER_KEYWORDS_PLACEHOLDER)
        keywords_sizer = wx.BoxSizer(wx.HORIZONTAL)
        keywords_sizer.AddSpacer(20)
        keywords_sizer.Add(self.keywords_checkbox_ctrl)
        keywords_sizer.Add(self.keywords_ctrl, wx.EXPAND)

        self.hashtags_checkbox_ctrl = wx.CheckBox(self, label=GUIText.TWITTER_HASHTAGS+": ")
        self.hashtags_ctrl = wx.TextCtrl(self)
        self.hashtags_ctrl.SetHint(GUIText.TWITTER_HASHTAGS_PLACEHOLDER)
        hashtags_sizer = wx.BoxSizer(wx.HORIZONTAL)
        hashtags_sizer.AddSpacer(20)
        hashtags_sizer.Add(self.hashtags_checkbox_ctrl)
        hashtags_sizer.Add(self.hashtags_ctrl, wx.EXPAND)

        self.account_checkbox_ctrl = wx.CheckBox(self, label=GUIText.TWITTER_LABEL+" "+GUIText.TWITTER_ACCOUNTS+": ")
        self.account_ctrl = wx.TextCtrl(self)
        self.account_ctrl.SetHint(GUIText.TWITTER_ACCOUNT_PLACEHOLDER)
        account_sizer = wx.BoxSizer(wx.HORIZONTAL)
        account_sizer.AddSpacer(20)
        account_sizer.Add(self.account_checkbox_ctrl)
        account_sizer.Add(self.account_ctrl, wx.EXPAND)

        attributes_options_sizer = wx.BoxSizer(wx.VERTICAL)
        attributes_options_sizer.Add(keywords_sizer, 0, wx.EXPAND)
        attributes_options_sizer.Add(hashtags_sizer, 0, wx.EXPAND)
        attributes_options_sizer.Add(account_sizer, 0, wx.EXPAND)
        
        attributes_sizer = wx.BoxSizer(wx.VERTICAL)
        attributes_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        attributes_sizer1.Add(self.attributes_radioctrl)
        attributes_sizer1.Add(attributes_info)
        attributes_sizer.Add(attributes_sizer1)
        attributes_sizer.Add(attributes_options_sizer, 0, wx.EXPAND)

        
        # add 'search by' elements to box
        search_box = wx.StaticBox(self, label=GUIText.REDDIT_SEARCH_BY)
        self.search_by_sizer = wx.StaticBoxSizer(search_box, wx.VERTICAL)
        self.search_by_sizer.Add(query_sizer, 0, wx.EXPAND)
        self.search_by_sizer.Add(attributes_sizer, 0, wx.EXPAND)

        # enable only the selected 'search by' option
        self.search_by_map.append([self.query_radioctrl, query_items_sizer])
        self.search_by_map.append([self.attributes_radioctrl, attributes_options_sizer])
        self.query_radioctrl.Bind(wx.EVT_RADIOBUTTON, self.EnableOnlySelected)
        self.attributes_radioctrl.Bind(wx.EVT_RADIOBUTTON, self.EnableOnlySelected)
        self.EnableOnlySelected(None)

        sizer.Add(self.search_by_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # retweets checkbox
        self.include_retweets_ctrl = wx.CheckBox(self, label=GUIText.INCLUDE_RETWEETS)
        sizer.Add(self.include_retweets_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        language_label = wx.StaticText(self, label=GUIText.LANGUAGE+":")
        self.language_ctrl = wx.Choice(self, choices=Constants.AVAILABLE_DATASET_LANGUAGES2)
        self.language_ctrl.Select(0)
        language_sizer = wx.BoxSizer(wx.HORIZONTAL)
        language_sizer.Add(language_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        language_sizer.Add(self.language_ctrl)
        sizer.Add(language_sizer, 0, wx.ALL, 5)

        # dates
        date_sizer = wx.BoxSizer(wx.HORIZONTAL)

        start_date_label = wx.StaticText(self, label=GUIText.START_DATE+" ("+GUIText.UTC+")"+": ")
        start_date_info = GenericGUIs.InfoIcon(self, GUIText.START_DATE_TOOLTIP)
        self.start_date_ctrl = wx.adv.DatePickerCtrl(self, name="startDate",
                                                style=wx.adv.DP_DROPDOWN|wx.adv.DP_SHOWCENTURY)
        self.start_date_ctrl.SetToolTip(GUIText.START_DATE_TOOLTIP)
        start_date_sizer = wx.BoxSizer(wx.HORIZONTAL)
        start_date_sizer.Add(start_date_label)
        start_date_sizer.Add(start_date_info)
        start_date_sizer.Add(self.start_date_ctrl)

        end_date_label = wx.StaticText(self, label=GUIText.END_DATE+" ("+GUIText.UTC+")"+": ")
        end_date_info = GenericGUIs.InfoIcon(self, GUIText.END_DATE_TOOLTIP)
        self.end_date_ctrl = wx.adv.DatePickerCtrl(self, name="endDate",
                                              style=wx.adv.DP_DROPDOWN|wx.adv.DP_SHOWCENTURY)
        self.end_date_ctrl.SetToolTip(GUIText.END_DATE_TOOLTIP)
        end_date_sizer = wx.BoxSizer(wx.HORIZONTAL)
        end_date_sizer.Add(end_date_label)
        end_date_sizer.Add(end_date_info)
        end_date_sizer.Add(self.end_date_ctrl)

        date_sizer.Add(start_date_sizer, 0, wx.EXPAND, 5)
        date_sizer.AddSpacer(10)
        date_sizer.Add(end_date_sizer, 0, wx.EXPAND, 5)
        sizer.Add(date_sizer, 0, wx.ALL, 5)

        # warning/notice
        notice = wx.StaticText(self, label=GUIText.RETRIEVAL_NOTICE_TWITTER)
        sizer.Add(notice, 0, wx.EXPAND | wx.ALL, 5)
        
        label_fields_label = wx.StaticText(self, label=GUIText.LABEL_FIELDS)
        label_fields_info = GenericGUIs.InfoIcon(self, GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.label_fields_ctrl.AppendColumn(GUIText.FIELD)
        self.label_fields_ctrl.AppendColumn(GUIText.DESCRIPTION)
        self.label_fields_ctrl.AppendColumn(GUIText.TYPE)
        self.label_fields_ctrl.SetToolTip(GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_ctrl.EnableCheckBoxes()
        label_fields_sizer = wx.BoxSizer(wx.HORIZONTAL)
        label_fields_sizer.Add(label_fields_label, 0, wx.ALL)
        label_fields_sizer.Add(label_fields_info, 0, wx.ALL)
        label_fields_sizer.Add(self.label_fields_ctrl, 1, wx.EXPAND)
        if main_frame.options_dict['adjustable_label_fields_mode']:
            sizer.Add(label_fields_sizer, 0, wx.ALL|wx.EXPAND, 5)
        else:
            label_fields_sizer.ShowItems(False)

        computational_fields_label = wx.StaticText(self, label=GUIText.COMPUTATIONAL_FIELDS)
        computational_fields_info = GenericGUIs.InfoIcon(self, GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computational_fields_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.computational_fields_ctrl.AppendColumn(GUIText.FIELD)
        self.computational_fields_ctrl.AppendColumn(GUIText.DESCRIPTION)
        self.computational_fields_ctrl.AppendColumn(GUIText.TYPE)
        self.computational_fields_ctrl.SetToolTip(GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computational_fields_ctrl.EnableCheckBoxes()
        computational_fields_sizer = wx.BoxSizer(wx.HORIZONTAL)
        computational_fields_sizer.Add(computational_fields_label, 0, wx.ALL)
        computational_fields_sizer.Add(computational_fields_info, 0, wx.ALL)
        computational_fields_sizer.Add(self.computational_fields_ctrl, 1, wx.EXPAND)
        if main_frame.options_dict['adjustable_computation_fields_mode']:
            sizer.Add(computational_fields_sizer, 0, wx.ALL|wx.EXPAND, 5)
        else:
            computational_fields_sizer.ShowItems(False)

        #TODO: defaults to tweet type for now, could add more (like with reddit) if needed
        self.OnDatasetTypeChosen(None)

        #Retriever button to collect the requested data
        controls_sizer = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        ok_button = wx.FindWindowById(wx.ID_OK, self)
        ok_button.SetLabel(GUIText.DATASETS_RETRIEVE_TWITTER)
        sizer.Add(controls_sizer, 0, wx.ALIGN_RIGHT|wx.ALL, 5)

        self.SetSizer(sizer)
        self.Layout()
        self.Fit()

        ok_button.Bind(wx.EVT_BUTTON, self.OnRetrieveStart)
        CustomEvents.RETRIEVE_EVT_RESULT(self, self.OnRetrieveEnd)

        logger.info("Finished")

    def OnDatasetTypeChosen(self, event):
        logger = logging.getLogger(__name__+".TwitterRetrieverDialog.OnDatasetTypeChosen")
        logger.info("Starting")
        dataset_type = self.dataset_type

        self.available_fields = Constants.available_fields[('Twitter', dataset_type,)]

        self.label_fields_ctrl.DeleteAllItems()
        self.computational_fields_ctrl.DeleteAllItems()
        idx = 0
        for key in self.available_fields:
            self.label_fields_ctrl.Append([key, self.available_fields[key]['desc'], self.available_fields[key]['type']])
            if self.available_fields[key]['label_fields_default']:
                self.label_fields_ctrl.CheckItem(idx)
            self.computational_fields_ctrl.Append([key, self.available_fields[key]['desc'], self.available_fields[key]['type']])
            if self.available_fields[key]['computation_fields_default']:
                self.computational_fields_ctrl.CheckItem(idx)
            idx = idx+1

        self.Layout()
        self.Fit()
        logger.info("Finished")

    def OnRetrieveStart(self, event):
        logger = logging.getLogger(__name__+".TwitterRetrieverDialog.OnRetrieveStart")
        logger.info("Starting")

        status_flag = True
        main_frame = wx.GetApp().GetTopWindow()
        keys = {}

        if main_frame.options_dict['multipledatasets_mode']:
            name = self.name_ctrl.GetValue()
            if name == "":
                wx.MessageBox(GUIText.NAME_MISSING_ERROR,
                            GUIText.ERROR, wx.OK | wx.ICON_ERROR)
                logger.warning('No name entered')
                status_flag = False

        if not self.ethics_community1_ctrl.IsChecked():
            wx.MessageBox(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY1,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('Ethics not checked')
            status_flag = False
        if not self.ethics_community2_ctrl.IsChecked():
            wx.MessageBox(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY2,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('Ethics not checked')
            status_flag = False
        if not self.ethics_research_ctrl.IsChecked():
            wx.MessageBox(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_RESEARCH,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('Ethics not checked')
            status_flag = False
        if not self.ethics_institution_ctrl.IsChecked():
            wx.MessageBox(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_INSTITUTION,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('Ethics not checked')
            status_flag = False
        if not self.ethics_twitter_ctrl.IsChecked():
            wx.MessageBox(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_TWITTER,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('Ethics not checked')
            status_flag = False
        
        keys['consumer_key'] = self.consumer_key_ctrl.GetValue()
        if keys['consumer_key'] == "":
            wx.MessageBox(GUIText.CONSUMER_KEY_MISSING_ERROR,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('No consumer key entered')
            status_flag = False
        keys['consumer_secret'] = self.consumer_secret_ctrl.GetValue()
        if keys['consumer_secret'] == "":
            wx.MessageBox(GUIText.CONSUMER_SECRET_MISSING_ERROR,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('No consumer secret entered')
            status_flag = False

        language = Constants.AVAILABLE_DATASET_LANGUAGES1[self.language_ctrl.GetSelection()]

        auth = tweepy.OAuthHandler(keys['consumer_key'], keys['consumer_secret'])
        api = tweepy.API(auth)
        #valid_credentials = False
        #try:
        #    valid_credentials = api.verify_credentials() # throws an error if user credentials are insufficient
        #    if not valid_credentials:
        #        wx.MessageBox(GUIText.INVALID_CREDENTIALS_ERROR,
        #                    GUIText.ERROR, wx.OK | wx.ICON_ERROR)
        #        logger.warning('Invalid credentials')
        #        status_flag = False 
        #except tweepy.errors.TweepyException as e:
        #    if 403 in e.api_codes:
                #TODO: once user auth is implemented, verify user credentials are sufficient (input for valid user credentials still need to be added)
        #        pass
                # wx.MessageBox(GUIText.INSUFFICIENT_CREDENTIALS_ERROR,
                #             GUIText.ERROR, wx.OK | wx.ICON_ERROR)
                # logger.warning('User credentials do not allow access to this resource.')
                # status_flag = False         

        selected_option = None
        for option in self.search_by_map:
            if option[0].GetValue():
                selected_option = option
                break
        
        # generate query
        query = ""
        if selected_option[0].GetLabel() == GUIText.TWITTER_QUERY+": ":
            query = self.query_ctrl.GetValue().strip()
        elif selected_option[0].GetLabel() == GUIText.TWITTER_TWEET_ATTRIBUTES+": ":
            query_items = [] # individual sub-queries, which are joined by UNION (OR) to form the overall query
            attributes_list_sizer = selected_option[1]
            for attribute_sizer in attributes_list_sizer.GetChildren():
                sizer = attribute_sizer.GetSizer()
                checkbox = sizer.GetChildren()[1].GetWindow()
                text_field = sizer.GetChildren()[2].GetWindow()
                if checkbox.GetValue() and text_field.GetValue() != "":
                    text = text_field.GetValue()
                    if checkbox.GetLabel() == GUIText.TWITTER_KEYWORDS+": ":
                        keywords = text.split(",")
                        for phrase in keywords:
                            phrase = phrase.strip()
                            if " " in phrase: # multi-word keyword
                                phrase = "\""+phrase+"\""
                            query_items.append(phrase)
                    elif checkbox.GetLabel() == GUIText.TWITTER_HASHTAGS+": ":
                        text = text.replace(",", " ")
                        hashtags = text.split()
                        for hashtag in hashtags:
                            hashtag = hashtag.strip()
                            if hashtag[0] != "#": # hashtags must start with '#' symbol
                                hashtag = "#"+hashtag
                            query_items.append(hashtag)
                    elif checkbox.GetLabel() == GUIText.TWITTER_LABEL+" "+GUIText.TWITTER_ACCOUNTS+": ":
                        text = text.replace(",", " ")
                        accounts = text.split()
                        for account in accounts:
                            account = account.strip()
                            if not account.startswith("from:"):
                                account = "from:"+account
                            query_items.append(account)
            for i in range(len(query_items)):
                query += query_items[i]
                if i < len(query_items)-1:
                    query += " OR "
        
        if query == "":
            wx.MessageBox(GUIText.TWITTER_QUERY_MISSING_ERROR,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning('No query entered')
            status_flag = False
        else:
            # retweets flag
            if not self.include_retweets_ctrl.GetValue():
                query += " -filter:retweets "
        query = query.strip() # trim whitespace
        logger.info("Query: "+query)

        if not main_frame.options_dict['multipledatasets_mode']:
            #TODO temporary fix for special character issue
            name = re.sub('[^A-Za-z0-9]+', '', query)

        start_date = str(self.start_date_ctrl.GetValue().Format("%Y-%m-%d"))
        end_date = str(self.end_date_ctrl.GetValue().Format("%Y-%m-%d"))
        if start_date > end_date:
            wx.MessageBox(GUIText.DATE_ERROR,
                          GUIText.ERROR, wx.OK | wx.ICON_ERROR)
            logger.warning("Start Date[%s] not before End Date[%s]",
                           str(start_date), str(end_date))
            status_flag = False

        dataset_source = "Twitter"
        
        dataset_key = (query, dataset_source, self.dataset_type)
        if dataset_key in main_frame.datasets:
            wx.MessageBox(GUIText.NAME_EXISTS_ERROR,
                          GUIText.ERROR,
                          wx.OK | wx.ICON_ERROR)
            logger.warning("Data with same name[%s] already exists", query)
            status_flag = False

        label_fields_list = []
        item = self.label_fields_ctrl.GetNextItem(-1)
        while item != -1:
            if self.label_fields_ctrl.IsItemChecked(item):
                field_name = self.label_fields_ctrl.GetItemText(item, 0)
                label_fields_list.append((field_name, self.available_fields[field_name],))
            item = self.label_fields_ctrl.GetNextItem(item)
        
        computational_fields_list = []
        item = self.computational_fields_ctrl.GetNextItem(-1)
        while item != -1:
            if self.computational_fields_ctrl.IsItemChecked(item):
                field_name = self.computational_fields_ctrl.GetItemText(item, 0)
                computational_fields_list.append((field_name, self.available_fields[field_name],))
            item = self.computational_fields_ctrl.GetNextItem(item)

        if status_flag:
            main_frame.CreateProgressDialog(title=GUIText.RETRIEVING_LABEL+name,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
            self.Hide()
            self.Disable()
            self.Freeze()
            main_frame.PulseProgressDialog(GUIText.RETRIEVING_BEGINNING_MSG)
            self.retrieval_thread = CollectionThreads.RetrieveTwitterDatasetThread(self, main_frame, name, language, keys, query, start_date, end_date, self.dataset_type,
                                                                                    list(self.available_fields.items()), label_fields_list, computational_fields_list)
        logger.info("Finished")

    # given a sizer, disables all child elements
    def DisableSizer(self, parent_sizer):
        for child_sizer in parent_sizer.GetChildren():
            elem = child_sizer.GetWindow()
            if not elem:
                try:
                    # elem is a sizer
                    sizer = child_sizer.GetSizer()
                    if sizer != None:
                        self.DisableSizer(sizer)
                except:
                    # elem is something else, not a widget
                    pass
            else:
                # elem is a widget
                # disable all widgets
                if isinstance(elem, wx.adv.HyperlinkCtrl):
                    elem.SetNormalColour(wx.Colour(127, 127, 127))
                elem.Disable()

    # given a sizer, enables all child elements
    def EnableSizer(self, parent_sizer):
        for child_sizer in parent_sizer.GetChildren():
            elem = child_sizer.GetWindow()
            if not elem:
                try:
                    # elem is a sizer
                    sizer = child_sizer.GetSizer()
                    if sizer != None:
                        self.EnableSizer(sizer)
                except:
                    # elem is something else, not a widget
                    pass
            else:
                # elem is a widget
                # enable all widgets
                if isinstance(elem, wx.adv.HyperlinkCtrl):
                    elem.SetNormalColour(wx.Colour(wx.BLUE))
                elem.Enable()

    # given a sizer containing a list of option sizers
    # enables option corresponding to selected radiobutton,
    # and disables the rest of the options            
    def EnableOnlySelected(self, event):
        for option in self.search_by_map:
            if option[0].GetValue():
                self.EnableSizer(option[1])
            else:
                self.DisableSizer(option[1])

class CSVDatasetRetrieverDialog(AbstractRetrieverDialog):
    def __init__(self, parent):
        logger = logging.getLogger(__name__+".CSVRetrieverDialog.__init__")
        logger.info("Starting")
        wx.Dialog.__init__(self, parent, title=GUIText.CSV_RETRIEVE_LABEL, style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.retrieval_thread = None
        self.available_fields = {}

        main_frame = wx.GetApp().GetTopWindow()

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.error_label = wx.StaticText(self, label="")
        self.error_label.SetForegroundColour(wx.Colour(255, 0, 0))
        sizer.Add(self.error_label, 0, wx.ALL, 5)
        self.error_label.Hide()

        if main_frame.options_dict['multipledatasets_mode']:
            name_label = wx.StaticText(self, label=GUIText.NAME + " ")
            name_info = GenericGUIs.InfoIcon(self, GUIText.NAME_TOOLTIP)
            self.name_ctrl = wx.TextCtrl(self)
            self.name_ctrl.SetToolTip(GUIText.NAME_TOOLTIP)
            self.name_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.name_sizer.Add(name_label, 0, wx.ALIGN_CENTRE_VERTICAL)
            self.name_sizer.Add(name_info, 0, wx.ALIGN_CENTRE_VERTICAL)
            self.name_sizer.Add(self.name_ctrl)
            sizer.Add(self.name_sizer, 0, wx.ALL, 5)
        
        
        datasetconfig_box = wx.StaticBox(self, label=GUIText.DATASET_CONFIGURATIONS)
        datasetconfig_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        datasetconfig_sizer = wx.StaticBoxSizer(datasetconfig_box, wx.VERTICAL)
        sizer.Add(datasetconfig_sizer, 0, wx.EXPAND|wx.ALL, 5)

        filename_label = wx.StaticText(self, label=GUIText.FILENAME + " ")
        self.filename_ctrl = wx.FilePickerCtrl(self, wildcard="CSV files (*.csv)|*.csv")
        path = os.path.join(Constants.DATA_PATH + "CSV")
        self.filename_ctrl.SetInitialDirectory(path)
        self.filename_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.filename_sizer.Add(filename_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        self.filename_sizer.Add(self.filename_ctrl, 1, wx.EXPAND)
        self.filename_ctrl.Bind(wx.EVT_FILEPICKER_CHANGED, self.OnFilenameChosen)
        datasetconfig_sizer.Add(self.filename_sizer, 0, wx.ALL|wx.EXPAND, 5)

        id_field_label = wx.StaticText(self, label=GUIText.CSV_IDFIELD+" ")
        id_field_info = GenericGUIs.InfoIcon(self, GUIText.CSV_IDFIELD_TOOLTIP)
        self.id_field_ctrl = wx.Choice(self, choices=[GUIText.CSV_IDFIELD_DEFAULT])
        self.id_field_ctrl.SetToolTip(GUIText.CSV_IDFIELD_TOOLTIP)
        self.id_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.id_field_sizer.Add(id_field_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        self.id_field_sizer.Add(id_field_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        self.id_field_sizer.Add(self.id_field_ctrl)
        datasetconfig_sizer.Add(self.id_field_sizer, 0, wx.ALL, 5)

        language_label = wx.StaticText(self, label=GUIText.LANGUAGE+" ")
        self.language_ctrl = wx.Choice(self, choices=Constants.AVAILABLE_DATASET_LANGUAGES2)
        self.language_ctrl.Select(0)
        self.language_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.language_sizer.Add(language_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        self.language_sizer.Add(self.language_ctrl)
        datasetconfig_sizer.Add(self.language_sizer, 0, wx.ALL, 5)

        datafields_box = wx.StaticBox(self, label=GUIText.SPECIAL_DATA_FIELDS)
        datafields_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        datafields_sizer = wx.StaticBoxSizer(datafields_box, wx.VERTICAL)
        sizer.Add(datafields_sizer, 0, wx.EXPAND|wx.ALL, 5)

        if main_frame.options_dict['multipledatasets_mode']:
            dataset_field_label = wx.StaticText(self, label=GUIText.CSV_DATASETFIELD+"(Optional) ")
            dataset_field_info = GenericGUIs.InfoIcon(self, GUIText.CSV_DATASETFIELD_TOOLTIP)
            self.dataset_field_ctrl = wx.Choice(self, choices=[])
            self.dataset_field_ctrl.SetToolTip(GUIText.CSV_DATASETFIELD_TOOLTIP)
            dataset_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
            dataset_field_sizer.Add(dataset_field_label, 0, wx.ALIGN_CENTRE_VERTICAL)
            dataset_field_sizer.Add(dataset_field_info, 0, wx.ALIGN_CENTRE_VERTICAL)
            dataset_field_sizer.Add(self.dataset_field_ctrl)
            datafields_sizer.Add(dataset_field_sizer, 0, wx.ALL, 5)
        
        url_field_label = wx.StaticText(self, label=GUIText.CSV_URLFIELD+"(Optional) ")
        url_field_info = GenericGUIs.InfoIcon(self, GUIText.CSV_URLFIELD_TOOLTIP)
        self.url_field_ctrl = wx.Choice(self, choices=[""])
        self.url_field_ctrl.SetToolTip(GUIText.CSV_URLFIELD_TOOLTIP)
        url_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
        url_field_sizer.Add(url_field_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        url_field_sizer.Add(url_field_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        url_field_sizer.Add(self.url_field_ctrl)
        datafields_sizer.Add(url_field_sizer, 0, wx.ALL, 5)

        datetime_field_label = wx.StaticText(self, label=GUIText.CSV_DATETIMEFIELD+"(Optional) ")
        datetime_field_info = GenericGUIs.InfoIcon(self, GUIText.CSV_DATETIMEFIELD_TOOLTIP)
        self.datetime_field_ctrl = wx.Choice(self, choices=[""])
        self.datetime_field_ctrl.SetToolTip(GUIText.CSV_DATETIMEFIELD_TOOLTIP)
        self.datetime_tz_ctrl = wx.Choice(self, choices=pytz.all_timezones)
        datetime_field_sizer = wx.BoxSizer(wx.HORIZONTAL)
        datetime_field_sizer.Add(datetime_field_label, 0, wx.ALIGN_CENTRE_VERTICAL)
        datetime_field_sizer.Add(datetime_field_info, 0, wx.ALIGN_CENTRE_VERTICAL)
        datetime_field_sizer.Add(self.datetime_field_ctrl)
        datetime_field_sizer.Add(self.datetime_tz_ctrl)
        datafields_sizer.Add(datetime_field_sizer, 0, wx.ALL, 5)

        label_fields_first_label = wx.StaticText(self, label=GUIText.LABEL_FIELDS)
        label_fields_first_info = GenericGUIs.InfoIcon(self, GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_first_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT|wx.LC_NO_HEADER)
        self.label_fields_first_ctrl.AppendColumn(GUIText.FIELD)
        self.label_fields_first_ctrl.SetToolTip(GUIText.LABEL_FIELDS_TOOLTIP)
        self.label_fields_first_ctrl.EnableCheckBoxes()
        label_fields_first_sizer = wx.BoxSizer(wx.VERTICAL)
        label_fields_first_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        label_fields_first_sizer1.Add(label_fields_first_label)
        label_fields_first_sizer1.Add(label_fields_first_info)
        label_fields_first_sizer.Add(label_fields_first_sizer1)
        label_fields_first_sizer.Add(self.label_fields_first_ctrl, 1, wx.EXPAND)
        label_fields_combined_label = wx.StaticText(self, label=GUIText.COMBINED_LABEL_FIELDS)
        label_fields_combined_info = GenericGUIs.InfoIcon(self, GUIText.COMBINED_LABEL_FIELDS_TOOLTIP)
        self.label_fields_combined_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT|wx.LC_NO_HEADER)
        self.label_fields_combined_ctrl.AppendColumn(GUIText.FIELD)
        self.label_fields_combined_ctrl.SetToolTip(GUIText.COMBINED_LABEL_FIELDS_TOOLTIP)
        self.label_fields_combined_ctrl.EnableCheckBoxes()
        label_fields_combined_sizer = wx.BoxSizer(wx.VERTICAL)
        label_fields_combined_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        label_fields_combined_sizer1.Add(label_fields_combined_label)
        label_fields_combined_sizer1.Add(label_fields_combined_info)
        label_fields_combined_sizer.Add(label_fields_combined_sizer1)
        label_fields_combined_sizer.Add(self.label_fields_combined_ctrl, 1, wx.EXPAND)
        label_fields_sizer = wx.BoxSizer(wx.HORIZONTAL)
        label_fields_sizer.Add(label_fields_first_sizer, 1, wx.EXPAND)
        label_fields_sizer.Add(label_fields_combined_sizer, 1, wx.EXPAND)
        sizer.Add(label_fields_sizer, 1, wx.EXPAND|wx.ALL, 5)

        computation_fields_first_label = wx.StaticText(self, label=GUIText.COMPUTATIONAL_FIELDS)
        computation_fields_first_info = GenericGUIs.InfoIcon(self, GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computation_fields_first_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT|wx.LC_NO_HEADER)
        self.computation_fields_first_ctrl.AppendColumn(GUIText.FIELD)
        self.computation_fields_first_ctrl.SetToolTip(GUIText.COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computation_fields_first_ctrl.EnableCheckBoxes()
        computation_fields_first_sizer = wx.BoxSizer(wx.VERTICAL)
        computation_fields_first_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        computation_fields_first_sizer1.Add(computation_fields_first_label)
        computation_fields_first_sizer1.Add(computation_fields_first_info)
        computation_fields_first_sizer.Add(computation_fields_first_sizer1)
        computation_fields_first_sizer.Add(self.computation_fields_first_ctrl, 1, wx.EXPAND)
        computation_fields_combined_label = wx.StaticText(self, label=GUIText.COMBINED_COMPUTATIONAL_FIELDS)
        computation_fields_combined_info = GenericGUIs.InfoIcon(self, GUIText.COMBINED_COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computation_fields_combined_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT|wx.LC_NO_HEADER)
        self.computation_fields_combined_ctrl.AppendColumn(GUIText.FIELD)
        self.computation_fields_combined_ctrl.SetToolTip(GUIText.COMBINED_COMPUTATIONAL_FIELDS_TOOLTIP)
        self.computation_fields_combined_ctrl.EnableCheckBoxes()
        computation_fields_combined_sizer = wx.BoxSizer(wx.VERTICAL)
        computation_fields_combined_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        computation_fields_combined_sizer1.Add(computation_fields_combined_label)
        computation_fields_combined_sizer1.Add(computation_fields_combined_info)
        computation_fields_combined_sizer.Add(computation_fields_combined_sizer1)
        computation_fields_combined_sizer.Add(self.computation_fields_combined_ctrl, 1, wx.EXPAND)
        computation_fields_sizer = wx.BoxSizer(wx.HORIZONTAL)
        computation_fields_sizer.Add(computation_fields_first_sizer, 1, wx.EXPAND)
        computation_fields_sizer.Add(computation_fields_combined_sizer, 1, wx.EXPAND)
        sizer.Add(computation_fields_sizer, 1, wx.EXPAND|wx.ALL, 5)
        
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.OnDragInit, self.computation_fields_first_ctrl)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.OnDragInit, self.computation_fields_combined_ctrl)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.OnDragInit, self.label_fields_first_ctrl)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.OnDragInit, self.label_fields_combined_ctrl)
        label_fields_first_dt = FieldDropTarget(self.computation_fields_first_ctrl, self.label_fields_first_ctrl, self.computation_fields_combined_ctrl, self.label_fields_combined_ctrl)
        self.label_fields_first_ctrl.SetDropTarget(label_fields_first_dt)
        label_fields_combined_dt = FieldDropTarget(self.computation_fields_combined_ctrl, self.label_fields_combined_ctrl, self.computation_fields_first_ctrl, self.label_fields_first_ctrl)
        self.label_fields_combined_ctrl.SetDropTarget(label_fields_combined_dt)
        computation_fields_first_dt = FieldDropTarget(self.computation_fields_first_ctrl, self.label_fields_first_ctrl, self.computation_fields_combined_ctrl, self.label_fields_combined_ctrl)
        self.computation_fields_first_ctrl.SetDropTarget(computation_fields_first_dt)
        computation_fields_combined_dt = FieldDropTarget(self.computation_fields_combined_ctrl, self.label_fields_combined_ctrl, self.computation_fields_first_ctrl, self.label_fields_first_ctrl)
        self.computation_fields_combined_ctrl.SetDropTarget(computation_fields_combined_dt)

        # ethics/terms of use
        ethics_box = wx.StaticBox(self, label=GUIText.ETHICAL_CONSIDERATIONS)
        ethics_box.SetFont(main_frame.DETAILS_LABEL_FONT)
        ethics_sizer = wx.StaticBoxSizer(ethics_box, wx.VERTICAL)
        self.ethics_community1_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY1)
        ethics_sizer.Add(self.ethics_community1_ctrl, 0, wx.ALL, 5)
        self.ethics_community2_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_COMMUNITY2)
        ethics_sizer.Add(self.ethics_community2_ctrl, 0, wx.ALL, 5)
        self.ethics_research_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_RESEARCH)
        ethics_sizer.Add(self.ethics_research_ctrl, 0, wx.ALL, 5)
        self.ethics_institution_ctrl = wx.CheckBox(self, label=GUIText.ETHICS_CONFIRMATION+GUIText.ETHICS_INSTITUTION)
        ethics_sizer.Add(self.ethics_institution_ctrl, 0, wx.ALL, 5)
        sizer.Add(ethics_sizer, 0, wx.ALL|wx.EXPAND, 5)

        #Retriever button to collect the requested data
        controls_sizer = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        ok_button = wx.FindWindowById(wx.ID_OK, self)
        ok_button.SetLabel(GUIText.DATASETS_IMPORT_CSV)
        sizer.Add(controls_sizer, 0, wx.ALIGN_RIGHT|wx.ALL, 5)

        self.SetSizer(sizer)
        self.Layout()
        self.Fit()

        ok_button.Bind(wx.EVT_BUTTON, self.OnRetrieveStart)
        CustomEvents.RETRIEVE_EVT_RESULT(self, self.OnRetrieveEnd)

        logger.info("Finished")
    
    def OnFilenameChosen(self, event):
        logger = logging.getLogger(__name__+".CSVRetrieverDialog.OnFilenameChosen")
        logger.info("Starting")
        filename = self.filename_ctrl.GetPath()

        if os.path.isfile(filename):
            with open(filename, 'rb') as infile:
                encoding_result = chardet.detect(infile.read(100000))
            with open(filename, mode='r', encoding='utf-8') as infile:
                reader = csv.reader(infile)
                header_row = next(reader)
                self.id_field_ctrl.Clear()
                self.id_field_ctrl.Append(GUIText.CSV_IDFIELD_DEFAULT)
                self.url_field_ctrl.Clear()
                self.url_field_ctrl.Append("")
                self.datetime_field_ctrl.Clear()
                self.datetime_field_ctrl.Append("")
                self.label_fields_first_ctrl.DeleteAllItems()
                self.label_fields_combined_ctrl.DeleteAllItems()
                self.computation_fields_first_ctrl.DeleteAllItems()
                self.computation_fields_combined_ctrl.DeleteAllItems()
                self.available_fields.clear()
                main_frame = wx.GetApp().GetTopWindow()
                if main_frame.options_dict['multipledatasets_mode']:
                    self.dataset_field_ctrl.Clear()
                    self.dataset_field_ctrl.Append("")
                idx = 0
                for field_name in Constants.available_fields[('CSV', 'documents',)]:
                    self.available_fields[field_name] = Constants.available_fields[('CSV', 'documents',)][field_name]
                    self.label_fields_first_ctrl.Append([field_name])
                    if self.available_fields[field_name]['label_fields_default']:
                        self.label_fields_first_ctrl.CheckItem(idx)
                    idx = idx+1
                for column_name in header_row:
                    if main_frame.options_dict['multipledatasets_mode']:
                        self.dataset_field_ctrl.Append(column_name)
                    self.id_field_ctrl.Append(column_name)
                    self.url_field_ctrl.Append(column_name)
                    self.datetime_field_ctrl.Append(column_name)
                    self.label_fields_first_ctrl.Append(["csv."+column_name])
                    self.computation_fields_first_ctrl.Append(["csv."+column_name])
                    self.available_fields["csv."+column_name] = {"desc":"CSV Field", "type":"string"}
                self.label_fields_first_ctrl.SetColumnWidth(0, wx.LIST_AUTOSIZE)
                self.computation_fields_first_ctrl.SetColumnWidth(0, wx.LIST_AUTOSIZE)
                self.Layout()
                self.Fit()
        logger.info("Finished")

    def OnDragInit(self, event):
        text = event.GetEventObject().GetItemText(event.GetIndex())
        tobj = wx.TextDataObject(text)
        src = wx.DropSource(event.GetEventObject())
        src.SetData(tobj)
        src.DoDragDrop(True)

    def OnRetrieveStart(self, event):
        logger = logging.getLogger(__name__+".CSVRetrieverDialog.OnRetrieveStart")
        logger.info("Starting")

        error_messages = []
        main_frame = wx.GetApp().GetTopWindow()
        
        if main_frame.options_dict['multipledatasets_mode']:
            name = self.name_ctrl.GetValue()
            if name == "":
                error_messages.append(GUIText.NAME_MISSING_ERROR)
                logger.warning('No name entered')
        else:
            name = self.filename_ctrl.GetPath().split('\\')[-1]

        filename = self.filename_ctrl.GetPath()
        if filename == "":
            error_messages.append(GUIText.FILENAME_MISSING_ERROR)
            logger.warning('No filename entered')
        
        id_field = self.id_field_ctrl.GetStringSelection()
        if id_field == "":
            error_messages.append(GUIText.CSV_IDFIELD_MISSING_ERROR)
            logger.warning('No id field chosen')

        language = Constants.AVAILABLE_DATASET_LANGUAGES1[self.language_ctrl.GetSelection()]

        datetime_field = self.datetime_field_ctrl.GetStringSelection()
        datetime_tz = self.datetime_tz_ctrl.GetStringSelection()
        if datetime_field != '':
            if datetime_tz not in pytz.all_timezones:
                error_messages.append(GUIText.CSV_DATETIMETZ_MISSING_ERROR)
                logger.warning('No datetime tz chosen')
            if not main_frame.options_dict['adjustable_label_fields_mode']:
                idx = self.label_fields_first_ctrl.FindItem(-1, "created_utc")
                self.label_fields_first_ctrl.CheckItem(idx, True)

        url_field = self.url_field_ctrl.GetStringSelection()
        if url_field != "" and not main_frame.options_dict['adjustable_label_fields_mode']:
            idx = self.label_fields_first_ctrl.FindItem(-1, "id")
            self.label_fields_first_ctrl.CheckItem(idx, False)
            idx = self.label_fields_first_ctrl.FindItem(-1, "url")
            self.label_fields_first_ctrl.CheckItem(idx, True)

        label_fields_list = []
        computation_fields_list = []
        combined_list = []
        item_idx = -1
        while 1:
            item_idx = self.label_fields_first_ctrl.GetNextItem(item_idx)
            if item_idx == -1:
                break
            else:
                if self.label_fields_first_ctrl.IsItemChecked(item_idx):
                    field_name = self.label_fields_first_ctrl.GetItemText(item_idx)
                    label_fields_list.append((field_name, self.available_fields[field_name],))
        
        item_idx = -1
        while 1:
            item_idx = self.label_fields_combined_ctrl.GetNextItem(item_idx)
            if item_idx == -1:
                break
            else:
                field_name = self.label_fields_combined_ctrl.GetItemText(item_idx)    
                if (field_name, self.available_fields[field_name],) not in combined_list:
                    combined_list.append(field_name)
                if self.label_fields_combined_ctrl.IsItemChecked(item_idx):
                    label_fields_list.append((field_name, self.available_fields[field_name],))
        
        item_idx = -1
        while 1:
            item_idx = self.computation_fields_first_ctrl.GetNextItem(item_idx)
            if item_idx == -1:
                break
            else:
                if self.computation_fields_first_ctrl.IsItemChecked(item_idx):
                    field_name = self.computation_fields_first_ctrl.GetItemText(item_idx)
                    computation_fields_list.append((field_name, self.available_fields[field_name],))
                    if not main_frame.options_dict['adjustable_label_fields_mode']:
                        if (field_name, self.available_fields[field_name],) not in label_fields_list:
                            computation_fields_list.append((field_name, self.available_fields[field_name],))
        
        item_idx = -1
        while 1:
            item_idx = self.computation_fields_combined_ctrl.GetNextItem(item_idx)
            if item_idx == -1:
                break
            else:
                field_name = self.computation_fields_combined_ctrl.GetItemText(item_idx)
                if (field_name, self.available_fields[field_name],) not in combined_list:
                    combined_list.append(field_name)
                if self.computation_fields_combined_ctrl.IsItemChecked(item_idx):
                    computation_fields_list.append((field_name, self.available_fields[field_name],))
                    if not main_frame.options_dict['adjustable_label_fields_mode']:
                        if (field_name, self.available_fields[field_name],) not in label_fields_list:
                            label_fields_list.append((field_name, self.available_fields[field_name],))

        if main_frame.options_dict['multipledatasets_mode']:
            dataset_field = self.dataset_field_ctrl.GetStringSelection()
        else:
            dataset_field = ""
        dataset_type = ""
        if dataset_field == "":
            dataset_type = "document"
        
        if not self.ethics_community1_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY1)
            logger.warning('Ethics not checked')
        if not self.ethics_community2_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_COMMUNITY2)
            logger.warning('Ethics not checked')
        if not self.ethics_research_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_RESEARCH)
            logger.warning('Ethics not checked')
        if not self.ethics_institution_ctrl.IsChecked():
            error_messages.append(GUIText.ETHICS_CONFIRMATION_MISSING_ERROR+GUIText.ETHICS_INSTITUTION)
            logger.warning('Ethics not checked')

        if len(error_messages) == 0:
            main_frame.CreateProgressDialog(title=GUIText.RETRIEVING_LABEL+name,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
            self.error_label.Hide()
            self.Layout()
            self.Fit()
            self.Hide()
            self.Disable()
            self.Freeze()
            main_frame.PulseProgressDialog(GUIText.RETRIEVING_BEGINNING_MSG)
            self.retrieval_thread = CollectionThreads.RetrieveCSVDatasetThread(self, main_frame, name, language, dataset_field, dataset_type,
                                                                               id_field, url_field, datetime_field, datetime_tz,
                                                                               list(self.available_fields.items()), label_fields_list, computation_fields_list, combined_list, filename)
        else:
            error_text = "-" + "\n-".join(error_messages)
            self.error_label.SetLabel(error_text)
            self.error_label.Show()
            self.Layout()
            self.Fit()
        logger.info("Finished")
    
class FieldDropTarget(wx.TextDropTarget):
    def __init__(self, dest1, dest2, source1, source2):
        wx.TextDropTarget.__init__(self)
        self.dest1 = dest1
        self.dest2 = dest2
        self.source1 = source1
        self.source2 = source2
    def OnDropText(self, x, y, data):
        idx = self.source1.FindItem(-1, data)
        if idx is not wx.NOT_FOUND:
            self.source1.DeleteItem(idx)
        idx = self.source2.FindItem(-1, data)
        if idx is not wx.NOT_FOUND:
            self.source2.DeleteItem(idx)
        if self.dest1.FindItem(-1, data) is wx.NOT_FOUND:
            self.dest1.InsertItem(0, data)
            self.dest1.SetColumnWidth(0, wx.LIST_AUTOSIZE)
        if self.dest2.FindItem(-1, data) is wx.NOT_FOUND:
            self.dest2.InsertItem(0, data)
            self.dest2.SetColumnWidth(0, wx.LIST_AUTOSIZE)
        return True