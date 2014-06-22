#!/bin/python
# -*- coding: utf-8 -*-

import sys
import os
import json
from ConfigParser import ConfigParser

if len(sys.argv) < 3:
    print("Usage: %s old_config.json new_config.cfg" % os.path.basename(sys.argv[0]))
    sys.exit(1)

old_conf = sys.argv[1]
new_conf = sys.argv[2]


if not os.path.exists(old_conf):
    print("Old config doesn't exists: %s" %  old_conf)
    sys.exit(1)
    
with open(old_conf, 'r') as fd:
    json_data = json.load(fd)

cfgparser = ConfigParser()
for title in sorted(json_data['series'], key=lambda k: k['title']):
    anime_id = str(title['id'])
    cfgparser.add_section(anime_id)
    
    for key in title.keys():
        if key == 'srt_id':
            title['sub_rg'] = title['srt_id']
            del title[key]
        elif key == 'start_episode':
            title['last_episode'] = title['start_episode']
            del title[key]
        elif key == 'id':
            del title[key]
            
    for key in sorted(title.keys()):
        if key == 'id':
            continue
        cfgparser.set(anime_id, key, title[key])

with open(new_conf, 'wb') as datafile:
    cfgparser.write(datafile)