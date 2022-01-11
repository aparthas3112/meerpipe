#!/usr/bin/env python
"""
MeerPipe: Processing pipeline for pulsar timing data - TPAPUM TIMING EDITION

__author__ = "Aditya Parthasarathy"
__copyright__ = "Copyright 2021, TRAPUM/MGPS"
__license__ = "Public Domain"
__version__ = "0.1"
__maintainer__ = "Aditya Parthasarathy"
__email__ = "adityapartha3112@gmail.com"
__status__ = "Development"

"""

"""
Contains routines that help initialize the pipeline. 
"""

import os,sys,shlex,subprocess,argparse,logging,glob
import numpy as np
from shutil import copyfile, rmtree


def get_obsinfo(obsinfo_path):
    """
    Parse the obs_info.dat file and return important parameters
    """
    params={}
    with open(obsinfo_path) as file:
        lines=file.readlines()
        for line in lines:
            (key, val) = line.split(";")
            params[str(key)] = str(val).rstrip()

    file.close()
    return params

def get_pid_dir(pid):
    #Routine to return a readable PID directory for the pipeline

    if pid == "SCI-20180516-MB-01":
        pid_dir = "MB01"
    elif pid == "SCI-20180516-MB-02":
        pid_dir = "TPA"
    elif pid == "SCI-20180516-MB-03":
        pid_dir = "RelBin"
    elif pid == "SCI-20180516-MB-04":
        pid_dir = "GC"
    elif pid == "SCI-20180516-MB-05":
        pid_dir = "PTA"
    elif pid == "SCI-20180516-MB-06":
        pid_dir = "NGC6440"
    elif pid == "SCI-20180516-MB-99":
        pid_dir = "fluxcal"
    elif pid == "None":
        pid_dir = "None"
    else:
        pid_dir = "Rogue"

    return pid_dir


def parse_config(path_cfile):
    """
    INPUT: Path to the configuration file
    """
    
    config_params = {}
    with open (str(path_cfile)) as cfile:
        for line in cfile.readlines():
            sline = line.split("=")
            attr = (sline[0].rstrip())
            if attr == 'input_path':
                config_params["input_path"] = sline[1].rstrip().lstrip(' ')
            if attr == 'output_path':
                config_params["output_path"] = sline[1].rstrip().lstrip(' ')
            if attr == "user":
                config_params["user"] = sline[1].rstrip().lstrip(' ')
            if attr == "rm_cat":
                config_params["rmcat"] = sline[1].rstrip().lstrip(' ')
            if attr == "dm_cat":
                config_params["dmcat"] = sline[1].rstrip().lstrip(' ')
            if attr == "decimation_products":
                config_params["decimation_products"] = sline[1].rstrip().lstrip(' ')
            if attr == "overwrite":
                config_params["overwrite"] = sline[1].rstrip().lstrip(' ')
            if attr == "meertime_ephemerides":
                config_params["meertime_ephemerides"] = sline[1].rstrip().lstrip()
            if attr == "meertime_templates":
                config_params["meertime_templates"] = sline[1].rstrip().lstrip()

    cfile.close()
    
    return config_params


def setup_logging(path):
    """
    Setup log handler - this logs in the terminal (if not run with --slurm).
    For slurm based runs - the logging is done by the job queue system

    """
    # create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    #Create console handler with a lower log level (INFO)
    logfile = "meerpipe_trap_mgps.log"
    logger = logging.getLogger(logfile)
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(ch)
    logger.info("Verbose mode enabled")
    log_toggle=True
        
    return logger



def get_outputinfo(cparams,pulsar_dirs,logger):
    """
    Routine to gather information about the directory structure from the input data
    """
    
    output_path = cparams["output_path"]
    logger.info("Gathering directory structure information")
    
    results_path=[]
    all_archives=[]
    psrnames=[]
    observations = []
    proposal_ids = []
    required_ram_list = []
    obs_time_list = []


    #DIRECTORY STRUCTURE (telescope/project/pulsar/utc/cfreq)
    for pulsar in pulsar_dirs:

        path,cfreq = os.path.split(pulsar)
        path,utc = os.path.split(path)
        path,psrname = os.path.split(path)
        path,pid = os.path.split(path)
        path,telescope = os.path.split(path)
        input_path = path

        for observation in observation_dirs:
            obs_path,obs_name = os.path.split(observation)
            beam_dirs = sorted(glob.glob(os.path.join(observation,"*")))
            for beam in beam_dirs:
                beam_path,beam_name = os.path.split(beam)
                freq_dirs = sorted(glob.glob(os.path.join(beam,"*")))
                logger.info("{0}".format(freq_dirs))
                for files in freq_dirs:
                    freq_path,freq_name = os.path.split(files)
                    archives = sorted(glob.glob(os.path.join(files,"*.ar")))
                    info_params = get_obsinfo(glob.glob(os.path.join(files,"obs_info.dat"))[0])
                    if not "pid" in cparams:
                        pid_dir = get_pid_dir(info_params["proposal_id"])
                        proposal_ids.append(str(pid_dir))
                        results_path.append(str(output_path+"/"+pid_dir+"/"+psr_name+"/"+obs_name+"/"+beam_name+"/"+freq_name+"/"))
                    elif "pid" in cparams:
                        pid_dir = str(cparams["pid"])
                        proposal_ids.append(pid_dir)
                        results_path.append(str(output_path+"/"+pid_dir+"/"+psr_name+"/"+obs_name+"/"+beam_name+"/"+freq_name+"/"))
                    psrnames.append(psr_name)
                    all_archives.append(archives)

                    #Computing RAM requirements for this observation
                    if float(info_params["target_duration"]) <= 900.0: #Less than 15 mins
                        reqram = "64g"
                    elif float(info_params["target_duration"]) > 900.0 and float(info_params["target_duration"]) <= 3600.0: #15 mins to 1 hour
                        reqram = "128g"
                    elif float(info_params["target_duration"]) > 3600.0 and float(info_params["target_duration"]) <= 10800.0: #1 to 3 hours
                        reqram = "256g"
                    elif float(info_params["target_duration"]) > 10800.0 and float(info_params["target_duration"]) < 18000.0: #3 hours to 5 hours
                        reqram = "512g"
                    elif float(info_params["target_duration"]) > 18000.0: #More than 5 hours
                        reqram = "768g"
         
                    obs_time_list.append(info_params["target_duration"])
                    required_ram_list.append(reqram)

return results_path,all_archives,psrnames,proposal_ids,required_ram_list,obs_time_list


def create_structure(output_dir,cparams,psrname,logger):
    """
    Routine to create an output directory structure as decided by get_directoryinfo.
    Creates a "cleaned", "calibrated" and a "timing" directory in each output path.

    Now includes a "scintillation" directory. 
    """
    output_path = cparams["output_path"]
    flags = cparams["flags"]
    if 'overwrite' in cparams.keys():
        overwrite_flag = str(cparams["overwrite"])
    else:
        overwrite_flag = "False"

    logger.info("Creating the directory structure for {0}".format(psrname))
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    cleaned_dir = os.path.join(output_dir,"cleaned")
    calibrated_dir = os.path.join(output_dir,"calibrated")
    timing_dir = os.path.join(output_dir,"timing")
    decimated_dir = os.path.join(output_dir,"decimated")
    scintillation_dir = os.path.join(output_dir,"scintillation")

    if cparams["type"] == "caspsr":
        #Creating the Project ID directory
        project_dir = os.path.join(output_path,str(cparams["pid"]))
        #NOTE: Pulsar directory is the main directory containing the global par and tim files and the processed obs directories.
        pulsar_dir = os.path.join(project_dir,psrname)
    elif cparams["type"] == "meertime":
        pulsar_dir = output_dir
        project_dir = output_dir
    elif cparams["type"] == "ppta_zap":
        pulsar_dir = output_dir
        project_dir = output_dir
        
    #Head pulsar directory
    if not os.path.exists(pulsar_dir):
        logger.info("Pulsar directory created")
        os.makedirs(pulsar_dir)
    else:
        logger.info("Pulsar directory exists")
        if overwrite_flag == "True":
            rmtree(pulsar_dir)
            logger.info("Pulsar head directory overwritten")
            os.makedirs(pulsar_dir)

    if not os.path.exists(cleaned_dir):
        logger.info("Cleaned directory created")
        os.makedirs(cleaned_dir)
    else:
        logger.info("Cleaned directory exists")

    if not cparams["fluxcal"]:
        if not os.path.exists(calibrated_dir):
            logger.info("Calibrated directory created")
            os.makedirs(calibrated_dir)
        else:
            logger.info("Calibrated directory exists")

        if not os.path.exists(timing_dir):
            logger.info("Timing directory created")
            os.makedirs(timing_dir)
        else:
            logger.info("Timing directory exists")

        if not os.path.exists(decimated_dir):
            logger.info("Decimated directory created")
            os.makedirs(decimated_dir)
        else:
            logger.info("Decimated directory exists")

        if not os.path.exists(scintillation_dir):
            logger.info("Scintillation directory created")
            os.makedirs(scintillation_dir)
        else:
            logger.info("Scintillation directory exists")

        #if not os.path.exists(project_dir):
        #    logger.info("Project directory created")
        #    os.makedirs(project_dir)
        #else:
        #    logger.info("Project directory exists")


    if not cparams["fluxcal"]:
    
        #Pull/Update repositories
        #TODO: for now just creating directories. Have to manage_repos eventually!
        logger.info("Checking if the ephemerides and templates directory exists")
        if not cparams["meertime_ephemerides"]:
            if not os.path.exists(os.path.join(output_path,"meertime_ephemerides")):
               # logger.info("Ephemerides directory created")
                os.makedirs(os.path.join(output_path,"meertime_ephemerides"))
            else:
                logger.info("meertime_ephemeredis exists")
            ephem_dir = os.path.join(output_path,"meertime_ephemerides")
        else:
            logger.info("custom meertime_ephemerides being used. {0}".format(cparams["meertime_ephemerides"]))
            ephem_dir = str(cparams["meertime_ephemerides"])


        if not cparams["meertime_templates"]:
            if not os.path.exists(os.path.join(output_path,"meertime_templates")):
                logger.info("Templates directory created")
                os.makedirs(os.path.join(output_path,"meertime_templates"))
            else:
                logger.info("meertime_templates exists")
            template_dir = os.path.join(output_path,"meertime_templates")
        else:
            logger.info("custom meertime_templates being used. {0}".format(cparams["meertime_templates"]))
            template_dir = str(cparams["meertime_templates"])


        #Check for the pulsar epehemeris and templates and copy them to the pulsar directory
        #Copying pulsar ephemeris
        if os.path.exists(os.path.join(ephem_dir,psrname+".par")):
            logger.info("Ephemeris for {0} found".format(psrname))
            copyfile(os.path.join(ephem_dir,psrname+".par"),os.path.join(pulsar_dir,psrname+".par"))
        else:
            logger.info("Ephemeris for {0} not found. Generating new one.".format(psrname))
            psrcat = "psrcat -all -e {0}".format(psrname)
            proc = shlex.split(psrcat)
            f = open("{0}/{1}.par".format(ephem_dir,psrname),"w")
            subprocess.call(proc,stdout=f)
            logger.info("An ephemeris was generated from the psrcat database")
            copyfile(os.path.join(ephem_dir,psrname+".par"),os.path.join(pulsar_dir,psrname+".par"))

        #Copying pulsar template
        if os.path.exists(os.path.join(template_dir,psrname+".std")):
            logger.info("Template for {0} found".format(psrname))
            copyfile(os.path.join(template_dir,psrname+".std"),os.path.join(pulsar_dir,psrname+".std"))
        else:
            #TODO:Generate new template in this case
            logger.info("Template for {0} not found. Will generate one after zapping.".format(psrname))

            #sys.exit()

