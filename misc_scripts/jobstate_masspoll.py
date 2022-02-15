#!/usr/bin/env python
"""

Code to collate processing entries reporting a certain job status

__author__ = "Andrew Cameron"
__copyright__ = "Copyright (C) 2022 Andrew Cameron"
__license__ = "Public Domain"
__version__ = "0.1"
__maintainer__ = "Andrew Cameron"
__email__ = "andrewcameron@swin.edu.au"
__status__ = "Development"
"""

# Import packages
import os,sys
import argparse
import json
import subprocess
import numpy as np

# PSRDB imports
from tables import *
from graphql_client import GraphQLClient
from db_utils import (check_response, check_pipeline, get_pulsar_id, get_observation_target_id, check_pulsar_target,
                      get_job_state, get_target_name, utc_psrdb2normal, get_observation_utc)

# Important paths
PSRDB = "psrdb.py"

# Argument parsing
parser = argparse.ArgumentParser(description="Reports the job state of all processings matching the specified criteria.")
parser.add_argument("-outdir", dest="outdir", help="Directory in which to store the output fle", default=None)
parser.add_argument("-outfile", dest="outfile", type=str, help="File in which to store the recalled results.", default=None)
parser.add_argument("-state", dest="state", type=str, help="Return processings matching this state.", default = None)
parser.add_argument("-pipe_id", dest="pipe_id", type=int, help="Return only those processings matching this pipeline ID.", default=None)
parser.add_argument("-parent_id", dest="parent_id", type=int, help="Return only those processings matching this parent pipeline ID.", default=None)
parser.add_argument("-psr", dest="pulsar", type=str, help="Return only those processings matching this PSR J-name.", default=None)
args = parser.parse_args()


# -- MAIN PROGRAM --

# PSRDB setup
env_query = 'echo $PSRDB_TOKEN'
token = str(subprocess.check_output(env_query, shell=True).decode("utf-8")).rstrip()
env_query = 'echo $PSRDB_URL'
url = str(subprocess.check_output(env_query, shell=True).decode("utf-8")).rstrip()
client = GraphQLClient(url, False)

# check the outpath
if not (args.outdir == None or args.outfile == None):
    if not (os.path.isdir(args.outdir)):
        os.makedirs(args.outdir)

# input verification
if not (args.pipe_id == None):
    if not(check_pipeline(args.pipe_id, client, url, token)):
        raise Exception("Invalid pipeline ID specified - aborting.")

if not (args.parent_id == None):
    if not(check_pipeline(args.parent_id, client, url, token)):
        raise Exception("Invalid parent pipeline ID specified - aborting.")

if not (args.pulsar == None):
    pulsar_id = get_pulsar_id(args.pulsar, client, url, token)
    if (pulsar_id == None):
        raise Exception("Pulsar J-name not found in the database - aborting.")

# query and return all processings matching the specified parameters

processings = Processings(client, url, token)
processings.set_field_names(True, False)
processings.get_dicts = True
processings.set_use_pagination(True)

print ("Compiling raw list of processing entries...")
proc_data = processings.list(None, None, args.parent_id, None, None)
print ("Raw data compiled - {0} processing entries found".format(len(proc_data)))

results_list = []

# nothing do to but scroll

for x in range(0, len(proc_data)):

    proc_entry = proc_data[x]['node']
    proc_id = processings.decode_id(proc_entry['id'])

    # check if the job state matches
    job_state_json = get_job_state(proc_id, client, url, token)
    if "job_state" in job_state_json.keys():
        job_state = job_state_json['job_state']
    else:
        job_state = None

    if not (args.state == None):
        if not (job_state == args.state):
            continue

    # check if the pipeline matches
    proc_pipe_id = int(processings.decode_id(proc_entry['pipeline']['id']))
    if not (args.pipe_id == None):
        if not (args.pipe_id == proc_pipe_id):
            continue

    # check if the pulsar name matches
    obs_id = int(processings.decode_id(proc_entry['observation']['id']))
    target_id = get_observation_target_id(obs_id, client, url, token)
    if not (args.pulsar == None or pulsar_id == None):
        if not (check_pulsar_target(pulsar_id, target_id, client, url, token)):
            continue

    # if we have survived this far, we have a match
    # collect the output info and add to the results list
    target_name = get_target_name(target_id, client, url, token)
    obs_utc = utc_psrdb2normal(get_observation_utc(obs_id, client, url, token))
    results_list.append([proc_id, target_name, obs_id, obs_utc, job_state])

# write the results to file, if there are any

if (len(results_list) > 0):

    header = "# ProcID Target ObsID ObsUTC JobState"
    arr = results_list

    # check file or screen output
    if not (args.outfile == None):
        if not (args.outdir == None):
            outpath = os.path.join(args.outdir, args.outfile)
        else:
            outpath = args.outfile

        outfile = open(outpath, "w")
        outfile.write("{0}\n".format(header))
        for x in range(0, len(arr)):
            outfile.write("{0}\t{1}\t{2}\t{3}\t{4}\n".format(arr[x][0], arr[x][1], arr[x][2], arr[x][3], arr[x][4]))
        outfile.close()
        print("{0} matching processing entries written to {1}.".format(len(arr), outpath))
    else:
        print (header)
        for x in range(0, len(arr)):
            print ("{0}\t{1}\t{2}\t{3}\t{4}".format(arr[x][0], arr[x][1], arr[x][2], arr[x][3], arr[x][4]))
        print("{0} matching processing entries found.".format(len(arr)))

else:
    
    print ("No processing entries found matching the specified criteria - please try again.")
