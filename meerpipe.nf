#!/usr/bin/env nextflow

params.help = false
if ( params.help ) {
    help = """mwa_search_pipeline.nf: A pipeline that will beamform and perform a pulsar search
             |                        in the entire FOV.
             |Observation selection options:
             |  --list_in   List of observations to process, given in a standard format.
             |              Row should include the following: pulsar,utc_obs,project_id,
             |                  band,duration,ephemeris_path,template_path
             |  --utcs      Start UTC for PSRDB search.
             |              Returns only observations after this UTC timestamp.
             |  --utce      End UTC for PSRDB search.
             |              Returns only observations before this UTC timestamp.
             |  --obs_pid   Project ID for PSRDB search.
             |              Return only observations matching this Project ID.
             |              If not provided, returns all observations.
             |  --pulsar    Pulsar name for PSRDB search.
             |              Returns only observations with this pulsar name.
             |              If not provided, returns all pulsars.
             |  --list_out  Write the list of observations submitted in a processing_jobs.csv file.
             |
             |Processing options:
             |  --use_edge_subints
             |              Use first and last 8 second subints of observation archives
             |              [default: ${params.use_edge_subints}]
             |  --fluxcal   Calibrate flux densities. Should only be done for calibrator observations
             |              [default: ${params.fluxcal}]
             |Ephemerides and template options:
             |  --ephemerides_dir
             |              Base directory of the ephermerides. Will be used to find a default ephemeris:
             |              \${ephemerides_dir}/\${project}/\${pulsar}.par
             |              [default: ${params.ephemerides_dir}]
             |  --templates_dir
             |              Base directory of the templates. Will be used to find a default templates:
             |              \${templates_dir}/\${project}/\${band}/\${pulsar}.std
             |              [default: ${params.templates_dir}]
             |  --ephemeris Path to the ephemris which will overwrite the default described above.
             |              Recomended to only be used for single observations.
             |  --template  Path to the template which will overwrite the default described above.
             |              Recomended to only be used for single observations.
             |Other arguments (optional):
             |  --out_dir   Output directory for the candidates files
             |              [default: ${params.out_dir}]
             |  -w          The Nextflow work directory. Delete the directory once the processs
             |              is finished [default: ${workDir}]""".stripMargin()
    println(help)
    exit(0)
}



process obs_list{
    label 'meerpipe'
    publishDir "./", mode: 'copy', enabled: params.list_out

    input:
    val utcs
    val utce
    val pulsar
    val obs_pid

    output:
    path "processing_jobs.csv"

    """
    #!/usr/bin/env python

    from glob import glob
    from datetime import datetime
    from joins.folded_observations import FoldedObservations
    from graphql_client import GraphQLClient
    from meerpipe.db_utils import get_pulsarname, utc_psrdb2normal, pid_getshort
    from meerpipe.archive_utils import get_obsheadinfo, get_rcvr

    # PSRDB setup
    client = GraphQLClient("${params.psrdb_url}", False)
    foldedobs = FoldedObservations(client, "${params.psrdb_url}", "${params.psrdb_token}")
    foldedobs.get_dicts = True
    foldedobs.set_use_pagination(True)

    # change blanks to nones
    if "${pulsar}" == "":
        pulsar = None
    else:
        pulsar = "${pulsar}"
    if "${obs_pid}" == "":
        obs_pid = None
    else:
        obs_pid = "${obs_pid}"

    # Also convert dates to correct format
    if "${utcs}" == "":
        utcs = None
    else:
        d = datetime.strptime("${utcs}", '%Y-%m-%d-%H:%M:%S')
        utcs = f"{d.date()}T{d.time()}+00:00"
    if "${utce}" == "":
        utce = None
    else:
        d = datetime.strptime("${utce}", '%Y-%m-%d-%H:%M:%S')
        utce = f"{d.date()}T{d.time()}+00:00"

    # Query based on provided parameters
    obs_data = foldedobs.list(
        None,
        pulsar,
        None,
        None,
        None,
        obs_pid,
        None,
        None,
        utcs,
        utce,
    )

    # Output file
    with open("processing_jobs.csv", "w") as out_file:
        for ob in obs_data:
            # Extract data from obs_data
            pulsar_obs = get_pulsarname(ob, client, "${params.psrdb_url}", "${params.psrdb_token}")
            utc_obs = utc_psrdb2normal(ob['node']['processing']['observation']['utcStart'])
            pid_obs = pid_getshort(ob['node']['processing']['observation']['project']['code'])

            # Extra data from obs header
            header_data = get_obsheadinfo(glob(f"${params.input_path}/{pulsar_obs}/{utc_obs}/*/*/obs.header")[0])
            band = get_rcvr(header_data)

            # Estimate intergration from number of archives
            nfiles = len(glob(f"${params.input_path}/{pulsar_obs}/{utc_obs}/*/*/*.ar"))

            # Grab ephermis and templates
            if "${params.ephemeris}" == "null":
                ephemeris = f"${params.ephemerides_dir}/{pid_obs}/{pulsar_obs}.par"
            else:
                ephemeris = "${params.ephemeris}"
            if "${params.template}" == "null":
                template = f"${params.templates_dir}/{pid_obs}/{band}/{pulsar_obs}.std"
            else:
                template = "${params.template}"

            # Write out results
            out_file.write(f"{pulsar_obs},{utc_obs},{pid_obs},{band},{int(nfiles*8)},{ephemeris},{template}")
    """
}


process psradd {
    label 'cpu'
    label 'psrchive'

    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path("${pulsar}_${utc}.ar")

    """
    if ${params.use_edge_subints}; then
        # Grab all archives
        archives=\$(ls ${params.input_path}/${pulsar}/${utc}/*/*/*.ar)
    else
        # Grab all archives except for the first and last one
        archives=\$(ls ${params.input_path}/${pulsar}/${utc}/*/*/*.ar | head -n-1 | tail -n+2)
    fi

    psradd -E ${ephemeris} -o ${pulsar}_${utc}.ar \${archives}
    """
}


process calibrate {
    label 'cpu'
    label 'psrchive'

    publishDir "${params.output_path}/${pulsar}/${utc}/calibrated", mode: 'copy'
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path("${pulsar}_${utc}.ar")

    """
    if ${params.use_edge_subints}; then
        # Grab all archives
        archives=\$(ls ${params.input_path}/${pulsar}/${utc}/*/*/*.ar)
    else
        # Grab all archives except for the first and last one
        archives=\$(ls ${params.input_path}/${pulsar}/${utc}/*/*/*.ar | head -n-1 | tail -n+2)
    fi

    # Calibrate the subint archives
    for ar in \$archives; do
        pac -XP -O ./ -e calib  \$ar
    done

    # Combine the calibrate archives
    psradd -E ${ephemeris} -o ${pulsar}_${utc}.ar *calib
    """
}


process meergaurd {
    label 'cpu'
    label 'coast_guard'

    publishDir "${params.output_path}/${pulsar}/${utc}/cleaned", mode: 'copy', pattern: "*_zap.ar"
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(archive)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(archive), path("${pulsar}_${utc}_zap.ar")

    """
    clean_archive.py -a ${archive} -T ${template} -o ${pulsar}_${utc}_zap.ar
    """
}


process psrplot_images {
    label 'cpu'
    label 'psrchive'

    publishDir "${params.output_path}/${pulsar}/${utc}/images", mode: 'copy', pattern: "*png"
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive)

    output:
    path "*png"

    """
    for i in "raw ${raw_archive}" "cleaned ${cleaned_archive}"; do
        set -- \$i
        type=\$1
        file=\$2
        # Do the plots for raw file then cleaned file
        psrplot -p flux -jFTDp -jC                -g 1024x768 -c above:l= -c above:c="Stokes I Profile (\${type})"     -D \${type}_profile_fts.png/png \$file
        psrplot -p Scyl -jFTD  -jC                -g 1024x768 -c above:l= -c above:c="Polarisation Profile (\${type})" -D \${type}_profile_ftp.png/png \$file
        psrplot -p freq -jTDp  -jC                -g 1024x768 -c above:l= -c above:c="Phase vs. Frequency (\${type})"  -D \${type}_phase_freq.png/png  \$file
        psrplot -p time -jFDp  -jC                -g 1024x768 -c above:l= -c above:c="Phase vs. Time (\${type})"       -D \${type}_phase_time.png/png  \$file
        psrplot -p b -x -jT -lpol=0,1 -O -c log=1 -g 1024x768 -c above:l= -c above:c="Cleaned bandpass (\${type})"     -D \${type}_bandpass.png/png    \$file
    done
    """
}


process decimate {
    label 'cpu'
    label 'psrchive'

    publishDir "${params.output_path}/${pulsar}/${utc}/decimated", mode: 'copy'
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive), path("${pulsar}_${utc}_zap.*.ar")

    """
    for nsub in ${params.time_subs.join(' ')}; do
        for nchan in ${params.freq_subs.join(' ')}; do
            pam -t \${nsub} -f \${nchan} -S -p -e \${nsub}t\${nchan}ch1p.ar ${cleaned_archive}
            pam -t \${nsub} -f \${nchan} -S -e \${nsub}t\${nchan}ch4p.ar ${cleaned_archive}
        done
    done
    """
}


process fluxcal {
    label 'cpu'
    label 'meerpipe'

    publishDir "${params.output_path}/${pulsar}/${utc}/fluxcal", mode: 'copy', pattern: "*fluxcal"
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path("${pulsar}_${utc}.fluxcal"), path("${pulsar}_${utc}_zap.fluxcal") // Replace the archives with flux calced ones

    """
    fluxcal.py -psrname ${pulsar} -obsname ${utc} -obsheader ${params.input_path}/${pulsar}/${utc}/*/*/obs.header -cleanedfile ${cleaned_archive} -rawfile ${raw_archive} -parfile ${ephemeris}
    """
}


process generate_toas {
    label 'cpu'
    label 'psrchive'

    publishDir "${params.output_path}/${pulsar}/${utc}/timing", mode: 'copy'
    time   { "${task.attempt * Integer.valueOf(dur) * 10} s" }
    memory { "${task.attempt * Integer.valueOf(dur) * 3} MB"}

    input:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive), path(decimated_archives)

    output:
    tuple val(pulsar), val(utc), val(obs_pid), val(band), val(dur), path(ephemeris), path(template), path(raw_archive), path(cleaned_archive), path(decimated_archives), path("*.tim")

    """
    # Loop over each decimated archive
    for ar in ${decimated_archives.join(' ')}; do
        # Grab archive nchan and nsub
        nchan=\$(vap -c nchan \$ar | tail -n 1 | tr -s ' ' | cut -d ' ' -f 2)
        nsub=\$( vap -c nsub  \$ar | tail -n 1 | tr -s ' ' | cut -d ' ' -f 2)
        # Grab template nchan
        tnchan=\$(vap -c nchan ${template} | tail -n 1 | tr -s ' ' | cut -d ' ' -f 2)

        # Use portrait mode if template has more frequency channels
        if [ "\$tnchan" -gt "\$nchan" ]; then
            port="-P"
        else
            port=""
        fi

        # Generate TOAs
        pat -jp \$port  -f "tempo2 IPTA" -C "chan rcvr snr length subint" -s ${template} -A FDM \$ar  > \${ar}.tim
    done
    """
}


workflow {
    // Use PSRDB to work out which obs to process
    if ( params.list_in ) {
        // Check contents of list_in
        obs_data = Channel.fromPath( params.list_in ).splitCsv()
    }
    else {
        obs_list(
            params.utcs,
            params.utce,
            params.pulsar,
            params.obs_pid,
        )
        obs_data = obs_list.out.splitCsv()
    }
    obs_data.view()

    // Combine archives and flux calibrate if option selected
    if ( params.fluxcal ) {
        obs_data_archive = calibrate( obs_data )
    }
    else {
        obs_data_archive = psradd( obs_data )
    }

    // Clean of RFI with MeerGaurd
    meergaurd( obs_data_archive )

    // Flux calibrate
    fluxcal( meergaurd.out )

    // Make psrplot images
    psrplot_images( fluxcal.out )

    // Decimate into different time and freq chunnks using pam
    decimate( fluxcal.out )

    // Generate TOAs
    generate_toas( decimate.out )

    // Summary and clean up jobs
    // generate_summary(output_dir,config_params,psrname,logger)
}


