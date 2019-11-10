#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 27 09:20:01 2018

@authors: dan.wendling@nih.gov

Last modified: 2019-11-11

------------------------------------------
 ** Semantic Search Analysis: Start-up **
------------------------------------------

This script: Import search queries from Google Analytics, clean up, 
match query entries against historical files. This is the only script of the 
set that can be run without human intervention. If desired.

INPUTS:
- data/raw/SearchConsoleNew.csv - log of google.com search results where person landed on your site
- data/raw/SiteSearchNew.csv - log from your site search
- data/matchFiles/SiteSpecificMatches.xslx - From custom clustering of terms that won't be in UMLS
- data/matchFiles/PastMatches.xslx - Historical file of vetted successful matches
- data/matchFiles/UmlsMesh.xslx - Free-to-use controlled vocabulary - MeSH - with UMLS Semantic Types

OUTPUTS:
- data/interim/01_CombinedSearchFullLog.xlsx - Lightly modified full log before changes
- data/interim/ForeignUnresolved.xslx - Currently, queries with non-English characters are removed
- data/interim/LogAfterPhase1.xslx - Full log after local processing
- data/interim/UnmatchedAfterPhase1.xslx - Queries that have not been matched, used in Phase 2


-------------------------------
HOW TO EXPORT YOUR SOURCE DATA
-------------------------------

Script assumes Google Analytics where search logging has been configured. Can
be adapted for other tools. This method avoids personally identifiable information.

    1. Go to Acquisition > Search Console > Queries
    2. Set date parameters (Consider 1 month)
    3. Select Export > Unsampled Report as SearchConsoleNew.csv
    4. Copy the result to data/raw folder
    5. Do the same from Behavior > Site Search > Search Terms with file name
        SiteSearchNew.csv
        
(You could also use the separate Google Search Console interface, but this
requires more configuration than is covered here.)


----------------
SCRIPT CONTENTS
----------------

1. Start-up / What to put into place, where
2. Create dataframe from query log; globally update columns and rows
3. Assign terms with non-English characters to ForeignUnresolved
4. Make special-case assignments with F&R, RegEx: Bibliographic, Numeric, Named entities
5. Exact-match to site-specific and vetted past matches
6. Eyeball results; manually classify remaining "brands" into SiteSpecificMatches
7. Exact-match to UmlsMesh
8. Exact match to journal file (necessary for pilot site)
9. Spell check with CSpell
"""


#%%
# ============================================
# 1. Start-up / What to put into place, where
# ============================================
'''
File locations, etc.
'''

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.pyplot import pie, axis, show
import matplotlib.ticker as mtick # used for example in 100-percent bars chart
import numpy as np
import os
import re
import string

# Set working directory and directories for read/write
home_folder = os.path.expanduser('~')
os.chdir(home_folder + '/Projects/classifysearches')

dataRaw = 'data/raw/' # Put log here before running script
dataMatchFiles = 'data/matchFiles/' # Permanent helper files; both reading and writing required
dataInterim = 'data/interim/' # Save to disk as desired, to re-start easily
reports = 'reports/'

SearchConsoleRaw = dataRaw + 'SearchConsoleNew.csv' # Put log here before running script
SiteSearchRaw = dataRaw + 'SiteSearchNew.csv' # Put log here before running script


#%%
# ======================================================================
# 2. Create dataframe from query log; globally update columns and rows
# ======================================================================
'''
If you need to concat multiple files, one option is
searchLog = pd.concat([x1, x2, x3], ignore_index=True)

File will have junk rows at top and bottom that this code removes.
'''

# --------------
# SearchConsole 
# --------------

SearchConsole = pd.read_csv(SearchConsoleRaw, sep=',', index_col=False) # skiprows=7, 
SearchConsole.columns
'''
Script expects:
'Search Query', 'Clicks', 'Impressions', 'CTR', 'Average Position'
'''

# Rename cols
SearchConsole.rename(columns={'Search Query': 'Query', 
                          'Average Position': 'AveragePosition'}, inplace=True)

SearchConsole.columns
'''
'Query', 'Clicks', 'Impressions', 'CTR', 'AveragePosition'
'''

'''
Remove zer-click searches; these are (apparently) searches at Google where the 
search result page answers the questio (but the term has a landing page on our 
site? Unclear what's going on.
For example, https://www.similarweb.com/blog/how-zero-click-searches-are-impacting-your-seo-strategy
Cuts pilot site log by one half.
'''
SearchConsole = SearchConsole.loc[(SearchConsole['Clicks'] > 0)]


# -----------
# SiteSearch
# -----------

SiteSearch = pd.read_csv(SiteSearchRaw, sep=',', index_col=False) # skiprows=7, 
SiteSearch.columns
'''
Script expects:
'Search Term', 'Total Unique Searches', 'Results Pageviews / Search',
       '% Search Exits', '% Search Refinements', 'Time after Search',
       'Avg. Search Depth'
'''

# Rename cols
SiteSearch.rename(columns={'Search Term': 'Query', 
                              'Total Unique Searches': 'TotalUniqueSearches',
                              'Results Pageviews / Search': 'ResultsPVSearch',
                              '% Search Exits': 'PercentSearchExits', 
                              '% Search Refinements': 'PercentSearchRefinements', 
                              'Time after Search': 'TimeAfterSearch',
                              'Avg. Search Depth': 'AvgSearchDepth'}, inplace=True)

SiteSearch.columns
'''
'Query', 'TotalUniqueSearches', 'ResultsPVSearch', 'PercentSearchExits',
       'PercentSearchRefinements', 'TimeAfterSearch', 'AvgSearchDepth'
'''

# Join the two df's, keeping all rows and putting terms in common into one row
CombinedSearch = pd.merge(SearchConsole, SiteSearch, on = ['Query'], how = 'outer')


# New col for total times people searched for term, regardless of location searched from
CombinedSearch['TotalSearchFreq'] = CombinedSearch.fillna(0)['Clicks'] + CombinedSearch.fillna(0)['TotalUniqueSearches']
CombinedSearch = CombinedSearch.sort_values(by='TotalSearchFreq', ascending=False).reset_index(drop=True)

# Dupe off Query column so we can tinker with the dupe
CombinedSearch['AdjustedQueryTerm'] = CombinedSearch['Query'].str.lower()

# Write out this version; won't need most columns until later
writer = pd.ExcelWriter(dataInterim + '01_CombinedSearchFullLog.xlsx')
CombinedSearch.to_excel(writer,'CombinedSearchFull', index=False)
# df2.to_excel(writer,'Sheet2')
writer.save()

# Cut down
CombinedSearchClean = CombinedSearch[['Query', 'AdjustedQueryTerm', 'TotalSearchFreq']]

# Remove rows containing nulls, mistakes
CombinedSearchClean = CombinedSearchClean.dropna()

# Add match cols
CombinedSearchClean['PreferredTerm'] = ''
CombinedSearchClean['SemanticType'] = ''


# Free up memory
del [[SearchConsole, SiteSearch, CombinedSearch]]


# -------------------------
# Remove punctuation, etc.
# -------------------------

# Replace hyphen with space because the below would replace with nothing
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.replace('-', ' ')
# Remove https:// if used
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.replace('http://', '')
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.replace('https://', '')

'''
Regular expressions info from https://docs.python.org/3/library/re.html

^   (Caret.) Matches the start of the string, and in MULTILINE mode also 
    matches immediately after each newline.
\w  For Unicode (str) patterns: Matches Unicode word characters; this 
    includes most characters that can be part of a word in any language, 
    as well as numbers and the underscore. If the ASCII flag is used, only 
    [a-zA-Z0-9_] is matched.
\s  For Unicode (str) patterns: Matches Unicode whitespace characters 
    (which includes [ \t\n\r\f\v], and also many other characters, for 
    example the non-breaking spaces mandated by typography rules in many 
    languages). If the ASCII flag is used, only [ \t\n\r\f\v] is matched.
+   Causes the resulting RE to match 1 or more repetitions of the preceding 
    RE. ab+ will match ‘a’ followed by any non-zero number of ‘b’s; it will 
    not match just ‘a’.

'''
# Remove all chars except a-zA-Z0-9 and leave foreign chars alone
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.replace(r'[^\w\s]+', '')

# Remove modified entries that are now dupes or blank entries
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.replace('  ', ' ') # two spaces to one
CombinedSearchClean['AdjustedQueryTerm'] = CombinedSearchClean['AdjustedQueryTerm'].str.strip() # remove leading and trailing spaces
CombinedSearchClean = CombinedSearchClean.loc[(CombinedSearchClean['AdjustedQueryTerm'] != "")]

# CombinedSearchClean.head()
CombinedSearchClean.columns
'''
'Referrer', 'Query', 'Date', 'SessionID', 'CountForPgDate',
       'AdjustedQueryTerm', 'SemanticType', 'PreferredTerm'
'''



#%%
# =================================================================
# 3. Assign terms with non-English characters to ForeignUnresolved
# =================================================================
'''
UMLS MetaMap should not be given anything other than flat ASCII - no foreign 
characters, no high-ASCII apostrophes or quotes, etc., at least as of October 
2019. Flag these so later you can remove them from processing. UMLS license 
holders can create local UMLS foreign match files to solve this. The current 
implementation runs without need for a UMLS license (i.e., many vocabularies 
have been left out).

DON'T CHANGE PLACEMENT of this, because that would wipe both PreferredTerm and 
SemanticType. Future procedures can replace this content with the correct 
translation.

FIXME - Some of these are not foreign; R&D how to avoid assigning as foreign;
start by seeing whether orig term had non-ascii characters. 

Mistaken assignments that are 1-4-word single-concept searches will be 
overwritten with the correct data. And a smaller number of other types will 
be reclaimed as well.
- valuation of fluorescence in situ hybridization as an ancillary tool to 
    urine cytology in diagnosing urothelial carcinoma
- comparison of a light‐emitting diode with conventional light sources for 
    providing phototherapy to jaundiced newborn infants
- crystal structure of ovalbumin
- diet exercise or diet with exercise 18–65 years old
'''

# Other unrecognized characters, flag as foreign.  Eyeball these once in a while and update the above.
def checkForeign(row):
    # print(row)
    foreignYes = {'AdjustedQueryTerm':row.AdjustedQueryTerm, 'PreferredTerm':'Foreign unresolved', 'SemanticType':'Foreign unresolved'}
    foreignNo = {'AdjustedQueryTerm':row.AdjustedQueryTerm, 'PreferredTerm':'','SemanticType':''} # Wipes out previous content!!
    try:
       row.AdjustedQueryTerm.encode(encoding='utf-8').decode('ascii')
    except UnicodeDecodeError:
       return pd.Series(foreignYes)
    else:
       return pd.Series(foreignNo)
   
CombinedSearchClean[['AdjustedQueryTerm', 'PreferredTerm','SemanticType']] = CombinedSearchClean.apply(checkForeign, axis=1)


# Write out foreign
ForeignUnresolved = CombinedSearchClean[CombinedSearchClean.SemanticType.str.contains("Foreign unresolved") == True]

writer = pd.ExcelWriter(dataInterim + 'ForeignUnresolved.xlsx')
ForeignUnresolved.to_excel(writer,'ForeignUnresolved', index=False)
# df2.to_excel(writer,'Sheet2')
writer.save()

# Remove from consideration
LogAfterForeign = CombinedSearchClean[CombinedSearchClean.SemanticType.str.contains("Foreign unresolved") == False]

# Free memory
del [[ForeignUnresolved, CombinedSearchClean]]


#%%
# =========================================================================================
# 4. Make special-case assignments with F&R, RegEx: Bibliographic, Numeric, Named entities
# =========================================================================================
'''
Later procedures won't be able to match the below very well, so match them here.

NOTE: Doing this will ignore concepts when the search query was a complex one.
We get great coverage but in some cases this might sacrifice completeness.
'''

# --- Bibliographic Entity: Usually people searching for a document title ---
# Assign ALL queries over x char to 'Bibliographic Entity' (often citations, search strategies, publication titles...)
LogAfterForeign.loc[(LogAfterForeign['AdjustedQueryTerm'].str.len() > 40), 'PreferredTerm'] = 'Bibliographic Entity'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('page number 1 page size', na=False), 'PreferredTerm'] = 'Bibliographic Entity'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('Bibliographic Entity', na=False), 'SemanticType'] = 'Bibliographic Entity'


# --- Numeric ID: Usually people searching for database ID ---
# Assign entries starting with 3 digits
# FIXME - Clarify and grab the below, PMID, ISSN, ISBN 0-8016-5253-7), etc.
# LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('^[0-9]{3,}', na=False), 'PreferredTerm'] = 'Numeric ID'
LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('[0-9]{5,}', na=False), 'PreferredTerm'] = 'Numeric ID'
LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('[0-9]{4,}-[0-9]{4,}', na=False), 'PreferredTerm'] = 'Numeric ID'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('Numeric ID', na=False), 'SemanticType'] = 'Numeric ID'

# --- Commonly searched products or unique names --- 
LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('pubmed', na=False), 'PreferredTerm'] = 'PubMed/PMC/MEDLINE'
LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('medline', na=False), 'PreferredTerm'] = 'PubMed/PMC/MEDLINE'
LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('journal abbreviation', na=False), 'PreferredTerm'] = 'PubMed/PMC/MEDLINE'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('PubMed/PMC/MEDLINE', na=False), 'SemanticType'] = 'Product-NLM'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('mesh', na=False), 'PreferredTerm'] = 'MeSH'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('MeSH', na=False), 'SemanticType'] = 'Product-NLM'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('umls', na=False), 'PreferredTerm'] = 'UMLS'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('UMLS', na=False), 'SemanticType'] = 'Product-LHC-MMS-Terminologies'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('rxnorm', na=False), 'PreferredTerm'] = 'RxNorm'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('RxNorm', na=False), 'SemanticType'] = 'Product-LHC-MMS-Terminologies'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('snomed', na=False), 'PreferredTerm'] = 'SNOMED CT'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('SNOMED CT', na=False), 'SemanticType'] = 'Product-LHC-MMS-Terminologies'

LogAfterForeign.loc[LogAfterForeign['AdjustedQueryTerm'].str.contains('index medicus', na=False), 'PreferredTerm'] = 'Index Medicus'
LogAfterForeign.loc[LogAfterForeign['PreferredTerm'].str.contains('Index Medicus', na=False), 'SemanticType'] = 'Product-NLM'


# -------------
# How we doin?
# -------------

# Total queries in log
SearchesRepresentedTot = LogAfterForeign['TotalSearchFreq'].sum().astype(int)
SearchesAssignedTot = LogAfterForeign.loc[LogAfterForeign['SemanticType'] != '']
SearchesAssignedTot = SearchesAssignedTot['TotalSearchFreq'].sum().astype(int)
SearchesAssignedPercent = (SearchesAssignedTot / SearchesRepresentedTot * 100).astype(int)
# PercentOfSearchesUnAssigned = 100 - PercentOfSearchesAssigned
RowsTot = len(LogAfterForeign)
RowsAssignedCnt = (LogAfterForeign['SemanticType'].values != '').sum() # .isnull().sum()
# RowsUnassignedCnt = TotRows - RowsAssigned
RowsAssignedPercent = (RowsAssignedCnt / RowsTot * 100).astype(int)

# print("\nTop Semantic Types\n{}".format(LogAfterForeign['SemanticType'].value_counts().head(10)))
print("\n==========================================================\n ** LogAfterForeign: {}% of total search volume tagged **\n==========================================================\n{:,} of {:,} searches ({}%) assigned;\n{:,} of {:,} rows ({}%) assigned\n".format(SearchesAssignedPercent, SearchesAssignedTot, SearchesRepresentedTot, SearchesAssignedPercent, RowsAssignedCnt, RowsTot, RowsAssignedPercent))


'''


TotQueriesAssigned = TotQueriesAssigned[LogAfterForeign['SemanticType'] != '' = True]


RowCountLeftToSolve = 


.sum() # .notnull().sum()



TotUniqueEntries = LogAfterForeign['AdjustedQueryTerm'].nunique()

Assigned = 
PercentAssigned = (Assigned / TotUniqueEntries * 100).astype(int)
'''

#%%
# ======================================================================
# 5. Exact-match to site-specific and vetted past matches
# ======================================================================
'''
Build a file of terms your site visitors are most commonly searching for,
which might be handled poorly by the resources in Phase 2, to include:
    1. Your product and service names, as people search for them
    2. Person names, whether staff, authors, etc.
    3. Organizational names specific to your organization
    4. Any homonymns, etc., that you review after Phase 2 that you want to 
        control tagging for to PREVENT the Phase 2 tools from tagging.

Focus on queries that are correct as typed and can be extact-matched to terms
that Phase 2 might handle incorrectly. Over time this will lighten the manual 
work in later steps.

DO use correct spellings, because later we fuzzy match off of the terms here. 
Okay to add previously matched foreign terms here.

** TO BUILD A NEW FILE **
Export the top 1,000 queries from the past 12 months and 
cluster them using the code at x. Then process similar BRANDED PRODUCTS, etc.
(ONLY the categories above!) in a spreadsheet, building the additional column 
information as you go, following what's in the model PastMatches file.
'''

# -------------------------
# SiteSpecificMatches.xlsx
# -------------------------

# Bring in
SiteSpecificMatches = pd.read_excel(dataMatchFiles + 'SiteSpecificMatches.xlsx')
SiteSpecificMatches.columns
'''
'AdjustedQueryTerm', 'PreferredTerm', 'SemanticType'
'''


# Combine
LogAfterSiteSpecific = pd.merge(LogAfterForeign, SiteSpecificMatches, how='left', on=['AdjustedQueryTerm'])
LogAfterSiteSpecific.columns
'''
'Query_x', 'AdjustedQueryTerm', 'TotalSearchFreq', 'PreferredTerm_x',
       'SemanticType_x', 'PreferredTerm_y', 'SemanticType_y', 'Query_y'
'''

# Future: Look for a better way to do the above - MERGE WITH CONDITIONAL OVERWRITE. Temporary fix:
# LogAfterSiteSpecific['Query2'] = LogAfterSiteSpecific['Query_x'].where(LogAfterSiteSpecific['Query_x'].notnull(), LogAfterSiteSpecific['Query_y'])
# LogAfterSiteSpecific['Query2'] = LogAfterSiteSpecific['Query_y'].where(LogAfterSiteSpecific['Query_y'].notnull(), LogAfterSiteSpecific['Query_x'])
LogAfterSiteSpecific['PreferredTerm2'] = LogAfterSiteSpecific['PreferredTerm_x'].where(LogAfterSiteSpecific['PreferredTerm_x'].notnull(), LogAfterSiteSpecific['PreferredTerm_y'])
LogAfterSiteSpecific['PreferredTerm2'] = LogAfterSiteSpecific['PreferredTerm_y'].where(LogAfterSiteSpecific['PreferredTerm_y'].notnull(), LogAfterSiteSpecific['PreferredTerm_x'])
LogAfterSiteSpecific['SemanticType2'] = LogAfterSiteSpecific['SemanticType_x'].where(LogAfterSiteSpecific['SemanticType_x'].notnull(), LogAfterSiteSpecific['SemanticType_y'])
LogAfterSiteSpecific['SemanticType2'] = LogAfterSiteSpecific['SemanticType_y'].where(LogAfterSiteSpecific['SemanticType_y'].notnull(), LogAfterSiteSpecific['SemanticType_x'])
LogAfterSiteSpecific.drop(['PreferredTerm_x', 'PreferredTerm_y', 'SemanticType_x', 'SemanticType_y'], axis=1, inplace=True)
LogAfterSiteSpecific.rename(columns={'PreferredTerm2': 'PreferredTerm',
                                     'SemanticType2': 'SemanticType'}, inplace=True)
# 'Query_x', 'Query_y', 'Query2': 'Query',

LogAfterSiteSpecific.columns


'''
Early in your project we recommend that you cycle through the clustering several 
times at this point.

'''

UnassignedAfterSS = LogAfterSiteSpecific.loc[LogAfterSiteSpecific['SemanticType'] == '']
# Set a limit, say, frequency of 10 or more
UnassignedAfterSS = UnassignedAfterSS.loc[(UnassignedAfterSS['TotalSearchFreq'] >= 5)]
# We updated AdjustedQueryTerm so put that in the place of Query
UnassignedAfterSS = UnassignedAfterSS[['AdjustedQueryTerm']].reset_index(drop=True)
UnassignedAfterSS.rename(columns={'AdjustedQueryTerm': 'Query'}, inplace=True)


# -------------
# How we doin?
# -------------

# Total queries in log
SearchesRepresentedTot = LogAfterSiteSpecific['TotalSearchFreq'].sum().astype(int)
SearchesAssignedTot = LogAfterSiteSpecific.loc[LogAfterSiteSpecific['SemanticType'] != '']
SearchesAssignedTot = SearchesAssignedTot['TotalSearchFreq'].sum().astype(int)
SearchesAssignedPercent = (SearchesAssignedTot / SearchesRepresentedTot * 100).astype(int)
# PercentOfSearchesUnAssigned = 100 - PercentOfSearchesAssigned
RowsTot = len(LogAfterSiteSpecific)
RowsAssignedCnt = (LogAfterSiteSpecific['SemanticType'].values != '').sum() # .isnull().sum()
# RowsUnassignedCnt = TotRows - RowsAssigned
RowsAssignedPercent = (RowsAssignedCnt / RowsTot * 100).astype(int)

# print("\nTop Semantic Types\n{}".format(LogAfterSiteSpecific['SemanticType'].value_counts().head(10)))
print("\n===============================================================\n ** LogAfterSiteSpecific: {}% of total search volume tagged **\n===============================================================\n{:,} of {:,} searches ({}%) assigned;\n{:,} of {:,} rows ({}%) assigned\n".format(SearchesAssignedPercent, SearchesAssignedTot, SearchesRepresentedTot, SearchesAssignedPercent, RowsAssignedCnt, RowsTot, RowsAssignedPercent))



# -----------------
# PastMatches.xlsx
# -----------------

# Bring in file containing this site's historical matches
PastMatches = pd.read_excel(dataMatchFiles + 'PastMatches.xlsx')
PastMatches.columns
'''
'SemanticType', 'AdjustedQueryTerm', 'PreferredTerm', 'ui'
'''



# Second, focus on AdjustedQueryTerm in PastMatches; higher success rate.
LogAfterPastMatches = pd.merge(LogAfterSiteSpecific, PastMatches, how='left', left_on=['AdjustedQueryTerm'], right_on=['AdjustedQueryTerm'])
LogAfterPastMatches.columns
'''
'Query', 'AdjustedQueryTerm', 'TotalSearchFreq', 'PreferredTerm_x',
       'SemanticType_x', 'PreferredTerm_y', 'SemanticType_y', 'ui'
'''

# Future: Look for a better way to do the above - MERGE WITH CONDITIONAL OVERWRITE. 
# Temporary fix: Move _y into _x if _x is empty; or here: where _x has content, use _x, otherwise use _y
LogAfterPastMatches['PreferredTerm2'] = LogAfterPastMatches['PreferredTerm_x'].where(LogAfterPastMatches['PreferredTerm_x'].notnull(), LogAfterPastMatches['PreferredTerm_y'])
LogAfterPastMatches['PreferredTerm2'] = LogAfterPastMatches['PreferredTerm_y'].where(LogAfterPastMatches['PreferredTerm_y'].notnull(), LogAfterPastMatches['PreferredTerm_x'])
LogAfterPastMatches['SemanticType2'] = LogAfterPastMatches['SemanticType_x'].where(LogAfterPastMatches['SemanticType_x'].notnull(), LogAfterPastMatches['SemanticType_y'])
LogAfterPastMatches['SemanticType2'] = LogAfterPastMatches['SemanticType_y'].where(LogAfterPastMatches['SemanticType_y'].notnull(), LogAfterPastMatches['SemanticType_x'])

LogAfterPastMatches.drop(['PreferredTerm_x', 'PreferredTerm_y',
                          'SemanticType_x', 'SemanticType_y'], axis=1, inplace=True)
LogAfterPastMatches.rename(columns={'PreferredTerm2': 'PreferredTerm',
                                    'SemanticType2': 'SemanticType'}, inplace=True)

LogAfterPastMatches.columns


"""
TODO - Clean up the journal match file before going further with this - 
incorrect column separators for some rows. Re-create source and separate with |
pipe.

# -------------------
# JournalMatches.csv
# -------------------
'''
Example of custom list matching
'''
    
JournalMatches = pd.read_csv(dataMatchFiles + 'JournalMatches.csv', sep = ',') # , skiprows=2
JournalMatches.columns
'''
'AdjustedQueryTerm', 'PreferredTerm', 'SemanticType', 'ui'
'''

"""


# -------------
# How we doin?
# -------------

# Total queries in log
SearchesRepresentedTot = LogAfterPastMatches['TotalSearchFreq'].sum().astype(int)
SearchesAssignedTot = LogAfterPastMatches.loc[LogAfterPastMatches['SemanticType'] != '']
SearchesAssignedTot = SearchesAssignedTot['TotalSearchFreq'].sum().astype(int)
SearchesAssignedPercent = (SearchesAssignedTot / SearchesRepresentedTot * 100).astype(int)
# PercentOfSearchesUnAssigned = 100 - PercentOfSearchesAssigned
RowsTot = len(LogAfterPastMatches)
RowsAssignedCnt = (LogAfterPastMatches['SemanticType'].values != '').sum() # .isnull().sum()
# RowsUnassignedCnt = TotRows - RowsAssigned
RowsAssignedPercent = (RowsAssignedCnt / RowsTot * 100).astype(int)

# print("\nTop Semantic Types\n{}".format(LogAfterPastMatches['SemanticType'].value_counts().head(10)))
print("\n==============================================================\n ** LogAfterPastMatches: {}% of total search volume tagged **\n==============================================================\n{:,} of {:,} searches ({}%) assigned;\n{:,} of {:,} rows ({}%) assigned\n".format(SearchesAssignedPercent, SearchesAssignedTot, SearchesRepresentedTot, SearchesAssignedPercent, RowsAssignedCnt, RowsTot, RowsAssignedPercent))


# Separate next operations so previous matches won't be overwritten
UnmatchedAfterPastMatches = LogAfterPastMatches.loc[LogAfterPastMatches['SemanticType'] == '']
UnmatchedAfterPastMatches = UnmatchedAfterPastMatches[['AdjustedQueryTerm', 'TotalSearchFreq']].reset_index(drop=True)
UnmatchedAfterPastMatches.rename(columns={'AdjustedQueryTerm': 'Search Query'}, inplace=True)


# Remove from memory. PastMatches is used below, so leave that.
del [[LogAfterForeign, LogAfterSiteSpecific, SiteSpecificMatches, 
UnassignedAfterSS]]



#%%
# ==================================================================================
# 6. Eyeball results; manually classify remaining "brands" into SiteSpecificMatches
# ==================================================================================
'''
Open spreadsheet of remaining unmatched; manually move ONLY your remaining high-frequency 
brands into SiteSpecificMatches. You can also re-run clustering. We
developed a Django-NoSQL interface, which could be used for long-term projects;
https://github.com/NCBI-Hackathons/Semantic-search-log-analysis-pipeline.

If you're using Google Search Console data, you can probably use the site area
where the person landed to help you classify the terms.
'''

# write out
writer = pd.ExcelWriter(dataInterim + 'UnmatchedAfterPastMatches.xlsx')
UnmatchedAfterPastMatches.to_excel(writer,'UnmatchedAfterPastMatches')
# df2.to_excel(writer,'Sheet2')
writer.save()




#%%
# ====================================================================
# 7. Exact-match to UmlsMesh
# ====================================================================
'''
Optional. Attempt local exact matching against 3.7-million-term UMLS file. 
Because of the license agreement this file will not be shared, but it is a 
combination of MRCONSO.RFF and MRSTY.RRF that is reduced to only the 
preferred "atom" for each concept (CUI) in the vocabulary, and each concept 
includes its semantic type assignment(s). Saves a lot of time with the API, 
but not necessary for the project.

Restart?
LogAfterForeign = pd.read_excel('01_Import-transform_files/LogAfterForeign.xlsx')
'''

# Reviewing from above
UnmatchedAfterPastMatches.columns
'''
'Search Query'
'''

# Custom MeSH vocabulary from UMLS, with semantic types
UmlsMesh = pd.read_csv(dataMatchFiles + 'UmlsMesh.csv', sep='|') # , index_col=False
UmlsMesh.drop('wordCount', axis=1, inplace=True)
UmlsMesh.columns
'''
'AdjustedQueryTerm', 'PreferredTerm', 'SemanticType', 'ui', 'LAT',
       'SAB'
'''

# Combine
UmlsMeshMatches = pd.merge(UnmatchedAfterPastMatches, UmlsMesh, how='inner', left_on=['Search Query'], right_on=['AdjustedQueryTerm'])
UmlsMeshMatches.columns
'''
'Search Query', 'TotalSearchFreq', 'AdjustedQueryTerm', 'PreferredTerm',
       'SemanticType', 'ui', 'LAT', 'SAB'
'''

# Join to full list
LogAfterUmlsMesh = pd.merge(LogAfterPastMatches, UmlsMeshMatches, how='left', left_on=['AdjustedQueryTerm'], right_on=['Search Query'])
LogAfterUmlsMesh.columns
'''
'Query', 'AdjustedQueryTerm_x', 'TotalSearchFreq_x', 'ui_x',
       'PreferredTerm_x', 'SemanticType_x', 'Search Query',
       'TotalSearchFreq_y', 'AdjustedQueryTerm_y', 'PreferredTerm_y',
       'SemanticType_y', 'ui_y', 'LAT', 'SAB'
'''

# Future: Look for a better way to do the above - MERGE WITH CONDITIONAL OVERWRITE. 
# Temporary fix: Move _y into _x if _x is empty; or here: where _x has content, use _x, otherwise use _y
LogAfterUmlsMesh['AdjustedQueryTerm2'] = LogAfterUmlsMesh['AdjustedQueryTerm_x'].where(LogAfterUmlsMesh['AdjustedQueryTerm_x'].notnull(), LogAfterUmlsMesh['AdjustedQueryTerm_y'])
LogAfterUmlsMesh['AdjustedQueryTerm2'] = LogAfterUmlsMesh['AdjustedQueryTerm_y'].where(LogAfterUmlsMesh['AdjustedQueryTerm_y'].notnull(), LogAfterUmlsMesh['AdjustedQueryTerm_x'])
LogAfterUmlsMesh['TotalSearchFreq2'] = LogAfterUmlsMesh['TotalSearchFreq_x'].where(LogAfterUmlsMesh['TotalSearchFreq_x'].notnull(), LogAfterUmlsMesh['TotalSearchFreq_y'])
LogAfterUmlsMesh['TotalSearchFreq2'] = LogAfterUmlsMesh['TotalSearchFreq_y'].where(LogAfterUmlsMesh['TotalSearchFreq_y'].notnull(), LogAfterUmlsMesh['TotalSearchFreq_x'])
LogAfterUmlsMesh['ui2'] = LogAfterUmlsMesh['ui_x'].where(LogAfterUmlsMesh['ui_x'].notnull(), LogAfterUmlsMesh['ui_y'])
LogAfterUmlsMesh['ui2'] = LogAfterUmlsMesh['ui_y'].where(LogAfterUmlsMesh['ui_y'].notnull(), LogAfterUmlsMesh['ui_x'])
LogAfterUmlsMesh['PreferredTerm2'] = LogAfterUmlsMesh['PreferredTerm_x'].where(LogAfterUmlsMesh['PreferredTerm_x'].notnull(), LogAfterUmlsMesh['PreferredTerm_y'])
LogAfterUmlsMesh['PreferredTerm2'] = LogAfterUmlsMesh['PreferredTerm_y'].where(LogAfterUmlsMesh['PreferredTerm_y'].notnull(), LogAfterUmlsMesh['PreferredTerm_x'])
LogAfterUmlsMesh['SemanticType2'] = LogAfterUmlsMesh['SemanticType_x'].where(LogAfterUmlsMesh['SemanticType_x'].notnull(), LogAfterUmlsMesh['SemanticType_y'])
LogAfterUmlsMesh['SemanticType2'] = LogAfterUmlsMesh['SemanticType_y'].where(LogAfterUmlsMesh['SemanticType_y'].notnull(), LogAfterUmlsMesh['SemanticType_x'])

LogAfterUmlsMesh.drop(['AdjustedQueryTerm_x', 'AdjustedQueryTerm_y',
                           'TotalSearchFreq_x', 'TotalSearchFreq_y',
                          'ui_x', 'ui_y', 'PreferredTerm_x', 'PreferredTerm_y',
                          'SemanticType_x', 'SemanticType_y'], axis=1, inplace=True)
LogAfterUmlsMesh.rename(columns={'AdjustedQueryTerm2': 'AdjustedQueryTerm',
                                     'TotalSearchFreq2': 'TotalSearchFreq',
                                     'ui2': 'ui', 'PreferredTerm2': 'PreferredTerm',
                                     'SemanticType2': 'SemanticType'}, inplace=True)

LogAfterUmlsMesh.columns
'''
'Query', 'Search Query', 'LAT', 'SAB', 'AdjustedQueryTerm',
       'TotalSearchFreq', 'ui', 'PreferredTerm', 'SemanticType'
'''

# Clean up
LogAfterUmlsMesh.drop(['Search Query', 'LAT', 'SAB'], axis=1, inplace=True)
LogAfterUmlsMesh = LogAfterUmlsMesh[['AdjustedQueryTerm', 'PreferredTerm', 'SemanticType', 'TotalSearchFreq', 'ui','Query']]

# Separate next operations so previous matches won't be overwritten
UnmatchedAfterUmlsMesh = LogAfterUmlsMesh.loc[LogAfterUmlsMesh['SemanticType'] == '']
UnmatchedAfterUmlsMesh = UnmatchedAfterUmlsMesh[['AdjustedQueryTerm', 'TotalSearchFreq']].reset_index(drop=True)
# UnmatchedAfterUmlsMesh.rename(columns={'AdjustedQueryTerm': 'Search Query'}, inplace=True)


# -------------
# How we doin?
# -------------

# Total queries in log
SearchesRepresentedTot = LogAfterUmlsMesh['TotalSearchFreq'].sum().astype(int)
SearchesAssignedTot = LogAfterUmlsMesh.loc[LogAfterUmlsMesh['SemanticType'] != '']
SearchesAssignedTot = SearchesAssignedTot['TotalSearchFreq'].sum().astype(int)
SearchesAssignedPercent = (SearchesAssignedTot / SearchesRepresentedTot * 100).astype(int)
# PercentOfSearchesUnAssigned = 100 - PercentOfSearchesAssigned
RowsTot = len(LogAfterUmlsMesh)
RowsAssignedCnt = (LogAfterUmlsMesh['SemanticType'].values != '').sum() # .isnull().sum()
# RowsUnassignedCnt = TotRows - RowsAssigned
RowsAssignedPercent = (RowsAssignedCnt / RowsTot * 100).astype(int)

# print("\nTop Semantic Types\n{}".format(LogAfterUmlsMesh['SemanticType'].value_counts().head(10)))
print("\n===========================================================\n ** LogAfterUmlsMesh: {}% of total search volume tagged **\n===========================================================\n{:,} of {:,} searches ({}%) assigned;\n{:,} of {:,} rows ({}%) assigned\n".format(SearchesAssignedPercent, SearchesAssignedTot, SearchesRepresentedTot, SearchesAssignedPercent, RowsAssignedCnt, RowsTot, RowsAssignedPercent))


# Free up some memory
del [[LogAfterPastMatches, UmlsMesh, UmlsMeshMatches, UnmatchedAfterPastMatches]]


# Somehow rows are being added over time. What is getting duplicated?
# https://stackoverflow.com/questions/14657241/how-do-i-get-a-list-of-all-the-duplicate-items-using-pandas-in-python
# Fix later, after re-joining to original log so you can tell the diff between google.com and site searches.
dupeCheck = pd.concat(g for _, g in LogAfterUmlsMesh.groupby("Query") if len(g) > 1)


#%%
# ==========================================================
# 8. Exact match to journal file (necessary for pilot site)
# ==========================================================
'''
Necessary on the pilot site; other sites probably do not need. Okay for this 
one to overwrite "Numeric ID" rows.
'''

JournalMatches = pd.read_csv(dataMatchFiles + 'JournalMatches.txt', sep='|') # , index_col=False, skiprows=7, 
JournalMatches.columns
'''
'AdjustedQueryTerm', 'PreferredTerm', 'SemanticType', 'ui'
'''

# Join to full list
LogAfterJournals = pd.merge(LogAfterUmlsMesh, JournalMatches, how='left', left_on=['AdjustedQueryTerm'], right_on=['AdjustedQueryTerm'])
LogAfterJournals.columns
'''
'AdjustedQueryTerm', 'PreferredTerm_x', 'SemanticType_x',
       'TotalSearchFreq', 'ui_x', 'Query', 'PreferredTerm_y', 'SemanticType_y',
       'ui_y'
'''

# Future: Look for a better way to do the above - MERGE WITH CONDITIONAL OVERWRITE. 
# Temporary fix: Move _y into _x if _x is empty; or here: where _x has content, use _x, otherwise use _y
LogAfterJournals['ui2'] = LogAfterJournals['ui_x'].where(LogAfterJournals['ui_x'].notnull(), LogAfterJournals['ui_y'])
LogAfterJournals['ui2'] = LogAfterJournals['ui_y'].where(LogAfterJournals['ui_y'].notnull(), LogAfterJournals['ui_x'])
LogAfterJournals['PreferredTerm2'] = LogAfterJournals['PreferredTerm_x'].where(LogAfterJournals['PreferredTerm_x'].notnull(), LogAfterJournals['PreferredTerm_y'])
LogAfterJournals['PreferredTerm2'] = LogAfterJournals['PreferredTerm_y'].where(LogAfterJournals['PreferredTerm_y'].notnull(), LogAfterJournals['PreferredTerm_x'])
LogAfterJournals['SemanticType2'] = LogAfterJournals['SemanticType_x'].where(LogAfterJournals['SemanticType_x'].notnull(), LogAfterJournals['SemanticType_y'])
LogAfterJournals['SemanticType2'] = LogAfterJournals['SemanticType_y'].where(LogAfterJournals['SemanticType_y'].notnull(), LogAfterJournals['SemanticType_x'])

LogAfterJournals.drop(['ui_x', 'ui_y', 'PreferredTerm_x', 'PreferredTerm_y',
                          'SemanticType_x', 'SemanticType_y'], axis=1, inplace=True)
LogAfterJournals.rename(columns={'ui2': 'ui', 'PreferredTerm2': 'PreferredTerm',
                                     'SemanticType2': 'SemanticType'}, inplace=True)

LogAfterJournals.columns
'''
'AdjustedQueryTerm', 'TotalSearchFreq', 'Query', 'ui', 'PreferredTerm',
       'SemanticType'
'''

# Separate next operations so previous matches won't be overwritten
UnmatchedAfterJournals = LogAfterJournals.loc[LogAfterJournals['SemanticType'] == '']
UnmatchedAfterJournals = UnmatchedAfterJournals[['AdjustedQueryTerm', 'TotalSearchFreq']].reset_index(drop=True)

    
# -------------
# How we doin?
# -------------

# Total queries in log
SearchesRepresentedTot = LogAfterJournals['TotalSearchFreq'].sum().astype(int)
SearchesAssignedTot = LogAfterJournals.loc[LogAfterJournals['SemanticType'] != '']
SearchesAssignedTot = SearchesAssignedTot['TotalSearchFreq'].sum().astype(int)
SearchesAssignedPercent = (SearchesAssignedTot / SearchesRepresentedTot * 100).astype(int)
# PercentOfSearchesUnAssigned = 100 - PercentOfSearchesAssigned
RowsTot = len(LogAfterJournals)
RowsAssignedCnt = (LogAfterJournals['SemanticType'].values != '').sum() # .isnull().sum()
# RowsUnassignedCnt = TotRows - RowsAssigned
RowsAssignedPercent = (RowsAssignedCnt / RowsTot * 100).astype(int)

# print("\nTop Semantic Types\n{}".format(LogAfterJournals['SemanticType'].value_counts().head(10)))
print("\n===========================================================\n ** LogAfterJournals: {}% of total search volume tagged **\n===========================================================\n{:,} of {:,} searches ({}%) assigned;\n{:,} of {:,} rows ({}%) assigned\n".format(SearchesAssignedPercent, SearchesAssignedTot, SearchesRepresentedTot, SearchesAssignedPercent, RowsAssignedCnt, RowsTot, RowsAssignedPercent))


# Free up some memory
del [[JournalMatches, LogAfterUmlsMesh, PastMatches, UnmatchedAfterUmlsMesh]]


#%%
# ==========================================================
# 9. Add spelling suggestions from CSpell
# ==========================================================
'''
See wiki for installation, help, etc.: 
    https://github.com/NCBI-Codeathons/Use-UMLS-and-Python-to-classify-website-visitor-queries-into-measurable-categories/wiki/3.-Installing-and-running-CSpell

No data yet on file size limits; 10,000 rows can be processed in around 12
minutes on a normal workstation, whcih uses these options:

cspell -I:cspell_infile.txt -si -o:cspell_result.txt

The order of the file is search frequency - probably the best order to use.
'''

# You could limit by search frequency
# CSpell_infile = UnmatchedAfterJournals.loc[(UnmatchedAfterJournals['TotalSearchFreq'] >= 4)]
# If something is searched many times, it's probably not misspelled.

# You could limit by eyeballing the df; would be a way to select the part of the
# df most amenable to spelling corrections. 
# cspell_infile = UnmatchedAfterJournals.iloc[378:2800]
# cspell_infile = UnmatchedAfterJournals.iloc[2801:12800]
# cspell_infile = UnmatchedAfterJournals.iloc[12800:12800]
cspell_infile = UnmatchedAfterJournals.iloc[12801:59397]

# reduce to one col
cspell_infile = cspell_infile[['AdjustedQueryTerm']]

# Write out
cspell_infile.to_csv(dataInterim + 'cspell_infile.txt', encoding='utf-8', index=False)



# ---------------------------------------
# NOW PROCESS THE FILE OUTSIDE OF PYTHON
# BEFORE RESUMING WITH THE BELOW.
# ---------------------------------------



cspellSuggestions = pd.read_csv(dataInterim + 'cspell_result.txt', sep='|') # , index_col=False, skiprows=7, 
cspellSuggestions.columns

# Drop rows where input and output are the same
# https://stackoverflow.com/questions/43951558/remove-rows-that-two-columns-have-the-same-values-by-pandas
cspellSuggestions = cspellSuggestions[cspellSuggestions['AdjustedQueryTerm'] != cspellSuggestions['adjusted query term']]



#%%

"""
# -------------------------------
# How we doin? Visualize results
# -------------------------------


'''
FIXME - Add: x% of the terms searched 3 times or more, have been classified

# Full dataset, which terms were searched 3+ times?
cntThreeOrMore = LogAfterStep1.groupby('AdjustedQueryTerm').size()
cntThreeOrMore = pd.DataFrame({'timesSearched':cntThreeOrMore})
cntThreeOrMore = cntThreeOrMore.sort_values(by='timesSearched', ascending=False)
cntThreeOrMore = cntThreeOrMore.reset_index()
threeOrMoreSearches = cntThreeOrMore.loc[cntThreeOrMore['timesSearched'] >= 3]

# 5454

# Count of these terms where SemanticType notnull

cutDownFull = LogAfterStep1[['AdjustedQueryTerm', 'SemanticType']]

cutDownFull.loc[cutDownFull['SemanticType'].str.contains(''), 'SemanticType'] = 'Yes'
'''

print("\n====================================================================\n ** Import and Trasformation Completed for {}! **\n    When running multiple files, re-name each new file\n====================================================================".format(logFileName))


# -----------------
# Visualize results
# -----------------
# These break in Spyder autorun

'''
# Pie for percentage of rows assigned; https://pythonspot.com/matplotlib-pie-chart/
totCount = len(LogAfterStep1)
Assigned = (LogAfterStep1['PreferredTerm'].values != '').sum()
Unassigned = (LogAfterStep1['PreferredTerm'].values == '').sum()
labels = ['Assigned', 'Unassigned']
sizes = [Assigned, Unassigned]
colors = ['steelblue', '#fc8d59']
explode = (0.1, 0)  # explode 1st slice
plt.pie(sizes, explode=explode, labels=labels, colors=colors,
        autopct='%1.f%%', shadow=False, startangle=100)
plt.axis('equal')
plt.title("Status after 'Step 1' processing - \n{} queries with {} unassigned".format(totCount, Unassigned))
plt.show()


# Bar of SemanticType categories, horizontal
# Source: http://robertmitchellv.com/blog-bar-chart-annotations-pandas-mpl.html
ax = LogAfterStep1['SemanticType'].value_counts()[:20].plot(kind='barh', figsize=(10,6),
                                                 color="steelblue", fontsize=10);
ax.set_alpha(0.8)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.set_title("Top 20 semantic types assigned after 'Step 1' processing \nwith {:,} of {:,} unassigned".format(Unassigned, totCount), fontsize=14)
ax.set_xlabel("Number of searches", fontsize=9);
# set individual bar lables using above list
for i in ax.patches:
    # get_width pulls left or right; get_y pushes up or down
    ax.text(i.get_width()+.1, i.get_y()+.31, str(round((i.get_width()), 2)), fontsize=9, color='dimgrey')
# invert for largest on top 
ax.invert_yaxis()
plt.gcf().subplots_adjust(left=0.3)
'''


#%%


# =====================================================
# If working with multiple processed 'uniques' at once
# =====================================================
'''
For start-up / multiple runs, I run whole script on each of several log files, 
renaming output files after each run, then open and combine, for the API work
that is next.
'''

# Open step 1 files for uniques (the API)
uniques01 = pd.read_excel(dataInterim + 'SiteSearch2018-12-uniquesForStep2.xlsx')
uniques02 = pd.read_excel(dataInterim + 'SiteSearch2019-01-uniquesForStep2.xlsx')
uniques03 = pd.read_excel(dataInterim + 'SiteSearch2019-02-uniquesForStep2.xlsx')
uniques04 = pd.read_excel(dataInterim + 'SiteSearch2019-03-uniquesForStep2.xlsx')
uniques05 = pd.read_excel(dataInterim + 'SiteSearch2019-04-uniquesForStep2.xlsx')
uniques06 = pd.read_excel(dataInterim + 'SiteSearch2019-05-uniquesForStep2.xlsx')


# Append new data
combinedLogs = uniques01.append([uniques02, uniques03, uniques04, uniques05,
                                            uniques06])

    
# If combinedLogs is huge, you could have a look at a subset
viewRows = combinedLogs[260000:260800]

# Free memory
del [[uniques05, uniques06, uniques07, uniques08, uniques09, uniques10]]

# Running API requires time; try focusing on terms searched 3+ times, 
# i.e., it's probably a real thing. May-Oct 18, mine was 13,426 terms, nice
listToCheck1 = combinedLogs[combinedLogs.timesSearched >= 3]

# Or limit by rows
# listToCheck1 = combinedLogs[0:15000]


# ----------------------------------------------------



viewRows = combinedLogs[10000:11000]



'''
# Open step 1 files for log
LogAfterStep1201805 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-05.xlsx')
LogAfterStep1201806 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-06.xlsx')
LogAfterStep1201807 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-07.xlsx')
LogAfterStep1201808 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-08.xlsx')
LogAfterStep1201809 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-09.xlsx')
LogAfterStep1201810 = pd.read_excel(dataInterim + 'LogAfterStep1-2018-10.xlsx')

# Append new data
combinedLogs = LogAfterStep1201805.append([LogAfterStep1201806, LogAfterStep1201807, 
                                            LogAfterStep1201808, LogAfterStep1201809,
                                            LogAfterStep1201810], sort=True)

# del [[LogAfterStep1201805, LogAfterStep1201806, LogAfterStep1201807, LogAfterStep1201808, LogAfterStep1201809, LogAfterStep1201810]]


combinedLogs.columns
'''
'ProbablyMeantGSTerm', 'Query', 'Referrer', 'SearchID',
'SemanticType', 'SessionID', 'StaffYN', 'Timestamp',
'AdjustedQueryTerm', 'PreferredTerm', 'ui'
'''

combinedLogs = combinedLogs[['SearchID', 'SessionID', 'Referrer', 
                             'AdjustedQueryTerm','PreferredTerm', 'ui', 
                             'ProbablyMeantGSTerm', 'SemanticType', 'StaffYN',
                             'Timestamp']]

viewRows = combinedLogs[10000:11000]

# Save to file so you can open in future sessions
writer = pd.ExcelWriter(dataInterim + 'combinedLogs.xlsx')
combinedLogs.to_excel(writer,'combinedLogs')
# df2.to_excel(writer,'Sheet2')
writer.save()
'''

'''
# I think the below can be obsoleted; I was not understanding. Replaced 9/19


# FIXME - see notes below, problem here
LogAfterPastMatches = pd.merge(LogAfterUmlsMesh, PastMatches, left_on=['AdjustedQueryTerm', 'ui', 'PreferredTerm', 'SemanticType'], right_on=['AdjustedQueryTerm', 'ui', 'PreferredTerm', 'SemanticType'], how='left')

LogAfterPastMatches.columns
'''
'Referrer', 'Query', 'Date', 'SessionID', 'CountForPgDate',
'AdjustedQueryTerm', 'wordCount', 'ui_x', 'PreferredTerm_x',
'SemanticType_x', 'Unnamed: 0', 'Unnamed: 0.1', 'SemanticType_y',
'PreferredTerm_y', 'ui_y'
'''

# Future: Look for a better way to do the above - MERGE WITH CONDITIONAL OVERWRITE. Temporary fix:
LogAfterPastMatches['ui2'] = LogAfterPastMatches['ui_x'].where(LogAfterPastMatches['ui_x'].notnull(), LogAfterPastMatches['ui_y'])
LogAfterPastMatches['ui2'] = LogAfterPastMatches['ui_y'].where(LogAfterPastMatches['ui_y'].notnull(), LogAfterPastMatches['ui_x'])
LogAfterPastMatches['PreferredTerm2'] = LogAfterPastMatches['PreferredTerm_x'].where(LogAfterPastMatches['PreferredTerm_x'].notnull(), LogAfterPastMatches['PreferredTerm_y'])
LogAfterPastMatches['PreferredTerm2'] = LogAfterPastMatches['PreferredTerm_y'].where(LogAfterPastMatches['PreferredTerm_y'].notnull(), LogAfterPastMatches['PreferredTerm_x'])
LogAfterPastMatches['SemanticType2'] = LogAfterPastMatches['SemanticType_x'].where(LogAfterPastMatches['SemanticType_x'].notnull(), LogAfterPastMatches['SemanticType_y'])
LogAfterPastMatches['SemanticType2'] = LogAfterPastMatches['SemanticType_y'].where(LogAfterPastMatches['SemanticType_y'].notnull(), LogAfterPastMatches['SemanticType_x'])
LogAfterPastMatches.drop(['ui_x', 'ui_y', 'PreferredTerm_x', 'PreferredTerm_y', 'SemanticType_x', 'SemanticType_y'], axis=1, inplace=True)
LogAfterPastMatches.rename(columns={'ui2': 'ui', 'PreferredTerm2': 'PreferredTerm',
                                     'SemanticType2': 'SemanticType'}, inplace=True)


"""