# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import unicode_literals

import os
import sys
import glob
import time
import types
import logging
import argparse
import xml.etree.ElementTree as ET

# petrarch.py
##
# Automated event data coder
##
# SYSTEM REQUIREMENTS
# This program has been successfully run under Mac OS 10.10; it is standard Python 2.7
# so it should also run in Unix or Windows.
#
# INITIAL PROVENANCE:
# Programmers:
#             Philip A. Schrodt
#			  Parus Analytics
#			  Charlottesville, VA, 22901 U.S.A.
#			  http://eventdata.parusanalytics.com
#
#             John Beieler
#			  Caerus Associates/Penn State University
#			  Washington, DC / State College, PA, 16801 U.S.A.
#			  http://caerusassociates.com
#             http://bdss.psu.edu
#
# GitHub repository: https://github.com/openeventdata/petrarch
#
# Copyright (c) 2014	Philip A. Schrodt.	All rights reserved.
#
# This project is part of the Open Event Data Alliance tool set; earlier developments
# were funded in part by National Science Foundation grant SES-1259190
#
# This code is covered under the MIT license
#
# Report bugs to: schrodt735@gmail.com
#
# REVISION HISTORY:
# 22-Nov-13:	Initial version
# Summer-14:	Numerous modifications to handle synonyms in actor and verb dictionaries
# 20-Nov-14:	write_actor_root/text added to parse_Config
# ------------------------------------------------------------------------

import PETRglobals  # global variables
import PETRreader  # input routines
import PETRwriter
import utilities
import PETRtree


# ========================== VALIDATION FUNCTIONS ========================== #


def change_Config_Options(line):
    """Changes selected configuration options."""
    # need more robust error checking
    theoption = line['option']
    value = line['value']
    #print("<Config>: changing", theoption, "to", value)
    if theoption == 'new_actor_length':
        try:
            PETRglobals.NewActorLength = int(value)
        except ValueError:
            logger.warning(
                "<Config>: new_actor_length must be an integer; command ignored")
    elif theoption == 'require_dyad':
        PETRglobals.RequireDyad = not 'false' in value.lower()
    elif theoption == 'stop_on_error':
        PETRglobals.StoponError = not 'false' in value.lower()
    elif 'comma_' in theoption:
        try:
            cval = int(value)
        except ValueError:
            logger.warning(
                "<Config>: comma_* value must be an integer; command ignored")
            return
        if '_min' in theoption:
            PETRglobals.CommaMin = cval
        elif '_max' in theoption:
            PETRglobals.CommaMax = cval
        elif '_bmin' in theoption:
            PETRglobals.CommaBMin = cval
        elif '_bmax' in theoption:
            PETRglobals.CommaBMax = cval
        elif '_emin' in theoption:
            PETRglobals.CommaEMin = cval
        elif '_emax' in theoption:
            PETRglobals.CommaEMax = cval
        else:
            logger.warning(
                "<Config>: unrecognized option beginning with comma_; command ignored")
    # insert further options here in elif clauses as this develops; also
    # update the docs in open_validation_file():
    else:
        logger.warning("<Config>: unrecognized option")


def _check_envr(environ):
    for elem in environ:
        if elem.tag == 'Verbfile':
            PETRglobals.VerbFileName = elem.text

        if elem.tag == 'Actorfile':
            PETRglobals.ActorFileList[0] = elem.text

        if elem.tag == 'Agentfile':
            PETRglobals.AgentFileName = elem.text

        if elem.tag == 'Discardfile':
            PETRglobals.DiscardFileName = elem.text

        if elem.tag == 'Errorfile':
            print('This is deprecated. Using a different errorfile. ¯\_(ツ)_/¯')

        if elem.tag == 'Include':
            ValidInclude = elem.text.split()
            print('<Include> categories', ValidInclude)
            if 'valid' in ValidInclude:
                ValidOnly = True
                ValidInclude.remove('valid')
        else:
            ValidInclude = ''

        if elem.tag == 'Exclude':
            ValidExclude = elem.tag.split()
            print('<Exclude> categories', ValidExclude)
        else:
            ValidExclude = ''

        if elem.tag == 'Pause':
            theval = elem.text
            if 'lways' in theval:
                ValidPause = 1   # skip first char to allow upper/lower case
            elif 'ever' in theval:
                ValidPause = 2
            elif 'top' in theval:
                ValidPause = 3
            else:
                ValidPause = 0

    return ValidInclude, ValidExclude, ValidPause, ValidOnly


# ========================== PRIMARY CODING FUNCTIONS ====================== #



def check_discards(SentenceText):
    """
    Checks whether any of the discard phrases are in SentenceText, giving
    priority to the + matches. Returns [indic, match] where indic
       0 : no matches
       1 : simple match
       2 : story match [+ prefix]


    """
    sent = SentenceText.upper().split()  # case insensitive matching
    size = len(sent)
    level = PETRglobals.DiscardList
    depart_index = [0]
    discardPhrase = ""

    for i in range(len(sent)):

        if '+' in level:
            return [2, '+ ' + discardPhrase]
        elif '$' in level:
            return [1, ' ' + discardPhrase]
        elif sent[i] in level:
            # print(sent[i],SentenceText.upper(),level[sent[i]])
            depart_index.append(i)
            level = level[sent[i]]
            discardPhrase += " " + sent[i]
        else:
            if len(depart_index) == 0:
                continue
            i = depart_index[0]
            level = PETRglobals.DiscardList
    return [0, '']


def get_issues(SentenceText):
    """
    Finds the issues in SentenceText, returns as a list of [code,count]

    <14.02.28> stops coding and sets the issues to zero if it finds *any*
    ignore phrase
    """

    sent = SentenceText.upper()  # case insensitive matching
    issues = []

    for target in PETRglobals.IssueList:
        if target[0] in sent:  # found the issue phrase
            code = PETRglobals.IssueCodes[target[1]]
            if code[0] == '~':  # ignore code, so bail
                return []
            ka = 0
            gotcode = False
            while ka < len(issues):
                if code == issues[ka][0]:
                    issues[ka][1] += 1
                    break
                ka += 1
            if ka == len(issues):  # didn't find the code, so add it
                issues.append([code, 1])

    return issues


def do_validation(filepath):
    """ Unit tests using a validation file. """
    nvalid = 0

    print("Using Validation File: ", filepath)
    answers = {}
    holding = {}

    tree = ET.iterparse(filepath)
    config = {}
    for event, elem in tree:
        if elem.tag == "Config":
            config[elem.attrib['option']] = elem.attrib

        if event == "end" and elem.tag == "Sentence":
            story = elem

            # Check to make sure all the proper XML attributes are included
            attribute_check = [key in story.attrib for key in
                               ['date', 'id', 'sentence', 'source']]
            if not attribute_check:
                print('Need to properly format your XML...')
                break

            parsed_content = story.find('Parse').text
            parsed_content = utilities._format_parsed_str(
                parsed_content)

            # Get the sentence information

            if story.attrib['sentence'] == 'true':

                entry_id, sent_id = story.attrib['id'].split('-')
                parsed = story.findall('EventCoding')
                entry_id = entry_id + "" + sent_id

                #if not entry_id == "AGENTS19": # Debugging validation files
                #    continue

                if not parsed is None:
                    for item in parsed:
                        answers[(entry_id, sent_id)] = answers.setdefault(
                            (entry_id, sent_id), []) + [item.attrib]
                else:
                    print("\n", entry_id, sent_id, ":INPUT MISSING\n")
                text = story.find('Text').text
                text = text.replace('\n', '').replace('  ', '')
                sent_dict = {
                    'content': text,
                    'parsed': parsed_content,
                    'config': config.copy(),
                    'date': story.attrib['date']}
                meta_content = {'date': story.attrib['date'],
                                'source': entry_id}
                content_dict = {'sents': {sent_id: sent_dict},
                                'meta': meta_content}
                if entry_id not in holding:
                    holding[entry_id] = content_dict
                else:
                    holding[entry_id]['sents'][sent_id] = sent_dict

    updated = do_coding(holding, 'VALIDATE')

    correct = 0
    count = 0
    return
    for id, entry in sorted(updated.items()):
        count += 1
        if entry['sents'] is None:
            print("Correct:", id, "discarded\n")
            correct += 1
            continue
        for sid, sent in sorted(entry['sents'].items()):

            calc = []
            given = []
            if not 'events' in sent:
                calc += ["empty"]
            else:
                for event in sorted(sent['events']):
                    calc += [(event[0], event[1], event[2])]
            if not (id, sid) in answers:
                correct += 1
                continue
            for event in sorted(answers[(id, sid)]):
                if 'noevents' in event:
                    given += ["empty"]
                    continue
                elif 'error' in event:
                    given += ["empty"]

                    continue
                given += [(event["sourcecode"],
                           event["targetcode"],
                           event["eventcode"])]
            if sorted(given) == sorted(calc):
                correct += 1
            else:
                print(
                    "MISMATCH",
                    id,
                    sid,
                    "\nExpected:",
                    given,
                    "\nActual",
                    calc,
                    "\n")

    print("Correctly identified: ", correct, "out of", count)
    sys.exit()


def do_coding(event_dict, out_file):
    """
    Main coding loop Note that entering any character other than 'Enter' at the
    prompt will stop the program: this is deliberate.
    <14.02.28>: Bug: PETRglobals.PauseByStory actually pauses after the first
                sentence of the *next* story
    """

    treestr = ""

    NStory = 0
    NSent = 0
    NEvents = 0
    NEmpty = 0
    NDiscardSent = 0
    NDiscardStory = 0

    file = open("output.tex",'w')
    
    print("""
\\documentclass[11pt]{article}
\\usepackage{tikz-qtree}
\\usepackage{ifpdf}
\\usepackage{fullpage}
\\usepackage[landscape]{geometry}
\\ifpdf
    \\pdfcompresslevel=9
    \\usepackage[pdftex,     % sets up hyperref to use pdftex driver
            plainpages=false,   % allows page i and 1 to exist in the same document
            breaklinks=true,    % link texts can be broken at the end of line
            colorlinks=true,
            pdftitle=My Document
            pdfauthor=My Good Self
           ]{hyperref} 
    \\usepackage{thumbpdf}
\\else
    \\usepackage{graphicx}       % to include graphics
    \\usepackage{hyperref}       % to simplify the use of \href
\\fi

\\title{Petrarch Output}
\\date{}

\\begin{document}
""", file = file)


    logger = logging.getLogger('petr_log')
    times = 0
    sents = 0
    for key, val in sorted(event_dict.items()):
        NStory += 1
        prev_code = []

        SkipStory = False
        #print('\n\nProcessing {}'.format(key))
        StoryDate = event_dict[key]['meta']['date']
        StorySource = 'TEMP'

        for sent in val['sents']:
            NSent += 1
            if 'parsed' in event_dict[key]['sents'][sent]:
                if 'config' in val['sents'][sent]:
                    for id, config in event_dict[key][
                            'sents'][sent]['config'].items():
                        change_Config_Options(config)

                SentenceID = '{}_{}'.format(key, sent)
                #if not "AFP" in SentenceID:
                #    continue
                print('\tProcessing {}'.format(SentenceID))
                SentenceText = event_dict[key]['sents'][sent]['content']
                # print(SentenceText)
                SentenceDate = event_dict[key]['sents'][sent][
                    'date'] if 'date' in event_dict[key]['sents'][sent] else StoryDate
                Date = PETRreader.dstr_to_ordate(SentenceDate)
                SentenceSource = 'TEMP'

                parsed = event_dict[key]['sents'][sent]['parsed']
                treestr = parsed
                
                #if not "824_1" in SentenceID:
                #   continue

                """
                disc = check_discards(SentenceText)
                
                if disc[0] > 0:
                    if disc[0] == 1:
                        print("Discard sentence:", disc[1])
                        logger.info('\tSentence discard. {}'.format(disc[1]))
                        NDiscardSent += 1
                        continue
                    else:
                        print("Discard story:", disc[1])
                        logger.info('\tStory discard. {}'.format(disc[1]))
                        SkipStory = True
                        NDiscardStory += 1
                        break
                
                """
                
                t1 = time.time()
                test_obj = PETRtree.Sentence(treestr,SentenceText,Date)
                
                coded_events = test_obj.get_events()

                #test_obj.do_verb_analysis()
                #print(test_obj.verb_analysis)
                
                
                #test_obj.print_to_file(test_obj.tree,file = file)
                
                code_time = time.time()-t1
                del(test_obj)
                times+=code_time
                sents += 1
                print(code_time)

                if coded_events:
                    event_dict[key]['sents'][sent]['events'] = coded_events
                if coded_events and PETRglobals.IssueFileName != "":
                    event_issues = get_issues(SentenceText)
                    if event_issues:
                        event_dict[key]['sents'][sent]['issues'] = event_issues

                if PETRglobals.PauseBySentence:
                    if len(input("Press Enter to continue...")) > 0:
                        sys.exit()

                prev_code = coded_events
                NEvents += len(coded_events)
                if len(coded_events) == 0:
                    NEmpty += 1
            else:
                logger.info(
                    '{} has no parse information. Passing.'.format(SentenceID))
                pass

        if SkipStory:
            event_dict[key]['sents'] = None


    print("Summary:")
    print(
        "Stories read:",
        NStory,
        "   Sentences coded:",
        NSent,
        "  Events generated:",
        NEvents)
    print(
        "Discards:  Sentence",
        NDiscardSent,
        "  Story",
        NDiscardStory,
        "  Sentences without events:",
        NEmpty)
    print("Average Coding time = ", times/sents)
    print("\n\\end{document})",file=file)

    return event_dict





def parse_cli_args():
    """Function to parse the command-line arguments for PETRARCH."""
    __description__ = """
PETRARCH
(https://openeventdata.github.io/) (v. 0.01)
    """
    aparse = argparse.ArgumentParser(prog='petrarch',
                                     description=__description__)

    sub_parse = aparse.add_subparsers(dest='command_name')
    parse_command = sub_parse.add_parser('parse', help="""Command to run the
                                         PETRARCH parser.""",
                                         description="""Command to run the
                                         PETRARCH parser.""")
    parse_command.add_argument('-i', '--inputs',
                               help='File, or directory of files, to parse.',
                               required=True)
    parse_command.add_argument('-P', '--parsed', action='store_true',
                               default=False, help="""Whether the input
                               document contains StanfordNLP-parsed text.""")
    parse_command.add_argument('-o', '--output',
                               help='File to write parsed events.',
                               required=True)
    parse_command.add_argument('-c', '--config',
                               help="""Filepath for the PETRARCH configuration
                               file. Defaults to PETR_config.ini""",
                               required=False)

    unittest_command = sub_parse.add_parser('validate', help="""Command to run
                                         the PETRARCH validation suite.""",
                                            description="""Command to run the
                                         PETRARCH validation suite.""")
    unittest_command.add_argument('-i', '--inputs',
                                  help="""Optional file that contains the
                               validation records. If not specified, defaults
                               to the built-in PETR.UnitTest.records.txt""",
                                  required=False)

    batch_command = sub_parse.add_parser('batch', help="""Command to run a batch
                                         process from parsed files specified by
                                         an optional config file.""",
                                         description="""Command to run a batch
                                         process from parsed files specified by
                                         an optional config file.""")
    batch_command.add_argument('-c', '--config',
                               help="""Filepath for the PETRARCH configuration
                               file. Defaults to PETR_config.ini""",
                               required=False)
    args = aparse.parse_args()
    return args


def main():

    cli_args = parse_cli_args()
    utilities.init_logger('PETRARCH.log')
    logger = logging.getLogger('petr_log')

    PETRglobals.RunTimeString = time.asctime()

    if cli_args.command_name == 'validate':
        PETRreader.parse_Config(utilities._get_data('data/config/',
                                                    'PETR_config.ini'))
        read_dictionaries()
        if not cli_args.inputs:
            validation_file = utilities._get_data('data/text',
                                                  'PETR.UnitTest.records.xml')
            do_validation(validation_file)
        else:
            do_validation(cli_args.inputs)

    if cli_args.command_name == 'parse' or cli_args.command_name == 'batch':

        if cli_args.config:
            print('Using user-specified config: {}'.format(cli_args.config))
            logger.info(
                'Using user-specified config: {}'.format(cli_args.config))
            PETRreader.parse_Config(cli_args.config)
        else:
            logger.info('Using default config file.')
            PETRreader.parse_Config(utilities._get_data('data/config/',
                                                        'PETR_config.ini'))

        read_dictionaries()
        start_time = time.time()
        print('\n\n')

        if cli_args.command_name == 'parse':
            if os.path.isdir(cli_args.inputs):
                if cli_args.inputs[-1] != '/':
                    paths = glob.glob(cli_args.inputs + '/*.xml')
                else:
                    paths = glob.glob(cli_args.inputs + '*.xml')
            elif os.path.isfile(cli_args.inputs):
                paths = [cli_args.inputs]
            else:
                print(
                    '\nFatal runtime error:\n"' +
                    cli_args.inputs +
                    '" could not be located\nPlease enter a valid directory or file of source texts.')
                sys.exit()

            run(paths, cli_args.output, cli_args.parsed)

        else:
            run(PETRglobals.TextFileList, PETRglobals.EventFileName, True)

        print("Coding time:", time.time() - start_time)

    print("Finished")


def read_dictionaries(validation=False):

    if validation:
        verb_path = utilities._get_data(
            'data/dictionaries/',
            'PETR.Validate.verbs.txt')
        actor_path = utilities._get_data(
            'data/dictionaries',
            'PETR.Validate.actors.txt')
        agent_path = utilities._get_data(
            'data/dictionaries/',
            'PETR.Validate.agents.txt')
        discard_path = utilities._get_data(
            'data/dictionaries/',
            'PETR.Validate.discards.txt')
        return

    print('Verb dictionary:', PETRglobals.VerbFileName)
    verb_path = utilities._get_data(
        'data/dictionaries',
        PETRglobals.VerbFileName)

    PETRreader.read_verb_dictionary(verb_path)
    # PETRreader.show_verb_dictionary('Verbs_output.txt')

    print('Actor dictionaries:', PETRglobals.ActorFileList)
    for actdict in PETRglobals.ActorFileList:
        actor_path = utilities._get_data('data/dictionaries', actdict)
        PETRreader.read_actor_dictionary(actor_path)

    print('Agent dictionary:', PETRglobals.AgentFileName)
    agent_path = utilities._get_data('data/dictionaries',
                                     PETRglobals.AgentFileName)
    PETRreader.read_agent_dictionary(agent_path)

    print('Discard dictionary:', PETRglobals.DiscardFileName)
    discard_path = utilities._get_data('data/dictionaries',
                                       PETRglobals.DiscardFileName)
    PETRreader.read_discard_list(discard_path)

    if PETRglobals.IssueFileName != "":
        print('Issues dictionary:', PETRglobals.IssueFileName)
        issue_path = utilities._get_data('data/dictionaries',
                                         PETRglobals.IssueFileName)
        PETRreader.read_issue_list(issue_path)


def run(filepaths, out_file, s_parsed):
    events = PETRreader.read_xml_input(filepaths, s_parsed)
    if not s_parsed:
        events = utilities.stanford_parse(events)
    updated_events = do_coding(events, 'TEMP')
    PETRwriter.write_events(updated_events, out_file)


def run_pipeline(data, out_file=None, config=None, write_output=True,
                 parsed=False):
    utilities.init_logger('PETRARCH.log')
    logger = logging.getLogger('petr_log')
    if config:
        print('Using user-specified config: {}'.format(config))
        logger.info('Using user-specified config: {}'.format(config))
        PETRreader.parse_Config(config)
    else:
        logger.info('Using default config file.')
        logger.info('Config path: {}'.format(utilities._get_data('data/config/',
                                                                 'PETR_config.ini')))
        PETRreader.parse_Config(utilities._get_data('data/config/',
                                                    'PETR_config.ini'))

    read_dictionaries()

    logger.info('Hitting read events...')
    events = PETRreader.read_pipeline_input(data)
    if parsed:
        logger.info('Hitting do_coding')
        updated_events = do_coding(events, 'TEMP')
    else:
        events = utilities.stanford_parse(events)
        updated_events = do_coding(events, 'TEMP')
    if not write_output:
        output_events = PETRwriter.pipe_output(updated_events)
        return output_events
    elif write_output and not out_file:
        print('Please specify an output file...')
        logger.warning('Need an output file. ¯\_(ツ)_/¯')
        sys.exit()
    elif write_output and out_file:
        PETRwriter.write_events(updated_events, out_file)


if __name__ == '__main__':
    main()
