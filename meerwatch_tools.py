#!/usr/bin/env python

"""
Code containing utilities adapted from MeerWatch codebase - /fred/oz005/users/meerpipe_dev/MeerWatch

__author__ = ["Matthew Bailes", "Renee Spiewak", "Andrew Cameron"]
__credits__ = ["Aditya Parthasarathy"]
__maintainer__ = "Andrew Cameron"
__email__ = "andrewcameron@swin.edu.au"
__status__ = "Development"
"""
# Imports
import re, os, sys
import numpy as np
from shlex import split as shplit
import subprocess as sproc
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize
import json

# calculate the rms of the toa format used in this library
# danger: assumes correct residual wrt to zero
def weighted_rms(toas):

    numerator = 0
    denominator = 0
    for x in range (0, len(toas)):

        weight = 1.0 / (toas['err'][x]**2)
        numerator += weight * (toas['res'][x]**2)
        denominator += weight

    return np.sqrt(numerator / denominator)

def weighted_mean(toas):
    numerator = 0
    demoninator = 0
    for x in range (0, len(toas)):
        weight = 1.0/ (toas['err'][x]**2)
        numerator += weight * toas['res'][x]
        demoninator += weight

    return (numerator/ demoninator)

def get_res_fromtim(tim_file, par_file, sel_file=None, out_dir="./", verb=False):

    tempo2_call = "tempo2 -nofit -set START 40000 -set FINISH 99999 "\
                  "-output general2 -s \"{{bat}} {{post}} {{err}} "\
                  "{{freq}} BLAH\n\" -nobs 1000000 -npsr 1 -f {} {}"
    awk_cmd = "awk '{print $1,$2,$3*1e-6,$4}'"
    temp_file = os.path.basename(tim_file).replace('.tim', '_res.txt')
    comp_file = os.path.basename(tim_file).replace('.tim', '_res_comp.txt')
    temp_file = os.path.join(out_dir, temp_file)
    comp_file = os.path.join(out_dir, comp_file)

    # if a select file is given, include it
    if sel_file is not None:
        tempo2_call += " -select {}".format(sel_file)

    # prep crash prevention
    cprep = "ulimit -c 0"

    # call tempo2 to produce residuals that can be read in
    with open(temp_file, 'w') as f:
        if verb:
            print("Running tempo2 command: {}".replace("\n", "\\n").format(tempo2_call.format(par_file, tim_file)))

        # re-writing to accommodate large PIPE sizes
        p1 = sproc.Popen("{}; {}".format(cprep, tempo2_call.format(par_file, tim_file)), stdout=sproc.PIPE, shell=True)
        # NOTE - shell=True is a bad idea; fix this code as soon as the tempo2 crash problem is resolved
        p1_data = p1.communicate()[0]
        p2 = sproc.Popen(shplit("grep BLAH"), stdin=sproc.PIPE,stdout=sproc.PIPE)
        p2_data = p2.communicate(input=p1_data)[0]
        p3 = sproc.Popen(shplit(awk_cmd), stdin=sproc.PIPE, stdout=f)
        p3.communicate(input=p2_data)

    if verb:
        print("Finished running tempo2")

    # load in the toa residuals
    toas = np.loadtxt(temp_file, usecols=(0, 1, 2, 3), dtype=[('mjd', 'f8'), ('res', 'f4'), ('err', 'f4'), ('freq', 'f4')])

    if toas.size == 1:
        if verb:
            print("Only one ToA from {}; skipping".format(tim_file))
        toas = np.array([])

    if len(toas) == 0:
        print("No ToAs from tempo2 for {}".format(tim_file))
    else:
        # write out the compressed residuals
        np.savetxt(comp_file, toas, fmt="%12.6f\t%.4e\t%.2e\t%9.4f")

    return(toas)


# determine outliers and remove from plot
def clean_toas(input_toas,outlier_factor=3):
    absvals = np.abs(input_toas['res'])
    mad = np.median(absvals) # this may not be the strict MAD calculation - residuals may be previously offset with regard to mean rather than median
    sigma = 1.4826 * mad
    indices = np.argwhere(absvals<=outlier_factor*sigma)
    new_toas = np.zeros(len(indices), dtype=input_toas.dtype)
    for name in input_toas.dtype.names:
        new_toas[name] = input_toas[name][indices].squeeze()
    return(new_toas)

def plot_toas_fromarr(
        toas,
        pid="unk",
        mjd=None,
        fs=14,
        out_file="toas.png",
        out_dir=None,
        sequential=True,
        title=None,
        verb=False,
        bw=856,
        cfrq=1284,
        nchn=None,
        outlier_factor=None,
    ):

    if outlier_factor is not None:
        toas = clean_toas(toas,outlier_factor=outlier_factor)
        weighted_mean_toa = weighted_mean(toas)
        for k in range (0, len(toas)):
            toas['res'][k]-=weighted_mean_toa

    if out_dir:
        out_file = os.path.join(out_dir, out_file)

    # use semi-fixed color normalisation
    f_min = cfrq-bw/2.0
    f_max = cfrq+bw/2.0
    norm = Normalize(vmin=f_min, vmax=f_max)
    # Make tupes of RGBA values for some manual error bar fixing
    y_norm = (toas['freq'] - f_min) / (f_max - f_min)
    cmap = cm.get_cmap('viridis')
    rgba_values = cmap(y_norm)
    rgba_tuples = [tuple(rgba) for rgba in rgba_values]


    fig = plt.figure(num=1)
    fig.set_size_inches(6, 4.5)
    ax = fig.gca()

    if sequential:
        if verb:
            print("Plotting serial ToAs")

        if nchn is None:
            raise(RuntimeError("Cannot get number of channels"))

        chan = range(nchn)
        freq_mins = [f_min+(i*bw/nchn) for i in chan]
        freq_maxs = [f_min+((i+1)*bw/nchn) for i in chan]
        pulse = 0
        last_chan = -1
        num = []

        for f in toas['freq']:
            for i, mi, ma in zip(chan, freq_mins, freq_maxs):
                if mi < f < ma:
                    if i <= last_chan:
                        pulse += nchn

                    num.append(pulse+i)

                    last_chan = i
                    break

        if len(num) != len(toas['freq']):
            print(num, toas['freq'], freq_mins, freq_maxs)
            raise(RuntimeError("Error determining ToA Number for {}".format(out_file)))

        xdata = np.array(num)
    else:
        if verb:
            print("Plotting against MJD")

        xdata = toas['mjd']


    scat = ax.scatter(xdata, toas['res']*1e6, s=8, c=toas['freq'], marker='s', norm=norm, cmap='viridis')
    cb = fig.colorbar(scat, ax=ax, fraction=0.1)
    ebar = ax.errorbar(xdata, toas['res']*1e6, 1e6*toas['err'], ls='', marker='', ms=1, zorder=0)
    ebar[2][0].set_color(rgba_tuples)


    print (xdata)
    spread = xdata.max()-xdata.min()
    xmin = xdata.min()-0.05*spread
    xmax = xdata.max()+0.05*spread
    ax.plot([xmin-0.1*spread, xmax+0.1*spread], [0, 0], ls='--', color='0.5')
    ax.set_xlim(xmin, xmax)

    cb.set_label("Observing frequency (MHz)", rotation=270, size=fs, labelpad=16)
    if sequential:
        ax.set_xlabel("ToA Number", fontsize=fs)
        ax.set_title("Single-observation TOAs ({0})".format(pid), fontsize=fs)
    else:
        ax.set_xlabel("MJD", fontsize=fs)

        # new - include WRMS as part of the plot
        if (len(toas) > 0):
            wrms = weighted_rms(toas)/(1e-6)
            ax.set_title("Global TOAs ({0}) | Wrms={1:.2f}$\mu$s".format(pid, wrms), fontsize=fs)
        else:
            ax.set_title("Global TOAs ({0})".format(pid), fontsize=fs)
        #ax.set_title("Global TOAs ({0})".format(pid), fontsize=fs)

        # new - add vertical line to indicate the MJD of the observation being processed
        if not ( mjd == None ):
            ax.vlines(mjd, ymin=0, ymax=1, color='red', linestyle='dotted', transform=ax.get_xaxis_transform(), zorder=1)

    ax.set_ylabel("residuals ($\mu$s)", fontsize=fs)
    if title is not None and type(title) is str:
        ax.set_title(title, fontsize=fs+2)

    plt.savefig(out_file, bbox_inches='tight')

    plt.clf()

# extract the observation-specific DM for a given set of TOAs
def get_dm_fromtim(tim_file, par_file, sel_file=None, out_dir="./", verb=False):

    if verb:
        print ("Beginning MeerWatch Tools DM measurement function...")

    # prep output file
    out_file = "DM.dat"
    out_file = os.path.join(out_dir, out_file)
    if (os.path.exists(out_file)):
        os.remove(out_file)

    # prep par file by removing DM derivatives
    dm_par_file = os.path.basename(par_file).replace('.par', '.DM.par')
    dm_par_file = os.path.join(out_dir, dm_par_file)
    if (os.path.exists(dm_par_file)):
        os.remove(dm_par_file)
    dm_deriv_start = 1
    dm_deriv_end = 9

    with open(dm_par_file, 'w') as f:
        if verb:
            print ("Creating DM-only par file {} by removing DM derivatives from {}".format(dm_par_file, par_file))

        px = sproc.Popen(shplit("cat {}".format(par_file)), stdout=sproc.PIPE)
        px_data = px.communicate()[0]
        for i in range(dm_deriv_start, dm_deriv_end + 1):
            if (i == dm_deriv_end):
                px = sproc.Popen(shplit("grep -v DM{}".format(i)), stdin=sproc.PIPE, stdout=f)
            else:
                px = sproc.Popen(shplit("grep -v DM{}".format(i)), stdin=sproc.PIPE, stdout=sproc.PIPE)
            px_data = px.communicate(input=px_data)[0]

    f.close()

    # prep tempo2 call
    dm_fit_par_file = os.path.basename(dm_par_file).replace('.par', '.fit.par')
    dm_fit_par_file = os.path.join(out_dir, dm_fit_par_file)
    if (os.path.exists(dm_fit_par_file)):
        os.remove(dm_fit_par_file)
    tempo2_call = "tempo2 -nofit -fit DM -set START 40000 -set FINISH 99999 -f {} -outpar {}".format(dm_par_file, dm_fit_par_file)

    # if a select file is given, include it
    if sel_file is not None:
        tempo2_call += " -select {}".format(sel_file)

    # add the tim file
    tempo2_call += " {}".format(tim_file)

    # prep crash prevention
    cprep = "ulimit -c 0"

    # run tempo2
    if verb:
        print ("Running DM call of tempo2.")
    pt = sproc.Popen("{}; {}".format(cprep, tempo2_call), stdout=sproc.PIPE, shell=True)
    # NOTE - shell=True is a bad idea; fix this code as soon as the tempo2 crash problem is resolved
    pt.wait()

    retval = None
    if verb:
        print ("Tempo2 complete. Analysing output...")

    # check if the output .par file exists
    if (os.path.exists(dm_fit_par_file)):

        # extract the DM values and check whether we have an error or not
        pp = sproc.Popen(shplit("cat {}".format(dm_fit_par_file)), stdout=sproc.PIPE)
        pp_data = pp.communicate()[0].decode("utf-8").split("\n")

        for line in pp_data:

            # extract DM
            if "DM" in line and not "DMEPOCH" in line and not "DM_SERIES" in line:
                vals = line.split()
                dm = float(vals[1])
                if (len(vals) > 3):
                    dm_err = float(vals[3])
                else:
                    dm_err = None

            # extract fit scores
            if "TRES" in line:
                tres = float(line.split()[1])
            if "CHI2R" in line:
                chi2 = float(line.split()[1])

            # extract epoch data
            if "START" in line:
                start = float(line.split()[1])
            if "FINISH" in line:
                finish = float(line.split()[1])
            if "DMEPOCH" in line:
                epoch = float(line.split()[1])

        # evaluate epoch and over-ride
        if 'start' in locals() and 'finish' in locals():
            epoch = (start + finish)/2
        elif 'start' in locals():
            epoch = start
        elif 'finish' in locals():
            epoch = finish
        else:
            if verb:
                print ("Unable to calculate epoch using START/FINISH fields - using DMEPOCH instead.")

        # check for valid DM
        if 'dm' in locals() and 'dm_err' in locals():
            if not (str(dm_err) == "inf" or dm_err == None):

                # write output file
                dm_fh = open(out_file, 'w')
                dm_fh.write("DM: {}\n".format(dm))
                dm_fh.write("ERR: {}\n".format(dm_err))
                dm_fh.write("EPOCH: {}\n".format(epoch))
                dm_fh.write("CHI2R: {}\n".format(chi2))
                dm_fh.write("TRES: {}\n".format(tres))
                dm_fh.close()

                if verb:
                    print ("Output DM file {} written.".format(out_file))

                # set return JSON string
                retval = json.loads(json.dumps({"dm_val": dm, "dm_err": dm_err, "epoch": epoch, "chi2r": chi2, "tres": tres}))
                if verb:
                    print ("Return JSON string formatted.")

            else:
                if verb:
                    print ("Insufficient TOAs in fit to determine a reliable DM and DM_ERR - aborting.")
        else:
            if verb:
                print ("Unable to identify DM or DM_ERR after fitting!")

    else:
        if verb:
            print ("Error fitting for DM - output fitted ephemeris file {} was not created!".format(dm_fit_par_file))

    # cleanup
    os.remove(dm_par_file)
    if (os.path.exists(dm_fit_par_file)):
        os.remove(dm_fit_par_file)

    return retval
