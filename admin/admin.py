#!/usr/bin/env python

import requests
import json
import time
import re

import subprocess

import argparse
import sys
import __main__
from argparse import RawTextHelpFormatter

from datetime import datetime
import hashlib
import codecs
import traceback

import os.path
import os
from prettytable import PrettyTable

from sqlalchemy import create_engine, select, func, text
from sqlalchemy import Table, Column, Integer, String, TIMESTAMP, MetaData, ForeignKey

# set configuration parameters
datastore = '/tmp/agora_elections/datastore'
shared_secret = 'hohoho'
db_user = 'agora_elections'
db_password = 'agora_elections'
db_name = 'agora_elections'
db_port = 5432
app_host = 'localhost'
app_port = 9000
node = '/usr/local/bin/node'

def get_local_hostport():
    return app_host, app_port

def votes_table():
    metadata = MetaData()
    votes = Table('vote', metadata,
        Column('id', Integer, primary_key=True),
        Column('election_id', String),
        Column('voter_id', String),
        Column('vote', String),
        Column('hash', String),
        Column('created', TIMESTAMP),
    )
    return votes

def elections_table():
    metadata = MetaData()
    elections = Table('election', metadata,
        Column('id', Integer, primary_key=True),
        Column('configuration', String),
        Column('state', String),
        Column('start_date', TIMESTAMP),
        Column('end_date', TIMESTAMP),
        Column('pks', String),
        Column('results', String),
        Column('results_updated', String)
    )
    return elections

def truncate(data):
    data = unicode(data)
    return (data[:20] + '..') if len(data) > 20 else data

def show_votes(result):
    v = PrettyTable(['id', 'election_id', 'voter_id', 'vote', 'hash', 'created'])
    v.padding_width = 1
    for row in result:
        v.add_row(map(truncate, row))
    print(v)

def show_elections(result):
    v = PrettyTable(['id', 'configuration', 'state', 'start_date', 'end_date', 'pks', 'results', 'results_updated'])
    v.padding_width = 1
    for row in result:
        v.add_row(map(truncate, row))
    print(v)

def get_max_electionid():
    conn = get_db_connection()
    elections = elections_table()
    s = select([func.max(elections.c.id)])
    result = conn.execute(s)
    return result.first()[0]

def get_db_connection():
    engine = create_engine('postgresql+psycopg2://%s:%s@localhost:%d/%s' % (db_user, db_password, db_port, db_name))
    conn = engine.connect()

    return conn

# writes the votes in the format expected by eo
def write_node_votes(votesData, filePath):
    # forms/election.py:save
    votes = []
    for vote in votesData:
        data = {
            "a": "encrypted-vote-v1",
            "proofs": [],
            "choices": [],
            "voter_username": 'foo',
            "issue_date": str(datetime.now()),
            "election_hash": {"a": "hash/sha256/value", "value": "foobar"},
        }

        q_answer = vote['question0']
        data["proofs"].append(dict(
            commitment=q_answer['commitment'],
            response=q_answer['response'],
            challenge=q_answer['challenge']
        ))
        data["choices"].append(dict(
            alpha=q_answer['alpha'],
            beta=q_answer['beta']
        ))

        votes.append(data)

    # tasks/election.py:launch_encrypted_tally
    # this is the format expected by eo, newline separated
    with codecs.open(filePath, encoding='utf-8', mode='w+') as votes_file:
        for vote in votes:
            votes_file.write(json.dumps(vote, sort_keys=True) + "\n")

''' commands '''

def register(cfg, args):

    auth = get_hmac(cfg, "register")
    host,port = get_local_hostport()
    headers = {'content-type': 'application/json', 'Authorization': auth}
    url = 'http://%s:%d/api/election' % (host, port)
    r = requests.post(url, data=json.dumps(cfg['electionConfig']), headers=headers)
    print(r.status_code, r.text)

def update(cfg, args):

    auth = get_hmac(cfg, 'update-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'content-type': 'application/json', 'Authorization': auth}
    url = 'http://%s:%d/api/election/%d' % (host, port, cfg['election_id'])
    r = requests.post(url, data=json.dumps(cfg['electionConfig']), headers=headers)
    print(r.status_code, r.text)

def create(cfg, args):

    auth = get_hmac(cfg, 'create-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/create' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def start(cfg, args):

    auth = get_hmac(cfg, 'start-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/start' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def stop(cfg, args):

    auth = get_hmac(cfg, 'stop-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/stop' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def cast_votes(cfg, args):
    ctexts = cfg['ciphertexts']
    electionId = cfg['election_id']

    if(os.path.isfile(ctexts)):
        with open(ctexts) as votes_file:
            votes = json.load(votes_file)

            voter_id = 0
            print("casting %d votes.." % len(votes))
            for vote in votes:
                vote_string = json.dumps(vote)
                vote_hash = hashlib.sha256(vote_string).hexdigest()
                vote = {
                    "election_id": cfg['election_id'],
                    "voter_id": str(voter_id),
                    "vote": json.dumps(vote),
                    "hash": vote_hash
                }

                auth = get_hmac(cfg, 'vote-%d-%d' % (cfg['election_id'], voter_id))
                host,port = get_local_hostport()
                headers = {'Authorization': auth, 'content-type': 'application/json'}
                url = 'http://%s:%d/api/election/%d/voter/%d' % (host, port, cfg['election_id'], voter_id)
                data = json.dumps(vote)
                # print("casting vote for voter %d, %s" % (voter_id, data))
                voter_id += 1
                r = requests.post(url, data=data, headers=headers)
                if r.status_code != 200:
                    print(r.status_code, r.text)

            # only show the status code for the last vote cast
            print(r.status_code, r.text)
    else:
        print("No public key or votes file, exiting..")
        exit(1)


    '''auth = get_hmac(cfg, 'admin-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/dumpVotes' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)'''

def dump_votes(cfg, args):
    auth = get_hmac(cfg, 'admin-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/dumpVotes' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def dump_pks(cfg, args):

    auth = get_hmac(cfg, 'admin-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/dumpPks' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def tally(cfg, args):

    auth = get_hmac(cfg, 'tally-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/tally' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def tally_no_dump(cfg, args):

    auth = get_hmac(cfg, 'tally-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/tally-no-dump' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def calculate_results(cfg, args):
    path = args.results_config
    if path != None and os.path.isfile(path):
        with open(path) as config_file:
            config = json.load(config_file)

            auth = get_hmac(cfg, 'results-%d' % cfg['election_id'])
            host,port = get_local_hostport()
            headers = {'Authorization': auth, 'content-type': 'application/json'}
            url = 'http://%s:%d/api/election/%d/calculate-results' % (host, port, cfg['election_id'])
            r = requests.post(url, headers=headers, data=json.dumps(config))
            print(r.status_code, r.text)
    else:
        print("no config file %s" % path)

def publish_results(cfg, args):

    auth = get_hmac(cfg, 'admin-%d' % cfg['election_id'])
    host,port = get_local_hostport()
    headers = {'Authorization': auth}
    url = 'http://%s:%d/api/election/%d/publish-results' % (host, port, cfg['election_id'])
    r = requests.post(url, headers=headers)
    print(r.status_code, r.text)

def list_votes(cfg, args):
    conn = get_db_connection()
    votes = votes_table()
    s = select([votes]).where(votes.c.election_id == cfg['election_id'])
    for filter in cfg['filters']:
        if "~" in filter:
            key, value = filter.split("~")
            s = s.where(getattr(votes.c, key).like(value))
        else:
            key, value = filter.split("==")
            s = s.where(getattr(votes.c, key) == (value))

    result = conn.execute(s)
    show_votes(result)

def list_elections(cfg, args):
    conn = get_db_connection()
    elections = elections_table()
    s = select([elections]).order_by(elections.c.id)
    for filter in cfg['filters']:
        if "~" in filter:
            key, value = filter.split("~")
            s = s.where(getattr(elections.c, key).like(value))
        else:
            key, value = filter.split("==")
            s = s.where(getattr(elections.c, key) == (value))

    result = conn.execute(s)
    show_elections(result)

def count_votes(cfg, args):
    conn = get_db_connection()
    votes = votes_table()
    s = select([func.count(votes.c.id)]).where(votes.c.election_id == cfg['election_id'])
    # result = conn.execute(text("select count(*) from vote where id in (select distinct on (voter_id) id from vote where election_id in :ids order by voter_id, election_id desc)"), ids=tuple(args.command[1:]))
    result = conn.execute(s)
    row = result.fetchall()
    print(row[0][0])

def show_column(cfg, args):
    conn = get_db_connection()
    elections = elections_table()
    s = select([elections]).where(elections.c.id == cfg['election_id'])
    result = conn.execute(s)
    for row in result:
        print(row[args.column])

def encryptNode(cfg, args):
    electionId = cfg['election_id']
    pkFile = 'pks'
    votesFile = cfg['plaintexts']
    votesCount = cfg['encrypt-count']
    ctexts = cfg['ciphertexts']

    print("> Encrypting votes (" + votesFile + ", pk = " + pkFile + ", " + str(votesCount) + ")..")
    publicPath = os.path.join(datastore, 'public', str(cfg['election_id']))
    pkPath = os.path.join(publicPath, pkFile)
    votesPath = votesFile
    ctextsPath = ctexts

    if(os.path.isfile(pkPath)) and (os.path.isfile(votesPath)):
        print("> Encrypting with %s %s %s %s %s" % (node, "js/encrypt.js", pkPath, votesPath, str(votesCount)))
        output, error = subprocess.Popen([node, "js/encrypt.js", pkPath, votesPath, str(votesCount)], stdout = subprocess.PIPE).communicate()

        print("> Received Nodejs output (" + str(len(output)) + " chars)")
        parsed = json.loads(output)

        print("> Writing file to " + ctextsPath)
        write_node_votes(parsed, ctextsPath)
    else:
        print("No public key or votes file, exiting..")
        exit(1)

# writes votes to file, in raw format (ready to submit to the ballotbox)
def encrypt(cfg, args):
    electionId = cfg['election_id']
    votesFile = cfg['plaintexts']
    votesCount = cfg['encrypt-count']
    ctextsPath = cfg['ciphertexts']

    publicPath = os.path.join(datastore, 'public', str(cfg['election_id']))
    pkPath = os.path.join(publicPath, 'pks')
    votesPath = votesFile
    print("Encrypting votes (" + votesFile + ", pk = " + pkPath + ", " + str(votesCount) + ")..")

    if(os.path.isfile(pkPath)) and (os.path.isfile(votesPath)):
        print("Encrypting with %s %s %s %s %s" % ("bash", "encrypt.sh", pkPath, votesPath, str(votesCount)))
        output, error = subprocess.Popen(["bash", "encrypt.sh", pkPath, votesPath, str(votesCount)], stdout = subprocess.PIPE).communicate()

        print("Received encrypt.sh output (" + str(len(output)) + " chars)")
        parsed = json.loads(output)

        print("Writing file to " + ctextsPath)
        with codecs.open(ctextsPath, encoding='utf-8', mode='w+') as votes_file:
            votes_file.write(json.dumps(parsed, sort_keys=True))
        #    for vote in parsed:
        #        votes_file.write(json.dumps(vote, sort_keys=True) + "\n")
    else:
        print("No public key or votes file, exiting..")
        exit(1)

def get_hmac(cfg, permission):
    import hmac

    secret = shared_secret
    message = '%s:%d' % (permission, 1000*long(time.time()))
    _hmac = hmac.new(str(secret), str(message), hashlib.sha256).hexdigest()
    auth = '%s:%s' % (message,_hmac)

    return auth

def main(argv):
    parser = argparse.ArgumentParser(description='agora-elections admin script', formatter_class=RawTextHelpFormatter)
    parser.add_argument('command', nargs='+', help='''register <election_json>: registers an election (uses local <id>.json file)
update <election_id>: updates an election (uses local <id>.json file)
create <election_id>: creates an election
start <election_id>: starts an election (votes can be cast)
stop <election_id>: stops an election (votes cannot be cast)
tally <election_dir>: launches tally
tally_no_dump <election_id>: launches tally (does not dump votes)
calculate_results <election_id>: uses agora-results to calculate the election's results (stored in db)
publish_results <election_id>: publishes an election's results (puts results.json and tally.tar.gz in public datastore)
show_column <election_id>: shows a column for an election
count_votes <election_id>: count votes
list_votes <election_dir>: list votes
list_elections: list elections
dump_pks <election_id>: dumps pks for an election (public datastore)
encrypt <election_id>: encrypts votes using scala (public key must be in datastore)
encryptNode <election_id>: encrypts votes using node (public key must be in datastore)
dump_votes <election_id>: dumps votes for an election (private datastore)
''')
    parser.add_argument('--ciphertexts', help='file to write ciphertetxs (used in dump, load and encrypt)')
    parser.add_argument('--plaintexts', help='json file to read votes from when encrypting', default = 'votes.json')
    parser.add_argument('--encrypt-count', help='number of votes to encrypt (generates duplicates if more than in json file)', type=int, default = 0)
    parser.add_argument('--results-config', help='config file for agora-results')
    parser.add_argument('-c', '--column', help='column to display when using show_column', default = 'state')
    parser.add_argument('-f', '--filters', nargs='+', default=[], help="key==value(s) filters for queries (use ~ for like)")
    args = parser.parse_args()
    command = args.command[0]
    if hasattr(__main__, command):
        config = {}

        # commands that use an election id
        if len(args.command) == 2:
            config['election_id'] = int(args.command[1])

            if args.ciphertexts is None:
                config['ciphertexts'] = 'ciphertexts_' + str(config['election_id'])
            else:
                config['ciphertexts'] = args.ciphertexts

            if command in ["register", "update"]:
                jsonPath = '%s.json' % config['election_id']
                if not os.path.isfile(jsonPath):
                    print("%s is not a file" % jsonPath)
                    exit(1)
                print("> loading config in %s" % jsonPath)
                with open(jsonPath, 'r') as f:
                    electionConfig = json.loads(f.read())

                config['electionConfig'] = electionConfig

        config['plaintexts'] = args.plaintexts
        config['encrypt-count'] = args.encrypt_count
        config['filters'] = args.filters

        eval(command + "(config, args)")

    else:
        parser.print_help()

if __name__ == "__main__":
	main(sys.argv[1:])