#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import os
import sys
import grp
import tempfile
import shutil
import subprocess
import urllib
import urllib2
import cgi
import re

from ConfigParser import ConfigParser
from optparse import OptionParser, OptionGroup
from time import time, mktime
from datetime import datetime

from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders
from smtplib import SMTP

KAGE_VERSION="1.0.0"

def options_parser():
    usage = "%prog [options]"
    defaults = {'verbose'         : False,
                'dest_dir'        : '~/Downloads/Anime',
                'titles_file'       : '~/.kage/titles.cfg',
                'use_transmission': True,
                'use_smtp'        : True,
                'smtp_host'       : 'localhost',
                'smtp_port'       : 25,
                'emails'          : [],
               }
               
    parser = OptionParser(usage=usage, version=KAGE_VERSION)
    parser.add_option("-c", "--config", metavar="FILE",
                      help="Config with base settings and anime list.",
                      default=os.path.expanduser('~/.kage/kage.cfg'))
    parser.add_option("-v", "--verbose", action="store_true",
                      help="Print debug information.")
    parser.add_option("-l", "--log", metavar="FILE",
                      help="Write messages to file.")
    parser.add_option("-t", "--titles-file", metavar="FILE",
                      help="File with saved anime titles info.")
    parser.add_option("-b", "--dest-dir", metavar="FILE",
                      help="Download anime to this dir.")
                      
    main_g = OptionGroup(parser, "Main options")                      
    main_g.add_option("-i", "--id", type="int", dest="kage_id",
                      help="ID from url of KageProject anime page.")
    main_g.add_option("-a", "--add", action="store_true",
                      help="Add new anime to config.")
    main_g.add_option("-d", "--delete", action="store_true",
                      help="Remove anime from config by from kage ID")
    main_g.add_option("-u", "--update", action="store_true",
                      help="Search for first unseen episode and try to get them.")
    main_g.add_option("-U", "--get-all", action="store_true",
                      help="Search for new episodes and try to get them all.")
                      
    torrent_g = OptionGroup(parser, "Torrent client options")
    torrent_g.add_option("--no-transmission", action="store_false",
                      dest="use_transmission", help="Don't add torrent to Transmission.")
    torrent_g.add_option("--transmission-host",
                      help="'Host:port' of remote transmission instance.")
    torrent_g.add_option("--transmission-cred",
                      help="'user:password' for remote transmission instance.") 

    smtp_g = OptionGroup(parser, "Notification sending")
    smtp_g.add_option("--no-smtp", action="store_false", dest="use_smtp",
                      help="Don't send email notifications.")
    smtp_g.add_option("--smtp-host", help="SMTP host")
    smtp_g.add_option("--smtp-port", type="int", help="SMTP host port")
    smtp_g.add_option("--smtp-user", type="string", help="SMTP user")
    smtp_g.add_option("--smtp-password", type="string", help="SMTP password")           
    smtp_g.add_option("-r", "--recipient", type="string", action="append", dest="emails",
                      help="Send notification to this email. Can be listed several times.")
                      
    parser.add_option_group(main_g)
    parser.add_option_group(torrent_g)
    parser.add_option_group(smtp_g)                  
    (options, args) = parser.parse_args()

    options.config = os.path.expanduser(options.config)
    if not os.path.isfile(options.config):
        parser.error("Config file '%s' does't exists." % options.config)

    cfgparser = ConfigParser()
    cfgparser.read(options.config)
    if cfgparser.has_section('global'):
        for key, value in cfgparser.items('global'):
            if getattr(options, key, 'XXXXXX') is None:
                if key in ['verbose', 'use_transmission', 'use_smtp']:
                    value = cfgparser.getboolean('global', key)
                elif key in ['smtp_port']:
                    value = cfgparser.getint('global', key)
                elif key in ['emails']:
                    value = value.strip().split(' ')
                setattr(options, key, value)
                
    for key, value in defaults.iteritems():
        if getattr(options, key, 'XXXXXX') is None:
            setattr(options, key, value)
    
    if (options.add or options.delete) and options.kage_id is None:
        parser.error("To add or delete anime title you must specify kage ID with '--id'")
    if options.add and options.delete:
        parser.error("Delete and Add opts don't work together!")
    
    if options.update and options.get_all:
        parser.error("Update and GetAll opts don't work together!")    
            
    if options.use_transmission and options.transmission_host is not None and \
       options.transmission_cred is None:
        parser.error("Please specify login:password if you using remote transmission instance.")
        
    if options.use_smtp:
        if options.smtp_user is not None and options.smtp_pass is None:
            parser.error("Specify password for smtp user '%s'." % options.smtp_user)
        if len(options.emails) == 0:
            parser.error("SMTP notification is enabled but no recipients was listed!")

    options.dest_dir = os.path.expanduser(options.dest_dir)
    if not os.path.isdir(options.dest_dir):
        parser.error("Output dir '%s' does't exists." % options.dest_dir)

    options.titles_file = os.path.expanduser(options.titles_file)
    if not os.path.isfile(options.titles_file):
        if options.add is None:
            parser.error("File with anime info '%s' does't exists." % options.titles_file)
        else:
            open(options.titles_file, 'w').close()
      
    return options

def download_url(url):
    httpResponse = urllib2.urlopen(url)
    assert httpResponse.getcode() == 200, "HTTP request %s failed: %d\n" % (url, httpResponse.getcode())
    page = httpResponse.read()
    return page

class TorrentApi:
    @staticmethod
    def download(torrent_data, dst_dir):
        tmpfile = tempfile.NamedTemporaryFile(suffix=".torrent")
        tmpfile.write(torrent_data)
        tmpfile.flush()
        print "Downloading torrent %s to %s\n" % (tmpfile.name, dst_dir)
        subprocess.check_call(["transmission-remote",
            "192.168.10.1:9091", "-a",
            tmpfile.name,
            "-w",
            dst_dir,
            "-n",
            "bittorrent:formatc"])
        tmpfile.close()

class Tracker:
    def search(self, name):
        page = download_url(self.get_search_url(name))
        parse_result = self.parse_page(name, page)
        assert parse_result is not None, "Torrent %s was not found" % name
        return parse_result

class AnisourceTracker (Tracker):
    def parse_page(self, name, page):
        pattern = re.compile('<a target="_blank" href="(http://download\.anisource\.net/download/[0-9a-f]*/)"><img src="[^"]*"></a> <a href="[^"]*"><img src="[^"]*"></a></span>\n\s*<span class="hidden">[^<]*</span>\n\s*<span class="info">\n\s*<a href="[^"]*" title="[^ ]* %s' % re.escape(name), re.MULTILINE)
        searchResult = pattern.search(page)
        if searchResult is None:
            return None
        return searchResult.group(1)

    def get_search_url(self, name):
        return 'http://anisource.net/?search=%s' % urllib.quote_plus(name)

class NyaaTorrentsTracker (Tracker):
    def parse_page(self, name, page):
        pattern = re.compile('http://www\.nyaa\.se/\?page=download&#38;tid=[0-9]*')
        searchResult = pattern.search(page)
        if searchResult is None:
            return None
        return searchResult.group(0).replace('#38;', '')
    
    def get_search_url(self, name):
        return 'http://www.nyaa.se/?page=search&cats=0_0&filter=0&term=%s' % urllib.quote_plus(name)

class SubFile:
    torrent_link = None

    def __init__(self, dirpath, subfilename):
        self.src_subfilename = subfilename

        # ... unibyou_demo_Koi_ga_Shi ... => ... unibyou demo Koi ga Shi ...
        # TestCase: TestSubFile_Chuunibyou_Ren_04
        if re.search(' ', subfilename):
            match_subfilename = subfilename
        else:
            match_subfilename = subfilename.replace('_', ' ')

        pattern = re.compile('\[([^\]]*)\]\ (.*)\ -\ ([0-9]*)')
        searchResult = pattern.search(match_subfilename)
        assert searchResult is not None, "Regular expression mismatch"
        self.dirpath = dirpath
        self.release_group = searchResult.group(1).lower()
        self.title = searchResult.group(2)
        self.episode = int(searchResult.group(3))

        self.dst_subfilename = match_subfilename
        # ... 09 [720p].ass => 09 [1080p].ass
        # TestCase: TestSubFile_Fairy_Tail_S2_10
        if self.release_group == "horriblesubs":
            self.dst_subfilename = self.dst_subfilename.replace("[480p]", "[1080p]")
            self.dst_subfilename = self.dst_subfilename.replace("[720p]", "[1080p]")

        # ... 09 [720p].unCreate.ass => ... 09 [720p].ass
        # TestCase: TestSubFile_No_Game_No_Life_10
        # ... x264 AAC).[HUNTA & Fratelli].ass => ... x264 AAC).ass
        # TestCase: TestSubFile_Sidonia_No_Kishi_09
        pattern = re.compile('(\)|\])\.[^\.]*(\.[^\.]*)$')
        if pattern.search(self.dst_subfilename) is not None:
            self.dst_subfilename = pattern.sub(r'\1\2', self.dst_subfilename)

    def get_release_group(self):
        return self.release_group

    def get_title(self):
        return self.title

    def get_episode(self):
        return self.episode

    def get_src_subfile(self):
        return self.dirpath + "/" + self.src_subfilename

    def get_dst_subfilename(self):
        return self.dst_subfilename

    def get_name_for_tracker(self):
        pattern = re.compile('\.(ass|srt)$')
        assert pattern.search(self.get_dst_subfilename()) is not None, "File extension mismatch"
        return pattern.sub('', self.get_dst_subfilename())

    def get_tracker(self):
        if self.release_group in ('スカーraws', 'raws-4u', 'leopard-raws'):
            return AnisourceTracker()
        else:
            return NyaaTorrentsTracker()
    
    def get_torrent_link(self):
        if self.torrent_link is None:
            self.torrent_link = self.get_tracker().search(self.get_name_for_tracker())
        return self.torrent_link
    
    def get_torrent(self):
        return download_url(self.get_torrent_link())
    
    def send_notification(self):
        msg = MIMEMultipart()
        msg['Subject'] = '[ongoing] %s episode released' % self.get_title()
        msg["From"] = 'Anime Notifiction Daemon <noreply@master.onotole.local>'
        recipients = ['tolich.arz@yandex.ru', 'drgmachine@yandex.ru', 'toragen@yandex.ru']
        msg["To"] = ', '.join(recipients)
        
        body = MIMEText("Hi,\n%s episode %02d released and had to be downloaded.\nTorrent is here: %s\nSubtitles is in the attachment.\nEnjoy it.\n\n-- \nsincerely yours\nAnime Notifiction Daemon" % (self.get_title(), self.get_episode(), self.get_torrent_link()), 'plain', 'utf-8')
        msg.attach(body)

        sub = MIMEBase('text', 'plain')
        sub.set_payload(open(self.get_src_subfile(),"rb").read())
        Encoders.encode_base64(sub)
        sub.add_header('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(self.get_dst_subfilename()))
        msg.attach(sub)

        smtp = SMTP('localhost')
        smtp.sendmail(msg['From'], recipients, msg.as_string())
        smtp.quit()

class SubArchive:
    def get_unpack_command(self):
        if re.search('\.(7z|zip)$', self.archfilename.lower()):
            return [ '7z', 'x', '-y', '-o' + self.tmpdir, self.archfilename ]
        elif re.search('\.rar$', self.archfilename.lower()):
            return [ 'unrar', 'x', '-y', self.archfilename, self.tmpdir + '/' ]
        else:
            assert False, "Archive type is not defined"

    def __init__(self, archfilename):
        self.archfilename = archfilename
        self.tmpdir = tempfile.mkdtemp()
        subprocess.check_call(self.get_unpack_command())
        self.sub_files = []
        for dirpath, dirs, files in os.walk(self.tmpdir):
            for f in files:
                try:
                    s = SubFile(dirpath, f)
                    self.sub_files.append(s)
                except Exception as e:
                    print "Error processing file %s: %s" % (f, e)
    
    def find_episode(self, episode, preferred_title=None, preferred_release_group=None):
        res = None
        for s in self.sub_files:
            if s.get_episode() == episode and \
            (preferred_title is None or s.get_title() == preferred_title) and \
            (res is None or s.get_release_group() == preferred_release_group):
                res = s
        return res

    def clean(self):
        shutil.rmtree(self.tmpdir)

class KageRg:
    def __init__(self, srt_id, episodes, date):
        self.srt_id = srt_id
        self.episode_intervals = self.parse_episodes(episodes)
        self.release_ts = mktime(datetime.strptime(date, "%d.%m.%y").timetuple())

    def parse_episodes(self, episodes):
        intervals = []
        for i in episodes.split(','):
            bounds = re.search('([0-9]+)\-([0-9]+)', i)
            if bounds is not None:
                intervals.append([int(bounds.group(1)), int(bounds.group(2))])
            else:
                ep = re.search('[0-9]+', i)
                if ep is not None:
                    intervals.append([int(ep.group(0)), int(ep.group(0))])
        print 'RG %d has the following: %s (parsed as %s)' % (self.srt_id, episodes, str(intervals))
        return intervals
    
    def is_episode_presented(self, episode):
        for i in self.episode_intervals:
            if i[0] <= episode and episode <= i[1]:
                return True
        return False
    
    def is_episode_ready(self, episode, min_release_delay=0, curtime=time()):
        return self.is_episode_presented(episode) and (curtime - min_release_delay >= self.release_ts)

    def download(self):
        httpResponse = urllib2.urlopen('http://fansubs.ru/base.php', 'srt=%d&x=45&y=2' % self.srt_id)
        assert httpResponse.getcode() == 200, "HTTP request http://fansubs.ru/base.php?srt=%d&x=45&y=2 failed: %d\n" % (self.srt_id, httpResponse.getcode())
        
        _, params = cgi.parse_header(httpResponse.headers.get('Content-Disposition', ''))
        fname = os.path.join(tempfile.gettempdir(), params['filename'])
        print "Writing sub file to %s" % fname
        fd = open(fname, "w")
        fd.write(httpResponse.read())
        fd.close
        
        return fname

class KageAnimePage:
    def __init__(self, id):
        page = download_url("http://fansubs.ru/base.php?id=%d" % id)
        self.parse_page(page)

    def parse_page(self, page):
        pattern = re.compile('<td class="row3" width="290"><b>([^<]*)</b></td>\r?\n\s*<td width="100" align="center" class="row3"><a href="base.php\?cntr=([0-9]*)"><font color=#[A-Z0-9]*>([^<]*)</font></a></td>\r?\n\s*<td width="100" align="center" class="row3">([0-9\.]*)</td>', re.MULTILINE)
        searchResult = pattern.findall(page)
        assert searchResult, "could not match anything, may be markup was changed. please check it."
        self.rgs = {}
        for match in searchResult:
            srt_id = int(match[1])
            self.rgs[srt_id] = KageRg(srt_id, match[0].decode('cp1251').encode('utf-8'), match[3])
    
    def get_rg(self, srt_id):
        return self.rgs[srt_id]

    def find_episode(self, episode, preferred_srt_id=None):
        res = None
        if preferred_srt_id is not None and preferred_srt_id in self.rgs and self.rgs[preferred_srt_id].is_episode_ready(episode, 0):
            res = self.rgs[preferred_srt_id]
        else:    
            for srt_id, rg in self.rgs.iteritems():
                min_release_delay = 172800
                if rg.is_episode_ready(episode, min_release_delay):
                    res = rg
        return res

class ActRunner:
    options = None
    titles = []

    def run_action(self):
        if self.options.add:
            ka = KageAnimePage(self.options.kage_id)
            srt_id = int(raw_input('which one should I pick? '))
            rg = ka.get_rg(srt_id)
            sa = SubArchive(rg.download())
            titles_raws_idx = {}
            titles_raws = []
            for sf in sa.sub_files:
                key = sf.get_title() + sf.get_release_group()
                if key not in titles_raws_idx:
                    titles_raws.append([sf.get_title(), sf.get_release_group(), 1])
                    titles_raws_idx[key] = len(titles_raws) - 1
                else:
                    titles_raws[titles_raws_idx[key]][2] += 1
            for (idx, (title, release_group, neps)) in enumerate(titles_raws):
                print "%d\ttitle \"%s\", raws by %s, %d episodes" % (idx, title, release_group, neps)
            rg_title_comb = int(raw_input('which one should I pick? '))
            print titles_raws[idx][0]
            start_episode = int(raw_input('how many episodes I should skip (usually 0)? '))
            new_title = {'id': self.options.kage_id, 'srt_id': srt_id, 'start_episode': start_episode, 'title': titles_raws[rg_title_comb][0], 'rg': titles_raws[rg_title_comb][1]}
            self.titles.append(new_title)
        elif self.options.delete:
            for (key, title) in enumerate(self.titles):
                if title['id'] == self.options.kage_id:
                    del self.titles[key]

        if self.options.update or self.options.get_all:
            base_download_path = self.options.dest_dir

            for (key, title) in enumerate(self.titles):
                if title['disabled']:
                    print "==== NOT processing anime %d (%s) rg %d\n!!! disabled by config !!!" % (title['id'], title['title'], title['srt_id'])
                    continue

                print "==== processing anime %d (%s) rg %d" % (title['id'], title['title'], title['srt_id'])
                ka = KageAnimePage(title['id'])

                search_ep = title['start_episode'] + 1
                
                episode_correction = 0
                if title.has_key('episode_correction'):
                    episode_correction = title['episode_correction']

                sa = None
                while True:
                    print "Looking for episode %02d" % (search_ep + episode_correction)
                    rg = ka.find_episode(search_ep + episode_correction, title['srt_id'])
                    if rg is not None:
                        if self.titles[key]['srt_id'] != rg.srt_id:
                            self.titles[key]['srt_id'] = rg.srt_id
                            if sa is not None:
                                sa.clean()
                                sa = None

                        if sa is None:
                            sa = SubArchive(rg.download())

                        sf = sa.find_episode(search_ep, title['title'], title['rg'] if 'rg' in title else None)
                        assert sf is not None, "Expected episode %d was not found in archive" % search_ep
                        torrent_data = sf.get_torrent()
                        download_path = os.path.join(base_download_path, sf.get_title())
                        if not os.path.isdir(download_path):
                            os.mkdir(download_path)
                            os.chmod(download_path, 0775)
                            os.chown(download_path, -1, grp.getgrnam('transmission').gr_gid)
                        TorrentApi.download(torrent_data, download_path)
                        shutil.copyfile(sf.get_src_subfile(), os.path.join(download_path, sf.get_dst_subfilename()))
                        search_ep += 1
                        self.titles[key]['start_episode'] += 1
                        self.titles[key]['title'] = sf.get_title()
                        if not self.options.get_all:
                            sf.send_notification()
                            break
                    else:
                        print "Episode was not found :("
                        if sa is not None:
                            sa.clean()
                        break
   
    def load_anime_info(self):
        fmt = {'int'    : ['id', 'srt_id', 'start_episode', 'episode_correction'], 
               'bool'   : ['disabled'],
               'mustbe' : ['title','id'],
              }
        cfgparser = ConfigParser()
        cfgparser.read(self.options.titles_file)
    
        for section in cfgparser.sections():
            title = {}
            for key in cfgparser.options(section):
                if key in fmt['int']:
                    title[key] = cfgparser.getint(section, key)
                elif key in fmt['bool']:
                    title[key] = cfgparser.getboolean(section, key)
                else:
                    title[key] = cfgparser.get(section, key)
            for key in fmt['mustbe']:
                if not title.has_key(key):
                    print("Malformed configuration for section '%s'" % section)
            self.titles.append(title)
            
        if len(self.titles) == 0:
            print("Info wasn't load for any title in data file '%s'" % self.options.titles_file)
    
    def write_anime_info(self):
        cfgparser = ConfigParser()
        
        for title in self.titles:
            anime_id = str(title['id'])
            cfgparser.add_section(anime_id)
            for key, value in title.iteritems():
                cfgparser.set(anime_id, key, value)

        with open(self.options.titles_file, 'wb') as datafile:
            cfgparser.write(datafile)

    def __init__(self):
        self.options = options_parser()
        self.load_anime_info()
        self.run_action()
        self.write_anime_info()
    
if __name__ == "__main__":
    ActRunner()