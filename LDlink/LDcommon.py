import boto3
import botocore
from numpy import False_
import yaml
from pymongo import MongoClient
import json
import subprocess
from bson import json_util
from collections import OrderedDict
# retrieve config
with open('config.yml', 'r') as yml_file:
    config = yaml.load(yml_file)
aws_info = config['aws']
env = config['env']
connect_external = config['database']['connect_external']
api_mongo_addr = config['database']['api_mongo_addr']
mongo_username = config['database']['mongo_user_readonly']
mongo_password = config['database']['mongo_password']
mongo_port = config['database']['mongo_port']

genome_build_vars = {
    "vars": ['grch37', 'grch38', 'grch38_high_coverage'],
    "grch37": {
        "title": "GRCh37",
        "title_hg": "hg19",
        "chromosome": "chromosome_grch37",
        "position": "position_grch37",
        "gene_begin": "begin_grch37",
        "gene_end": "end_grch37",
        "refGene": "refGene_grch37",
        "1000G_dir": "GRCh37",
        "1000G_file": "ALL.chr%s.phase3_shapeit2_mvncall_integrated_v5.20130502.genotypes.vcf.gz",
        "1000G_chr_prefix": "",
        "ldassoc_example_file": "prostate_example_grch37.txt"
    },
    "grch38": {
        "title": "GRCh38",
        "title_hg": "hg38",
        "chromosome": "chromosome_grch38",
        "position": "position_grch38",
        "gene_begin": "begin_grch38",
        "gene_end": "end_grch38",
        "refGene": "refGene_grch38",
        "1000G_dir": "GRCh38",
        "1000G_file": "ALL.chr%s.shapeit2_integrated_snvindels_v2a_27022019.GRCh38.phased.vcf.gz",
        "1000G_chr_prefix": "",
        "ldassoc_example_file": "prostate_example_grch38.txt"
    },
    "grch38_high_coverage": {
        "title": "GRCh38 High Coverage",
        "title_hg": "hg38_HC",
        "chromosome": "chromosome_grch38",
        "position": "position_grch38",
        "gene_begin": "begin_grch38",
        "gene_end": "end_grch38",
        "refGene": "refGene_grch38",
        "1000G_dir": "GRCh38_High_Coverage",
        "1000G_file": "CCDG_14151_B01_GRM_WGS_2020-08-05_chr%s.filtered.shapeit2-duohmm-phased.vcf.gz",
        "1000G_chr_prefix": "chr",
        "ldassoc_example_file": "prostate_example_grch38.txt"
    }
}

def checkS3File(aws_info, bucket, filePath):
    if ('aws_access_key_id' in aws_info and len(aws_info['aws_access_key_id']) > 0 and 'aws_secret_access_key' in aws_info and len(aws_info['aws_secret_access_key']) > 0):
        session = boto3.Session(
            aws_access_key_id=aws_info['aws_access_key_id'],
            aws_secret_access_key=aws_info['aws_secret_access_key'],
        )
        s3 = session.resource('s3')
    else: 
        s3 = boto3.resource('s3')
    try:
        s3.Object(bucket, filePath).load()
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            raise Exception("File not found in AWS S3.")
            # return False
        else:
            raise Exception("File not found in AWS S3.")
            # return False
    else: 
        return True

def retrieveAWSCredentials():
    if ('aws_access_key_id' in aws_info and len(aws_info['aws_access_key_id']) > 0 and 'aws_secret_access_key' in aws_info and len(aws_info['aws_secret_access_key']) > 0):
        export_s3_keys = "export AWS_ACCESS_KEY_ID=%s; export AWS_SECRET_ACCESS_KEY=%s;" % (aws_info['aws_access_key_id'], aws_info['aws_secret_access_key'])
    else:
        # retrieve aws credentials here
        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        export_s3_keys = "export AWS_ACCESS_KEY_ID=%s; export AWS_SECRET_ACCESS_KEY=%s; export AWS_SESSION_TOKEN=%s;" % (credentials.access_key, credentials.secret_key, credentials.token)
    return export_s3_keys

def connectMongoDBReadOnly(web):
    # Connect to 'api_mongo_addr' MongoDB endpoint if app started locally (specified in config.yml)
    if env == 'local' or connect_external:
        mongo_host = api_mongo_addr
    else: 
        mongo_host = 'localhost'
    if web:
        client = MongoClient('mongodb://' + mongo_username + ':' + mongo_password + '@' + mongo_host + '/admin', mongo_port)
    else:
        if env == 'local' or connect_external:
            client = MongoClient('mongodb://' + mongo_username + ':' + mongo_password + '@' + mongo_host + '/admin', mongo_port)
        else:
            client = MongoClient('localhost', mongo_port)
    db = client["LDLink"]
    return db

def retrieveTabix1000GData(query_file, coords, query_dir):
    export_s3_keys = retrieveAWSCredentials()
    tabix_snps = export_s3_keys + " cd {2}; tabix -fhD --separate-regions {0}{1} | grep -v -e END".format(
        query_file, coords, query_dir)
    # print("tabix_snps", tabix_snps)
    vcf = [x.decode('utf-8') for x in subprocess.Popen(tabix_snps, shell=True, stdout=subprocess.PIPE).stdout.readlines()]
    h = 0
    while vcf[h][0:2] == "##":
        h += 1
    return vcf,h

# Query genomic coordinates
def get_rsnum(db, coord, genome_build):
    temp_coord = coord.strip("chr").split(":")
    chro = temp_coord[0]
    pos = temp_coord[1]
    query_results = db.dbsnp.find({"chromosome": chro.upper() if chro == 'x' or chro == 'y' else str(chro), genome_build_vars[genome_build]['position']: str(pos)})
    query_results_sanitized = json.loads(json_util.dumps(query_results))
    return query_results_sanitized

def processCollapsedTranscript(genes_same_name):
    chrom = genes_same_name[0]["chrom"]
    txStart = genes_same_name[0]["txStart"]
    txEnd = genes_same_name[0]["txEnd"]
    exonStarts = genes_same_name[0]["exonStarts"].split(",")
    exonEnds = genes_same_name[0]["exonEnds"].split(",")
    name = genes_same_name[0]["name"]
    name2 = genes_same_name[0]["name2"]
    transcripts = [name] * len(list(filter(lambda x: x != "",genes_same_name[0]["exonStarts"].split(","))))


    for gene in genes_same_name[1:]:
        txStart = gene['txStart'] if gene['txStart'] < txStart else txStart
        txEnd = gene['txEnd'] if gene['txEnd'] > txEnd else txEnd
        exonStarts = list(filter(lambda x: x != "", gene["exonStarts"].split(","))) + exonStarts
        exonEnds = list(filter(lambda x: x != "", gene["exonEnds"].split(","))) + exonEnds
        transcripts = transcripts + ([gene['name']] * len(list(filter(lambda x: x != "", gene["exonStarts"].split(",")))))
    return {
        "chrom": chrom,
        "txStart": txStart,
        "txEnd": txEnd,
        "exonStarts": ",".join(exonStarts),
        "exonEnds": ",".join(exonEnds),
        "name2": name2,
        "transcripts": ",".join(transcripts)
    }

def getRefGene(db, filename, chromosome, begin, end, genome_build, collapseTranscript):
    query_results = db[genome_build_vars[genome_build]['refGene']].find({
        "chrom": "chr" + chromosome, 
        "$or": [
            {
                "txStart": {"$lte": int(begin)}, 
                "txEnd": {"$gte": int(end)}
            }, 
            {
                "txStart": {"$gte": int(begin)}, 
                "txEnd": {"$lte": int(end)}
            },
            {
                "txStart": {"$lte": int(begin)}, 
                "txEnd": {"$gte": int(begin), "$lte": int(end)}
            },
            {
                "txStart": {"$gte": int(begin), "$lte": int(end)}, 
                "txEnd": {"$gte": int(end)}
            }
        ]
    })
    if collapseTranscript:
        query_results_sanitized = json.loads(json_util.dumps(query_results)) 
        group_by_gene_name = {}
        for gene in query_results_sanitized:
            # new gene name
            if gene['name2'] not in group_by_gene_name:
                group_by_gene_name[gene['name2']] = []
                group_by_gene_name[gene['name2']].append(gene)
            # same gene name as another's
            else:
                group_by_gene_name[gene['name2']].append(gene)
        # print(json.dumps(group_by_gene_name, indent=4, sort_keys=True))
        query_results_sanitized = []
        for gene_name_key in group_by_gene_name.keys():
            query_results_sanitized.append(processCollapsedTranscript(group_by_gene_name[gene_name_key]))
        # print(json.dumps(query_results_sanitized, indent=4, sort_keys=True))
    else:
        query_results_sanitized = json.loads(json_util.dumps(query_results)) 
    with open(filename, "w") as f:
        for x in query_results_sanitized:
            f.write(json.dumps(x) + '\n')
    return query_results_sanitized

def getRecomb(db, filename, chromosome, begin, end, genome_build):
    recomb_results = db.recomb.find({
		genome_build_vars[genome_build]['chromosome']: str(chromosome), 
		genome_build_vars[genome_build]['position']: {
            "$gte": int(begin), 
            "$lte": int(end)
        }
	})
    recomb_results_sanitized = json.loads(json_util.dumps(recomb_results)) 

    with open(filename, "w") as f:
        for recomb_obj in recomb_results_sanitized:
            f.write(json.dumps({
                "rate": recomb_obj['rate'],
                genome_build_vars[genome_build]['position']: recomb_obj[genome_build_vars[genome_build]['position']]
            }) + '\n')
    return recomb_results_sanitized

def parse_vcf(vcf,snp_coords,ifsorted):
    delimiter = "#"
    snp_lists = str('**'.join(vcf)).split(delimiter)
    snp_dict = {}
    snp_rs_dict = {}
    missing_snp = []
    missing_rs = []    
    snp_found_list = [] 
   
    #print(vcf)
    #print(snp_lists)
    
    for snp in snp_lists[1:]:
        snp_tuple = snp.split("**")
        snp_key = snp_tuple[0].split("-")[-1].strip()
        vcf_list = [] 
        #print(snp_tuple)
        match_v = ''
        for v in snp_tuple[1:]:#choose the matched one for dup; if no matched, choose first
            if len(v) > 0:
                match_v = v
                geno = v.strip().split()
                if geno[1] == snp_key:
                    match_v = v
        if len(match_v) > 0:
            vcf_list.append(match_v)
            snp_found_list.append(snp_key)   
                
        #vcf_list.append(snp_tuple.pop()) #always use the last one, even dup
        #create snp_key as chr7:pos_rs4
        snp_dict[snp_key] = vcf_list
    
    for snp_coord in snp_coords:
        if snp_coord[-1] not in snp_found_list:
            missing_rs.append(snp_coord[0])
        else:
            s_key = "chr"+snp_coord[1]+":"+snp_coord[2]+"_"+snp_coord[0]
            snp_rs_dict[s_key] = snp_dict[snp_coord[2]]
    del snp_dict

    sorted_snp_rs = snp_rs_dict
    if ifsorted:
        sorted_snp_rs = OrderedDict(sorted(snp_rs_dict.items(),key=customsort))
    
    return sorted_snp_rs," ".join(missing_rs)

def customsort(key_snp1):
    k = key_snp1[0].split("_")[0].split(':')[1]
    k = int(k)
    return k