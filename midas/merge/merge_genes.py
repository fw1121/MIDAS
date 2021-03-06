#!/usr/bin/env python

# MIDAS: Metagenomic Intra-species Diversity Analysis System
# Copyright (C) 2015 Stephen Nayfach
# Freely distributed under the GNU General Public License (GPLv3)

import argparse, sys, os, gzip
from collections import defaultdict
from midas import utility
from midas.merge import merge

def build_gene_matrices(species_id, samples, args):
	""" Compute gene copy numbers for samples """
	for sample in samples:
		sample.genes = {}
		for type in ['presabs', 'copynum', 'depth']:
			sample.genes[type] = defaultdict(float)
		inpath = '%s/genes/output/%s.genes.gz' % (sample.dir, species_id)
		for r in utility.parse_file(inpath):
			if 'ref_id' in r: r['gene_id'] = r['ref_id'] # fix old fields if present
			if 'normalized_coverage' in r: r['copy_number'] = r['normalized_coverage'] 
			if 'raw_coverage' in r: r['coverage'] = r['raw_coverage']
			gene_id = r['gene_id']
			sample.genes['copynum'][gene_id] += float(r['copy_number'])
			sample.genes['depth'][gene_id] += float(r['coverage'])
	for sample in samples:
		for gene_id, copynum in sample.genes['copynum'].items():
			if copynum >= args['min_copy']: sample.genes['presabs'][gene_id] = 1
			else: sample.genes['presabs'][gene_id] = 0

def write_gene_matrices(species_id, samples, args):
	""" Compute pangenome matrices to file """
	# open outfiles
	outfiles = {}
	for type in ['presabs', 'copynum', 'depth']:
		outfiles[type] = open('%s/%s/genes_%s.txt' % (args['outdir'], species_id, type), 'w')
		outfiles[type].write('\t'.join(['gene_id'] + [s.id for s in samples])+'\n')
	# write values
	genes = sorted(samples[0].genes['depth'])
	for gene_id in genes:
		for type in ['presabs', 'copynum', 'depth']:
			outfiles[type].write(gene_id)
			for sample in samples:
				outfiles[type].write('\t%s' % str(sample.genes[type][gene_id]))
			outfiles[type].write('\n')
	for outfile in outfiles.values():
		outfile.close()

def write_readme(args, sp):
	outfile = open('%s/%s/README' % (args['outdir'], sp.id), 'w')
	outfile.write("""
Description of output files and file formats from 'merge_midas.py genes'

Output files
############
genes_depth.txt  
  average-read depth of each gene per sample
genes_copynum.txt
  copy-number of each gene per sample
  estimated by dividing the read-depth of a gene by the median read-depth of 15 universal single copy genes
genes_presabs.txt  
  the presence (1) or absence (0) of each gene per sample
  estimated by applying a threshold to gene copy-number values
genes_summary.txt
  alignment summary statistics per sample

Output formats
############
genes_depth.txt, genes_copynum.txt, genes_presabs.txt
  tab-delimited matrix files
  field names are sample ids
  row names are gene ids
genes_summary.txt
  sample_id: sample identifier
  pangenome_size: number of non-redundant genes in reference pan-genome
  covered_genes: number of genes with at least 1 mapped read
  fraction_covered: proportion of genes with at least 1 mapped read
  mean_coverage: average read-depth across genes with at least 1 mapped read
  marker_coverage: median read-depth across 15 universal single copy genes


Additional information for species can be found in the reference database:
 %s/pan_genomes/%s
""" % (args['db'], sp.id) )
	outfile.close()

def run_pipeline(args):

	print("Identifying species")
	species = merge.select_species(args, type='genes')

	for sp in species:

		print("Merging: %s for %s samples" % (sp.id, len(sp.samples)))
		outdir = os.path.join(args['outdir'], sp.id)
		if not os.path.isdir(outdir): os.mkdir(outdir)
			
		print("  building pangenome matrices")
		build_gene_matrices(sp.id, sp.samples, args)
		write_gene_matrices(sp.id, sp.samples, args)

		print("  writing summary statistics")
		merge.write_summary_stats(sp.id, sp.samples, args, 'genes')

		write_readme(args, sp)
		
		print("")


