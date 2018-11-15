import json as sj
import argparse
import logging
from glob import glob
import os
from fnmatch import fnmatch
import configparser
from tqdm import tqdm
#import imp
import importlib
import pprint
script_dir = os.path.dirname(os.path.realpath(__file__))
try:
    spec = importlib.util.spec_from_file_location("veris_logger", script_dir + "/veris_logger.py")
    veris_logger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(veris_logger)
    # veris_logger = imp.load_source("veris_logger", script_dir + "/veris_logger.py")
except:
    print("Script dir: {0}.".format(script_dir))
    raise

cfg = {
    'log_level': 'warning',
    'log_file': None,
    'countryfile':'./all.json'
}

def getCountryCode(countryfile):
    country_codes = sj.loads(open(countryfile).read())
    country_code_remap = {'Unknown': '000000'}
    for eachCountry in country_codes:
        try:
            country_code_remap[eachCountry['alpha-2']] = \
                eachCountry['region-code']
        except:
            country_code_remap[eachCountry['alpha-2']] = "000"
        try:
            country_code_remap[eachCountry['alpha-2']] += \
                eachCountry['sub-region-code']
        except:
            country_code_remap[eachCountry['alpha-2']] += "000"
    return country_code_remap


def getField(current, txt):
    tsplit = txt.split('.', 1)
    if tsplit[0] in current:
        result = current[tsplit[0]]
        if len(tsplit) > 1:
            result = getField(result, tsplit[1])
    else:
        result = None
    return result


def grepText(incident, searchFor):
    txtFields = ['summary', "notes", "victim.notes", "actor.external.notes",
                 "actor.internal.notes", "actor.partner.notes",
                 "actor.unknown.notes", "action.malware.notes",
                 "action.hacking.notes", "action.social.notes",
                 "action.misuse.notes", "action.physical.notes",
                 "action.error.notes", "action.environmental.notes",
                 "asset.notes", "attribute.confidentiality.notes",
                 "attribute.integrity.notes", "attribute.availability.notes",
                 "impact.notes", "plus.analyst_notes", "plus.pci.notes"]
    foundAny = False
    for txtField in txtFields:
        curText = getField(incident, txtField)
        if isinstance(curText, str): # replaced basestr with str per 2to3. - GDB 181109
          if searchFor.lower() in curText:
              foundAny = True
              break
        # could be extended to look for fields in lists
    return foundAny


def main(cfg):
    veris_logger.updateLogger(cfg)
 
    pprint.pprint(cfg) # DEBUG

    logging.info("Converting files from {0} to {1}.".format(cfg["input"], cfg["output"]))
    for root, dirnames, filenames in tqdm(os.walk(cfg['input'])):
      logging.info("starting parsing of directory {0}.".format(root))
      # filenames = filter(lambda fname: fnmatch(fname, "*.json"), filenames)
      filenames = [fname for fname in filenames if fnmatch(fname, "*.json")] # per 2to3. - GDB 181109
      if filenames:
        dir_ = os.path.join(cfg['output'], root[len(cfg['input']):]) # if we don't strip the input, we get duplicate directories 
        logging.info("Output directory is {0}.".format(dir_))
        if not os.path.isdir(dir_):
            os.makedirs(dir_)
        for fname in filenames:
            in_fname = os.path.join(root,fname)
            out_fname = os.path.join(dir_, fname)

            logging.info("Now processing %s" % in_fname)
            try:
                incident = sj.loads(open(in_fname).read())
            except sj.scanner.JSONDecodeError:
                logging.warning(
                    "ERROR: %s did not parse properly. Skipping" % in_fname)
                continue

            if 'assets' not in incident.get('asset', {}):
                raise KeyError("Asset missing from assets in incident {0}.".format(fname))

            # Update the schema version
            incident['schema_version'] = "1.3.3"

            # EXAMPLE UPDATE
#             # Replace asset S - SCADA with S - ICS
#             # Issue 104, Commit f8b7387
#             # if "S - SCADA" in incident.get("asset", {}).get("assets", []):
#                 # incident["asset"]["assets"] = [e.replace("S - SCADA", "S - ICS") for e in incident["asset"]["assets"]]  
#             incident["asset"]["assets"] = [dict(e, **{u"variety": u"S - ICS"}) if e.get(u"variety", "") ==  u"S - SCADA" else e for e in incident["asset"]["assets"]] 

            # # if '3rd party desktop' or 'graphical desktop sharing' are in action.hacking.vector, add 'Desktop sharing software'
            # if "3rd party desktop" in incident.get("action", {}).get("hacking", {}).get("vector", {}) or \
            #    "Desktop sharing" in incident.get("action", {}).get("hacking", {}).get("vector", {}):
            #    incident['action']['hacking']['vector'].append("Desktop sharing software")

            # # Compress infiltrate/exfiltrate/elevate to a single
            # # Issue VERIS 157
            # for action in ["hacking", "malware", "social", "physical", "misuse", "unknown"]:
            #     if action in incident.get('action', {}):
            #         results = []
            #         for result in ['Exfiltrate', 'Infiltrate', 'Elevate']:
            #             if result in incident['action'][action]:
            #                 r = incident['action'][action].pop(result)
            #                 if r:
            #                     results.append(result)
            #         if len(results) > 0:
            #             incident['action'][action]['result'] = results

            ### Add 'bitcoin miner' to click fraud
            ## Issue VERIS 203
            if 'Click fraud' in incident.get("action", {}).get("malware", {}).get("variety", []):
                incident['action']['malware']['variety'] = ["Click fraud and cryptocurrency mining" if x == "Click fraud" else x for x in incident['action']['malware']['variety']]


            ### Remove 'plus.public_disclosure' as everything in VCDB is treated as public and everything else as private.  And it's never used.
            ## Issue VCDB 10412
            if 'public_disclosure' in incident.get('plus', {}):
                _ = incident['plus'].pop('public_disclosure')


            ### Remove 'plus.f500'.  We don't really ever fill it in and there are no questions we'd answer with it.  Plus it only applies when we know the victim.
            ## Issue VCDB 10403
            if 'f500' in incident.get('plus', {}):
                _ = incident['plus'].pop('f500')


            ### Combine plus.attribute.confidentiality.data_misuse into plus.attribute.confidentiality.data_abuse.  We rarely use data_misuse and they do not have distinct definitions.
            ## Issue VCDB 10102
            abuse_misuse_lookup = {'y': 'Yes', 'n': 'No', 'u': 'Unknown'}
            if 'data_misuse' in incident.get('plus', {}):
                misuse = incident['plus'].pop('data_misuse')
                misuse = misuse.lower()[0]
                misuse = abuse_misuse_lookup.get(misuse, 'Other')
                if 'data_abuse' in incident.get('plus', {}):
                    abuse = incident['plus']['data_abuse']
                    abuse = abuse.lower()[0]
                    abuse = abuse_misuse_lookup.get(abuse, 'Other')
                    if abuse != misuse:
                        warning("Abuse value of {0} does not match misuse value of {1}.  Defaulting to the abuse value ({0}).".format(abuse, misuse)) # TODO: handle all the values data_abuse and data_misuse are in data.  Also handle combining them when they are both set
                incident['plus']['data_abuse'] = misuse
            if 'data_abuse' in incident.get('plus', {}):
                abuse = incident['plus']['data_abuse']
                abuse = abuse.lower()[0]
                abuse = abuse_misuse_lookup.get(abuse, 'Other')
                incident['plus']['data_abuse'] = abuse


            ### Make discovery_method hierarchical
            ## Issue VERIS 168
            if 'discovery_method' in incident:
                # if incident['discovery_method'] == "Other":
                #     incident['discovery_method'] = {"other": {"note": "Other"}}
                # if incident['discovery_method'] == "Unknown":
                #     incident['discovery_method'] = {"unknown": {"note": "Unknown"}}
                if incident['discovery_method'] == "Other":
                    incident['discovery_method'] = {"other": True}
                if incident['discovery_method'] == "Unknown":
                    incident['discovery_method'] = {"unknown": True}
                else:
                    parent = {"Ext":"external", "Int": "internal", "Prt": "partner"}[incident['discovery_method'][0:3]]
                    leaf = incident['discovery_method'][6:].capitalize()
                    incident['discovery_method'] = {parent: {'variety': [leaf]}}

            ### Add hacking.exploit vuln
            ## Issue VERIS # 192
            exploit_varieties = ["Abuse of functionality", 
                       "Buffer overflow", "Cache poisoning", 
                       "Cryptanalysis", "CSRF", 
                       "Forced browsing", "Format string attack", 
                       "Fuzz testing", "HTTP request smuggling", 
                       "HTTP request splitting", "HTTP response smuggling", 
                       "HTTP Response Splitting", "Integer overflows", 
                       "LDAP injection", "Mail command injection", 
                       "MitM", "Null byte injection", 
                       "OS commanding", 
                       "Other", 
                       "Path traversal", "Reverse engineering", 
                       "RFI", "Routing detour", 
                       "Session fixation", "Session prediction", 
                       "Session replay", "Soap array abuse", 
                       "Special element injection", "SQLi", 
                       "SSI injection",
                       "URL redirector abuse",  
                       "Virtual machine escape", 
                       "XML attribute blowup", "XML entity expansion", 
                       "XML external entities", "XML injection", 
                       "XPath injection", "XQuery injection", 
                       "XSS"]
            if 'variety' in incident.get('action', {}).get('hacking', {}):
                if "Exploit vuln" not in incident['hacking']['variety'] and len(set(incident['hacking']['variety']).intersect(hak_exploit_varieties)) > 0:
                    incident['hacking']['variety'].append('Exploit vuln') 
            mal_exploit_varieties = ["Remote injection", "Web drive-by"]
            if 'variety' in incident.get('action', {}).get('malware', {}):
                if "Exploit vuln" not in incident['malware']['variety'] and len(set(incident['malware']['variety']).intersect(mal_exploit_varieties)) > 0:
                    incident['malware']['variety'].append('Exploit vuln') 


            # Now to save the incident
            logging.info("Writing new file to %s" % out_fname)
            with open(out_fname, 'w') as outfile:
                sj.dump(incident, outfile, indent=2, sort_keys=True, separators=(',', ': '))


if __name__ == '__main__':
    descriptionText = "Converts VERIS 1.3.2 incidents to v1.3.3"
    helpText = "output directory to write new files. Default is to overwrite."
    parser = argparse.ArgumentParser(description=descriptionText)
    parser.add_argument("-l","--log_level",choices=["critical","warning","info","debug"], help="Minimum logging level to display")
    parser.add_argument('--log_file', help='Location of log file')
    parser.add_argument("-i", "--input", required=True,
                        help="top level folder to search for incidents")
    parser.add_argument("-o", "--output", required=True,
                        help=helpText)
    # parser.add_argument('--countryfile', help='The json file holdering the country mapping.')
    parser.add_argument('--conf', help='The location of the config file', default="../user/data_flow.cfg")
    args = parser.parse_args()
    args = {k:v for k,v in vars(args).items() if v is not None}

    # logging_remap = {'warning':logging.WARNING, 'critical':logging.CRITICAL, 'info':logging.INFO, 'debug':logging.DEBUG} # defined above. - gdb 080716

    # Parse the config file
    try:
        config = configparser.ConfigParser()
        config.readfp(open(args["conf"]))
        cfg_key = {
            'GENERAL': ['report', 'input', 'output', 'analysis', 'year', 'force_analyst', 'version', 'database', 'check'],
            'LOGGING': ['log_level', 'log_file'],
            'REPO': ['veris', 'dbir_private'],
            'VERIS': ['mergedfile', 'enumfile', 'schemafile', 'labelsfile', 'countryfile']
        }
        for section in cfg_key.keys():
            if config.has_section(section):
                for value in cfg_key[section]:
                    if value.lower() in config.options(section):
                        cfg[value] = config.get(section, value)
        veris_logger.updateLogger(cfg)
        logging.debug("config import succeeded.")
    except Exception as e:
        logging.warning("config import failed with error {0}.".format(e))
        #raise e
        pass
    # place any unique config file parsing here
    if "input" in cfg:
        cfg["input"] = [l.strip() for l in cfg["input"].split(" ,")]  # spit to list

    cfg.update(args)

    veris_logger.updateLogger(cfg)

    # country_region = getCountryCode(cfg['countryfile'])

    # assert args.path != args.output, "Source and destination must differ"

    main(cfg)
