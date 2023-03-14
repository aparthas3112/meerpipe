#!/usr/bin/env python

"""
Code containing utilities adapted from MeerWatch codebase - /fred/oz005/users/meerpipe_dev/MeerWatch

__author__ = ["Andrew Cameron", "Matthew Bailes", "Renee Spiewak", "Daniel Reardon"]
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
from matplotlib import colors, cm
from astropy.time import Time

# Custom imports
from binary_tools import is_binary, get_binphase

# Constants
DAYPERYEAR = 365.25

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

# calculates weighted mean of a set of toas
def weighted_mean(toas):
    numerator = 0
    demoninator = 0
    for x in range (0, len(toas)):
        weight = 1.0/ (toas['err'][x]**2)
        numerator += weight * toas['res'][x]
        demoninator += weight

    return (numerator/ demoninator)

# new - 15/11/2022 - addinging an "align" flag which will allow separately generated residuals of the same pulsar to be lined up
def get_res_fromtim(tim_file, par_file, sel_file=None, out_dir="./", verb=False, align=False):

    # WARNING - The precise format of the output residual file is critical to the
    # correct operation of the Data Portal (pulsars.org.au). Changes to this format
    # will result in pulsr/project specific TOA plots failing to generate, and may
    # result in unexpected crashes. Please liaise on any changes to the format/storage
    # of the residual files with the Data Portal maintenance team.

    if verb:
        print ("Generating residuals from provided files {} and {}...".format(par_file, tim_file))

    # prepare tempo2 call and files
    tempo2_call = "tempo2 -nofit -set START 40000 -set FINISH 99999 "\
                  "-output general2 -s \"{{bat}} {{post}} {{err}} "\
                  "{{freq}} {{post_phase}} BLAH\n\" -nobs 1000000 -npsr 1 -f {} {}"
    awk_cmd = "awk '{print $1,$2,$3*1e-6,$4,$5}'"

    temp_file = os.path.basename(tim_file).replace('.tim', '.delme')
    res_file = os.path.basename(tim_file).replace('.tim', '_res.txt')
    comp_file = os.path.basename(tim_file).replace('.tim', '_res_comp.txt')
    temp_file = os.path.join(out_dir, temp_file)
    res_file = os.path.join(out_dir, res_file)
    comp_file = os.path.join(out_dir, comp_file)

    # if a select file is given, include it
    if sel_file is not None:
        tempo2_call += " -select {}".format(sel_file)

    # if phase aligning the residuals, add the fake TOA to a modified tim file
    if (align):

        if verb:
            print("TOA alignment requested.")

        fake_str = "ALIGNFAKE"
        fake_toa = "{} 1284.0 57754.0 10 meerkat\n".format(fake_str)
        newtim_file = "{0}.{1}".format(tim_file, fake_str)

        # open the files and modify the contents, inserting fake TOA as last entry
        tim_fh = open(tim_file, 'r')
        newtim_fh = open(newtim_file, 'w')
        orig_toas = tim_fh.readlines()
        tim_fh.close()

        # copy contents
        for line in orig_toas:
            newtim_fh.write(line)
        # add fake TOA
        newtim_fh.write(fake_toa)
        newtim_fh.close()

        # reset variables for later tempo2 call
        tim_file = newtim_file

        if verb:
            print("Created temporary tim file {}".format(tim_file))

    # call tempo2 to produce residuals that can be read in
    with open(temp_file, 'w') as f:
        if verb:
            print("Running tempo2 command: {}".replace("\n", "\\n").format(tempo2_call.format(par_file, tim_file)))

        # re-writing to accommodate large PIPE sizes
        p1 = sproc.Popen(shplit(tempo2_call.format(par_file, tim_file)), stdout=sproc.PIPE)
        p1_data = p1.communicate()[0]
        p2 = sproc.Popen(shplit("grep BLAH"), stdin=sproc.PIPE,stdout=sproc.PIPE)
        p2_data = p2.communicate(input=p1_data)[0]
        p3 = sproc.Popen(shplit(awk_cmd), stdin=sproc.PIPE, stdout=f)
        p3.communicate(input=p2_data)

    f.close()

    if verb:
        print("Finished running tempo2")

    # cleanup temporary tim file if necessary
    if (align):
        if (fake_str in tim_file):
            os.remove(tim_file)
            if verb:
                print("Deleted temporary tim file {}".format(tim_file))

    # define data formats of products to be handled
    mjd_f = ('mjd','f16')
    doy_f = ('doy', 'f16')
    res_f = ('res', 'f4')
    res_phase_f = ('res_phase', 'f4')
    err_f = ('err', 'f4')
    err_phase_f = ('err_phase', 'f4')
    freq_f = ('freq', 'f8')
    binphase_f = ('binphase', 'f8')

    # load in the toa residuals and cleanup
    toas = np.loadtxt(temp_file, usecols=(0, 1, 2, 3, 4), dtype=[mjd_f, res_f, err_f, freq_f, res_phase_f])
    os.remove(temp_file)
    if verb:
        print ("Loaded ToAs from file")

    # convert data
    doys = np.zeros(len(toas), dtype=[doy_f])
    doys[doy_f[0]] = calc_doy(toas[mjd_f[0]])

    phase_errors = np.zeros(len(toas), dtype=[err_phase_f])
    phase_errors[err_phase_f[0]] = calc_err_phase(toas[res_f[0]], toas[err_f[0]], toas[res_phase_f[0]])

    # prepare binary phase if required
    bflag = False
    try:
        pars = read_par(par_file)
    except:
        print ("Unable to parse parfile ({})".format(par_file))
    else:
        if (is_binary(pars)):
            print ("Binary pulsar detected - calculating binary phases...")
            bflag = True
            binphases = np.zeros(len(toas), dtype=[binphase_f])
            binphases[binphase_f[0]] = get_binphase(toas[mjd_f[0]],pars)

    # concatenate data in the correct order
    dtype_list = [mjd_f, doy_f, res_f, res_phase_f, err_f, err_phase_f, freq_f]
    arr_list = [toas, doys, phase_errors]
    if (bflag):
        dtype_list.append(binphase_f)
        arr_list.append(binphases)

    toas_exp = np.zeros(toas.shape, dtype=dtype_list)
    for x in arr_list:
        for y in x.dtype.names:
            toas_exp[y] = x[y]

    # if alignment requested, then identify the offset of the fake residual, rotate by that amount,
    # then delete the fake residual and re-write the file
    if (align):

        # check the size of the toas and handle appropriately
        if toas.size == 1:
        
            # fake residual is the only residual - abort
            toas = np.array([])
            if verb:
                print ("Fake alignment residual is the only residual found - aborting rotation and writing blank residuals!")

        else:

            if verb:
                print("Rotating residuals to account for TOA alignment")

            # get the offset of the fake TOA - this will be the last in the list
            fake_index = toas.size - 1
            fake_phase_offset = toas[fake_index][res_phase_f[0]]

            # rotate the real residuals
            rotate_toas(toas, fake_phase_offset, verb=True)

            # delete the fake residual
            toas = np.delete(toas, fake_index, 0)

            if verb:
                print("Rotation complete.")


    # write out residual files

    if len(toas_exp) == 0:
        if verb:
            print("No ToAs from tempo2 for {}".format(tim_file))
        # echo blank residual files
        np.savetxt(res_file, toas_exp)
        np.savetxt(res_file, toas_exp)

    else:
        if verb:
            print ("Writing out {} residuals to disk...".format(len(toas_exp)))
        raw_str="%s\t%s\t%s\t%s\t%s\t%s\t%s"
        comp_str="%12.6f\t%9.6f\t%.4e\t%.4e\t%.2e\t%.2e\t%9.4f"
        if (bflag):
            raw_str = raw_str + "\t%s"
            comp_str = comp_str + "\t%.8e"
        # write out uncompressed residuals
        np.savetxt(res_file, toas_exp, fmt=raw_str)
        # write out the compressed residuals
        np.savetxt(comp_file, toas_exp, fmt=comp_str)

    if toas_exp.size == 1:
        if verb:
            print("Only one ToA from {}; setting return array to be empty".format(tim_file))
        toas_exp = np.array([])

    return(toas_exp)

# calculate day-of-year given an MJD (credit: Daniel Reardon)
def calc_doy(mjd):

    t = Time(mjd, format='mjd')
    yrs = t.jyear # observation year in J2000.0
    # return 365.2425 * (yrs % 1)
    return DAYPERYEAR * (yrs % 1) # J2000.0 in astropy.time built of year = 365.25

# calculate phase error
def calc_err_phase(res, err, res_phase):

    return (res_phase / res) * err

# new - rotate contents of an array per the specified phase offset
# modifies the copy of the toas provided - no need to return
def rotate_toas(toas, phase_offset, verb=False):

    if verb:
        print("Rotating by phase {}.".format(phase_offset))

    # scroll through entries and modify
    for x in range (0, toas.size):

        # subtract out the phase offset of the fake toa and then modulo it back to within range
        new_res_phase = toas[x]['res_phase'] - phase_offset
        if (new_res_phase > 0.5):
            new_res_phase = new_res_phase - 1.0
        elif (new_res_phase <= -0.5):
            new_res_phase = new_res_phase + 1.0

        # now redo the time offset
        new_res = (new_res_phase / toas[x]['res_phase']) * toas[x]['res']

        # reset the toa entry
        toas[x]['res_phase'] = new_res_phase
        toas[x]['res'] = new_res

    if verb:
        print("Rotation complete.")

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

def plot_toas_fromarr(toas, pid="unk", mjd=None, fs=14, out_file="toas.png", out_dir=None, sequential=True, title=None, verb=False, bw=856, cfrq=1284, nchn=None, rebase=False, outlier_factor=None):

    # new - optionally rebaseline the residuals before display to account for the new re-alignment procedures
    if rebase:
        toa_mean = np.mean(toas['res_phase'])

        # create toa copy to rotate
        toas = np.copy(toas)
        rotate_toas(toas, toa_mean, verb=True)

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

    norm = colors.Normalize(vmin=f_min, vmax=f_max)

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

    p2 = ax.scatter(xdata, toas['res']*1e6, s=8, c=toas['freq'], marker='s', norm=norm, cmap='viridis')
    cb = fig.colorbar(p2, ax=ax, fraction=0.1)

    lines = ax.errorbar(xdata, toas['res']*1e6, yerr=1e6*toas['err'], ls='', marker='', ms=1, zorder=0)[2]
    lines[0].set_color(cb.to_rgba(toas['freq']))

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
