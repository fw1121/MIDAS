#!/usr/bin/env python

# MIDAS: Metagenomic Intra-species Diversity Analysis System
# Copyright (C) 2015 Stephen Nayfach
# Freely distributed under the GNU General Public License (GPLv3)

import sys, os, subprocess, shutil
from time import time
from midas import utility

def build_genome_db(args, species):
	""" Build FASTA and BT2 database of representative genomes """
	import Bio.SeqIO
	# fasta database
	genomes_fasta = open('/'.join([args['outdir'], 'snps/temp/genomes.fa']), 'w')
	genomes_map = open('/'.join([args['outdir'], 'snps/temp/genomes.map']), 'w')
	db_stats = {'total_length':0, 'total_seqs':0, 'species':0}
	for sp in species:
		db_stats['species'] += 1
		infile = utility.iopen(sp.rep_genome)
		for r in Bio.SeqIO.parse(infile, 'fasta'):
				genomes_fasta.write('>%s\n%s\n' % (r.id, str(r.seq).upper()))
				genomes_map.write('%s\t%s\n' % (r.id, sp.id))
				db_stats['total_length'] += len(r.seq)
				db_stats['total_seqs'] += 1
		infile.close()
	# print out database stats
	print("  total genomes: %s" % db_stats['species'])
	print("  total contigs: %s" % db_stats['total_seqs'])
	print("  total base-pairs: %s" % db_stats['total_length'])
	# bowtie2 database
	inpath = '/'.join([args['outdir'], 'snps/temp/genomes.fa'])
	outpath = '/'.join([args['outdir'], 'snps/temp/genomes'])
	command = ' '.join([args['bowtie2-build'], inpath, outpath])
	args['log'].write('command: '+command+'\n')
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	utility.check_exit_code(process, command)

def genome_align(args):
	""" Use Bowtie2 to map reads to representative genomes """
	# Bowtie2
	bam_path = os.path.join(args['outdir'], 'snps/temp/genomes.bam')
	command = '%s --no-unal ' % args['bowtie2']
	command += '-x %s ' % '/'.join([args['outdir'], 'snps/temp/genomes']) # index
	if args['max_reads']: command += '-u %s ' % args['max_reads'] # max num of reads
	if args['trim']: command += '--trim3 %s ' % args['trim'] # trim 3'
	command += '--%s ' % args['speed'] # speed/sensitivity
	command += '--threads %s ' % args['threads'] # threads
	command += '-f ' if args['file_type'] == 'fasta' else '-q ' # input type
	command += '-1 %s -2 %s '  % (args['m1'], args['m2']) if args['m2'] else '-U %s ' % args['m1'] # input reads
	# Pipe to samtools
	command += '| %s view -b - ' % args['samtools'] # convert to bam
	command += '| %s sort -f - %s ' % (args['samtools'], bam_path) # sort bam
	# Run command
	args['log'].write('command: '+command+'\n')
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	# Check for errors
	print("  finished aligning")
	print("  checking bamfile integrity")
	utility.check_exit_code(process, command)
	utility.check_bamfile(args, bam_path)

def pileup(args):
	""" Filter alignments by % id, use samtools to create pileup, filter low quality bases """
	# Stream bam, filter alignments
	command = 'python %s ' % args['stream_bam']
	command += '%s ' % os.path.join(args['outdir'], 'snps/temp/genomes.bam')
	command += '/dev/stdout '
	command += '%s ' % args['mapid']
	command += '%s ' % args['readq']
	command += '%s ' % args['mapq']
	# Pipe to mpileup
	command += '| %s mpileup '  % args['samtools']
	command += '-d 10000 ' # set max depth
	if not args['baq']: command += '-B ' # BAQ
	if args['adjust_mq']: command += '-C 50 ' # adjust MQ
	if not args['discard']: command += '-A ' # keep discordant read pairs
	command += '-Q %s ' % (args['baseq']) # base quality filtering
	command += '-f %s ' % ('%s/snps/temp/genomes.fa' % args['outdir']) # reference fna file
	command += '- ' #   input bam file
	command += '| gzip > %s ' % ('%s/snps/temp/genomes.mpileup.gz' % args['outdir']) # output file
	# Run command
	args['log'].write('command: '+command+'\n')
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	utility.check_exit_code(process, command)

def read_ref_to_species(args):
	ref_to_species = {}
	inpath = '%s/snps/temp/genomes.map' % args['outdir']
	for line in open(inpath):
		ref_id, species_id = line.rstrip().split()
		ref_to_species[ref_id] = species_id
	return ref_to_species

def split_pileup(args):
	""" Split pileup into files per-species for easy parsing """
	ref_to_species = read_ref_to_species(args)
	# open outfiles for each species_id
	outdir = '/'.join([args['outdir'], 'snps/temp/mpileup'])
	if not os.path.isdir(outdir): os.mkdir(outdir)
	outfiles = {}
	for species_id in set(ref_to_species.values()):
		outpath = '%s/%s.mpileup.gz' % (outdir, species_id)
		outfiles[species_id] = utility.iopen(outpath, 'w')
	# parse pileup into temorary files for each species_id
	pileup_path = '%s/snps/temp/genomes.mpileup.gz' % args['outdir']
	for line in utility.iopen(pileup_path):
		species_id = ref_to_species[line.split()[0]]
		outfiles[species_id].write(line)
	# close outfiles
	for file in outfiles.values():
		file.close()

def read_ref_bases(sp):
	""" Read in reference genome by position """
	import Bio.SeqIO
	ref = []
	infile = utility.iopen(sp.rep_genome)
	for rec in Bio.SeqIO.parse(infile, 'fasta'):
		for pos in range(1, len(rec.seq)+1):
			ref.append([rec.id, pos, rec.seq[pos-1].upper()])
	return sorted(ref)

def write_snp_record(outfile, snp=None, ref=None, header=False):
	""" Write record for formatted SNP file """
	fields = ['ref_id', 'ref_pos', 'ref_allele', 'alt_allele', 'ref_freq', 'depth', 'count_atcg']
	if header: # just write header
		outfile.write('\t'.join(fields)+'\n')
	elif ref: # missing snp
		snp = {'ref_id': ref[0], 'ref_pos': str(ref[1]), 'ref_allele': ref[2], 'alt_allele': 'NA',
			   'depth': 0, 'ref_freq': 0.0, 'count_atcg':'0,0,0,0'}
		record = [str(snp[field]) for field in fields]
		outfile.write('\t'.join(record)+'\n')
	else: # present snp
		record = [str(snp[field]) for field in fields]
		outfile.write('\t'.join(record)+'\n')

def format_pileup(args, species):
	""" Parse mpileups and fill in missing positions """
	import parse_pileup
	ref_to_species = read_ref_to_species(args)
	for sp in species:
		# open outfile
		outpath = '/'.join([args['outdir'], 'snps/output/%s.snps.gz' % sp.id])
		outfile = utility.iopen(outpath, 'w')
		write_snp_record(outfile, header=True)
		# read sorted reference
		ref = read_ref_bases(sp)
		ref_index = 0
		ref_length = len(ref)
		# write formatted records
		pileup_path = '/'.join([args['outdir'], 'snps/temp/mpileup/%s.mpileup.gz' % sp.id])
		pileup_file = utility.iopen(pileup_path)
		for snp in parse_pileup.main(pileup_file):
			while [snp['ref_id'], int(snp['ref_pos'])] != ref[ref_index][0:2]: # fill in missing snp positions
				write_snp_record(outfile, None, ref[ref_index]) # write missing record
				ref_index += 1
			write_snp_record(outfile, snp, None) # write present record
			ref_index += 1
		while ref_index < ref_length: # fill in trailing snps
			write_snp_record(outfile, None, ref[ref_index]) # write trailing record
			ref_index += 1
		pileup_file.close()
	shutil.rmtree('%s/snps/temp/mpileup' % args['outdir'])

def snps_summary(args):
	""" Get summary of mapping statistics """
	# store stats
	stats = {}
	ref_to_species = read_ref_to_species(args)
	for species_id in set(ref_to_species.values()):
		genome_length, covered_bases, total_depth, maf = [0,0,0,0]
		for r in utility.parse_file('/'.join([args['outdir'], 'snps/output/%s.snps.gz' % species_id])):
			genome_length += 1
			depth = int(r['depth'])
			if depth > 0:
				covered_bases += 1
				total_depth += depth
				ref_freq = float(r['ref_freq'])
				maf += ref_freq if ref_freq <= 0.5 else 1 - ref_freq
		fraction_covered = covered_bases/float(genome_length)
		mean_coverage = total_depth/float(covered_bases) if covered_bases > 0 else 0
		stats[species_id] = {'genome_length':genome_length, 'covered_bases':covered_bases,
							 'fraction_covered':fraction_covered,'mean_coverage':mean_coverage}
	# write stats
	fields = ['genome_length', 'covered_bases', 'fraction_covered', 'mean_coverage']
	outfile = open('/'.join([args['outdir'], 'snps/summary.txt']), 'w')
	outfile.write('\t'.join(['species_id'] + fields)+'\n')
	for species_id in stats:
		record = [species_id] + [str(stats[species_id][field]) for field in fields]
		outfile.write('\t'.join(record)+'\n')

def remove_tmp(args):
	""" Remove specified temporary files """
	shutil.rmtree('/'.join([args['outdir'], 'snps/temp']))

class Species:
	""" Base class for species """
	def __init__(self, id):
		self.id = id
		
	def init_ref_db(self, ref_db):
		for ext in ['', '.gz']:
			inpath = '%s/rep_genomes/%s/genome.fna%s' % (ref_db, self.id, ext)
			if os.path.isfile(inpath): self.rep_genome = inpath

def initialize_species(args):
	species = []
	splist = '%s/snps/species.txt' % args['outdir']
	if args['build_db']:
		from midas.run.species import select_species
		with open(splist, 'w') as outfile:
			for id in select_species(args):
				species.append(Species(id))
				outfile.write(id+'\n')
	elif os.path.isfile(splist):
		for line in open(splist):
			species.append(Species(line.rstrip()))
	for sp in species:
		sp.init_ref_db(args['db'])
	return species

def run_pipeline(args):
	""" Run entire pipeline """
	
	# Initialize species
	species = initialize_species(args)

	# Build genome database for selected species
	if args['build_db']:
		print("\nBuilding database of representative genomes")
		args['log'].write("\nBuilding database of representative genomes\n")
		start = time()
		build_genome_db(args, species)
		print("  %s minutes" % round((time() - start)/60, 2) )
		print("  %s Gb maximum memory" % utility.max_mem_usage())

	# Use bowtie2 to map reads to a representative genome for each species
	if args['align']:
		args['file_type'] = utility.auto_detect_file_type(args['m1'])
		print("\nMapping reads to representative genomes")
		args['log'].write("\nMapping reads to representative genomes\n")
		start = time()
		genome_align(args)
		print("  %s minutes" % round((time() - start)/60, 2) )
		print("  %s Gb maximum memory" % utility.max_mem_usage())

	# Use mpileup to identify SNPs
	if args['call']:
		start = time()
		print("\nRunning mpileup")
		args['log'].write("\nRunning mpileup\n")
		pileup(args)
		print("  %s minutes" % round((time() - start)/60, 2) )
		print("  %s Gb maximum memory" % utility.max_mem_usage())

	# Split pileup into files for each species, format, and report summary statistics
		print("\nFormatting output")
		args['log'].write("\nFormatting output\n")
		split_pileup(args)
		format_pileup(args, species)
		snps_summary(args)
		print("  %s minutes" % round((time() - start)/60, 2) )
		print("  %s Gb maximum memory" % utility.max_mem_usage())

	# Optionally remove temporary files
	if args['remove_temp']: remove_tmp(args)

