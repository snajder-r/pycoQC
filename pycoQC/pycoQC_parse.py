# -*- coding: utf-8 -*-

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

# Standard library imports
from collections import *
from glob import glob
import warnings
import datetime

# Third party imports
import numpy as np
import pandas as pd

# Local lib import
from pycoQC.common import *

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~GLOBAL SETTINGS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

# Silence futurewarnings
warnings.filterwarnings("ignore", category=FutureWarning)

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~MAIN CLASS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
class pycoQC_parse ():

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~INIT METHOD~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
    def __init__ (self,
        summary_file:str,
        barcode_file:str="",
        bam_file:str="",
        runid_list:list=[],
        filter_calibration:bool=False,
        min_barcode_percent:float=0.1,
        verbose:bool=False,
        quiet:bool=False):
        """
        Parse Albacore sequencing_summary.txt file and clean-up the data
        * summary_file
            Path to the sequencing_summary generated by Albacore 1.0.0 + (read_fast5_basecaller.py) / Guppy 2.1.3+ (guppy_basecaller).
            One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
        * barcode_file
            Path to the barcode_file generated by Guppy 2.1.3+ (guppy_barcoder). This is not a required file.
            One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
        * bam_file
            Path to a Bam file corresponding to reads in the summary_file. Preferably aligned with Minimap2
            One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
        * runid_list
            Select only specific runids to be analysed. Can also be used to force pycoQC to order the runids for
            temporal plots, if the sequencing_summary file contain several sucessive runs. By default pycoQC analyses
            all the runids in the file and uses the runid order as defined in the file.
        * filter_calibration
            If True read flagged as calibration strand by the software are removed
        * min_barcode_percent
            Minimal percent of total reads to retain barcode label. If below the barcode value is set as `unclassified`.
        """

        # Set logging level
        self.logger = get_logger (name=__name__, verbose=verbose, quiet=quiet)
        self.logger.warning ("Initialising parser")

        # Explicit init counter
        self.counter = OrderedDict()

        # Save args to self values
        self.runid_list = runid_list
        self.filter_calibration = filter_calibration
        self.min_barcode_percent = min_barcode_percent

        # Expand file names and check files readeability
        self.summary_files_list = self._expand_file_names(summary_file)
        self.logger.debug ("\t\tSequencing summary files found: {}".format(" ".join(self.summary_files_list)))
        self.counter["Summary files found"] = len(self.summary_files_list)

        self.barcode_files_list = self._expand_file_names(barcode_file)
        self.logger.debug ("\t\tBarcode summary files found: {}".format(" ".join(self.barcode_files_list)))
        self.counter["Barcode files found"] = len(self.barcode_files_list)

        self.bam_file_list = self._expand_file_names(bam_file)
        self.logger.debug ("\t\tBam files found: {}".format(" ".join(self.bam_file_list)))
        self.counter["Bam files found"] = len(self.bam_file_list)

    def __call__ (self):
        """Parse files and clean df"""
        # Import summary, barcode and bam files and cleanup resulting df
        self.logger.warning ("Parsing input files")
        df = self._parse_summary ()
        if self.barcode_files_list:
            df = self._parse_barcode (df)
        if self.bam_file_list:
            df = self._parse_bam (df)
        df = self._clean_df (df)
        return df

    def __str__(self):
        return dict_to_str(self.counter)

    def __repr__(self):
        return "[{}]\n".format(self.__class__.__name__)

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~PRIVATE METHODS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

    def _parse_summary (self):
        """"""
        self.logger.info ("\tImporting sequencing information from sequencing summary files")
        df = self._merge_files_to_df (self.summary_files_list)

        # Define specific parameters depending on the run_type
        self.logger.info ("\tVerifying fields and discarding unused columns")

        if "sequence_length_template" in df:
            self.logger.debug ("\t\t1D Run type")
            self.run_type = "1D"
            required_colnames = ["read_id", "run_id", "channel", "start_time", "sequence_length_template", "mean_qscore_template"]
            optional_colnames = ["calibration_strand_genome_template", "barcode_arrangement"]
            rename_colmanes = {
                "sequence_length_template":"num_bases", "mean_qscore_template":"mean_qscore",
                "calibration_strand_genome_template":"calibration","barcode_arrangement":"barcode"}

        elif "sequence_length_2d" in df:
            self.logger.debug ("\t\t1D2 Run type")
            self.run_type = "1D2"
            required_colnames = ["read_id", "run_id", "channel", "start_time", "sequence_length_2d", "mean_qscore_2d"]
            optional_colnames = ["calibration_strand_genome_template", "barcode_arrangement"]
            rename_colmanes = {
                "sequence_length_2d":"num_bases", "mean_qscore_2d":"mean_qscore",
                "calibration_strand_genome_template":"calibration", "barcode_arrangement":"barcode"}
        else:
            raise pycoQCError ("Invalid sequencing summary file")

        # Verify the required and optional columns, Drop unused fields and standardise field names.
        col = self._check_df_columns (df=df, required_colnames=required_colnames, optional_colnames=optional_colnames)
        self.logger.debug ("\t\tColumns found: {}".format(col))
        df = df[col]
        df = df.rename(columns=rename_colmanes)

        # Collect stats
        n = len(df)
        self.logger.debug ("\t\t{:,} reads found in initial file".format(n))
        self.counter["Initial reads"] = n

        return df

    def _parse_barcode (self, df):
        """"""
        self.logger.info ("\tImporting barcode information from barcode summary files")
        df_b = self._merge_files_to_df (self.barcode_files_list)

        # check presence of barcode details
        if "read_id" in df_b and "barcode_arrangement" in df_b:
            self.logger.debug ("\t\tFound valid Guppy barcode file")
            df_b = df_b [["read_id", "barcode_arrangement"]]
            df_b = df_b.rename(columns={"barcode_arrangement":"barcode"})

        elif "read_ID" in df_b and "barcode_call" in df_b:
            self.logger.debug ("\t\tFound valid Deepbinner barcode file")
            df_b = df_b [["read_ID", "barcode_call"]]
            df_b = df_b.rename(columns={"read_ID":"read_id", "barcode_call":"barcode"})
        else:
            raise pycoQCError ("File {} does not contain required barcode information".format(fp))

        # Merge df and fill in missing barcode values
        df = pd.merge(df, df_b, on="read_id", how="left")
        df['barcode'].fillna('unclassified', inplace=True)
        df['barcode'].replace("none", "unclassified", inplace=True)

        n = len(df[df['barcode']!="unclassified"])
        self.logger.debug ("\t\t{:,} reads with barcodes assigned".format(n))
        self.counter["Reads with barcodes"] = n

        return df

    def _parse_bam (self, df): ################################################# TO DO
        return df

    def _clean_df (self, df):
        """"""
        # Drop lines containing NA values
        self.logger.info ("\tDiscarding lines containing NA values")
        l = len(df)
        df = df.dropna()
        n=l-len(df)
        self.logger.info ("\t\t{:,} reads discarded".format(n))
        self.counter["Reads with NA values discarded"] = n
        if len(df) <= 1:
            raise pycoQCError("No valid read left after NA values filtering")

        # Filter out zero length reads
        self.logger.info ("\tFiltering out zero length reads")
        l = len(df)
        df = df[(df["num_bases"] > 0)]
        n=l-len(df)
        self.logger.info ("\t\t{:,} reads discarded".format(n))
        self.counter["Zero length reads discarded"] = n
        if len(df) <= 1:
            raise pycoQCError("No valid read left after zero_len filtering")

        # Filter out calibration strands read if the "calibration_strand_genome_template" field is available
        if self.filter_calibration and "calibration" in df:
            self.logger.info ("\tFiltering out calibration strand reads")
            l = len(df)
            df = df[(df["calibration"].isin(["filtered_out", "no_match", "*"]))]
            n=l-len(df)
            self.logger.info ("\t\t{:,} reads discarded".format(n))
            self.counter["Calibration reads discarded"] = n
            if len(df) <= 1:
                raise pycoQCError("No valid read left after calibration strand filtering")

        # Filter and reorder based on runid_list list if passed by user
        if self.runid_list:
            self.logger.info ("\tSelecting run_ids passed by user")
            l = len(df)
            df = df[(df["run_id"].isin(self.runid_list))]
            n=l-len(df)
            self.logger.debug ("\t\t{:,} reads discarded".format(n))
            self.counter["Excluded runid reads discarded"] = n
            if len(df) <= 1:
                raise pycoQCError("No valid read left after run ID filtering")
            runid_list = self.runid_list

        # Else sort the runids by output per time assuming that the throughput decreases over time
        else:
            self.logger.info ("\tSorting run IDs by decreasing throughput")
            d = {}
            for run_id, sdf in df.groupby("run_id"):
                d[run_id] = len(sdf)/np.ptp(sdf["start_time"])
            runid_list = [i for i, j in sorted (d.items(), key=lambda t: t[1], reverse=True)]
            self.logger.info ("\t\tRun-id order {}".format(runid_list))

        # Modify start time per run ids to order them following the runid_list
        self.logger.info ("\tReordering runids")
        increment_time = 0
        runid_start = OrderedDict()
        for runid in runid_list:
            self.logger.info ("\t\tProcessing reads with Run_ID {} / time offset: {}".format(runid, increment_time))
            max_val = df['start_time'][df["run_id"] == runid].max()
            df.loc[df["run_id"] == runid, 'start_time'] += increment_time
            runid_start[runid] = increment_time
            increment_time += max_val+1
        df = df.sort_values ("start_time")

        #  Unset low frequency barcodes
        if "barcode" in df:
            self.logger.info ("\tCleaning up low frequency barcodes")
            l = (df["barcode"]=="unclassified").sum()
            barcode_counts = df["barcode"][df["barcode"]!="unclassified"].value_counts()
            cutoff = int(barcode_counts.sum()*self.min_barcode_percent/100)
            low_barcode = barcode_counts[barcode_counts<cutoff].index
            df.loc[df["barcode"].isin(low_barcode), "barcode"] = "unclassified"
            n= int((df["barcode"]=="unclassified").sum()-l)
            self.logger.info ("\t\t{:,} reads with low frequency barcode unset".format(n))
            self.counter["Reads with low frequency barcode unset"] = n

        # Reindex final df
        self.logger.info ("\tReindexing dataframe by read_ids")
        df = df.reset_index (drop=True)
        df = df.set_index ("read_id")
        self.logger.info ("\t\t{:,} Final valid reads".format(len(df)))

        # Save final df
        self.counter["Valid reads"] = len(df)
        if len(df) < 500:
            self.logger.warning ("WARNING: Low number of reads found. This is likely to lead to errors when trying to generate plots")

        return df

    #~~~~~~~~~~~~~~~~~~~~~~~~~~PRIVATE STATIC METHODS~~~~~~~~~~~~~~~~~~~~~~~~~~#

    @staticmethod
    def _check_df_columns (df, required_colnames, optional_colnames):
        """"""
        col_found = []
        # Verify the presence of the columns required for pycoQC
        for col in required_colnames:
            if col in df:
                col_found.append(col)
            else:
                raise pycoQCError("Column {} not found in the provided sequence_summary file".format(col))
        for col in optional_colnames:
            if col in df:
                col_found.append(col)
        return col_found

    @staticmethod
    def _expand_file_names (fn):
        """"""
        if not fn:
            return []

        # Try to expand file name to list
        if type(fn) == str:
            fn_list = glob (fn)
        elif type(fn) == list:
            fn_list=[]
            for fp in fn:
                fn_list.extend(glob(fp))
        else:
            raise pycoQCError ("{} has to be either a file or a regular expression or a list of files".format(fn))

        # Verify that a least 1 file was found and that files are readeable
        if len(fn_list) == 0:
            raise pycoQCError ("{} does not correspond to any valid file".format(fn))
        for fn in fn_list:
            if not is_readable_file (fn):
                raise pycoQCError("Cannot read file {}".format(fn))

        return fn_list

    @staticmethod
    def _merge_files_to_df (fn_list):
        """"""
        if len(fn_list) == 1:
            df =  pd.read_csv(fn_list[0], sep ="\t")

        else:
            df_list = []
            for fn in fn_list:
                df_list.append (pd.read_csv(fn, sep ="\t"))
            df = pd.concat(df_list, ignore_index=True, sort=False, join="inner")

        if len(df) == 0:
            raise pycoQCError ("No valid read found in input file")

        return df
