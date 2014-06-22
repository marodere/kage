#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import os
import sys
import grp
import tempfile
import shutil
import subprocess
import urllib2
import cgi
import re

from urllib import quote_plus
from ConfigParser import ConfigParser
from optparse import OptionParser, OptionGroup
from time import time, mktime
from datetime import datetime

from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders
from smtplib import SMTP

__VERSION__="1.0.0"

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
               
    parser = OptionParser(usage=usage, version=__VERSION__)
    parser.add_option("-c", "--config", metavar="FILE",
                      help="Config with base settings and anime list.",
                      default=os.path.expanduser('~/.kage/kage.cfg'))
    parser.add_option("-v", "--verbose", action="store_true",
                      help="Print debug information.")
    parser.add_option("-l", "--log", metavar="FILE",
                      help="Write messages to file.")
    parser.add_option("-t", "--titles-file", metavar="FILE",
                      help="File with saved anime titles info.")
    parser.add_option("-b", "--download-dir", metavar="DIR",
                      help="Download anime to this dir.")
                      
    main_g = OptionGroup(parser, "Main options")                      
    main_g.add_option("-a", "--add", action="store_true",
                      help="Add new anime to config.")
    main_g.add_option("-d", "--delete", action="store_true",
                      help="Remove anime from config by from kage ID")
    main_g.add_option("-u", "--update", action="store_true",
                      help="Search for first unseen episode and try to get them.")
    main_g.add_option("--list", action="store_true",
                      help="List enabled titles from config.")
                      
    main_g.add_option("-i", "--id", type="int", dest="kage_id",
                      help="ID from url of KageProject anime page.")
    main_g.add_option("-n", "--title-name", dest="title_name",
                      help="Anime title name.")
    main_g.add_option("-s", "--last-episode", type="int", dest="start_episode",
                      help="Download episodes after this.")
    main_g.add_option("--sub-rg-id", type="int", dest="sub_rg_id",
                      help="Subtitles release group id.")                      

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
                      help="Don't send email notifications.", default=True)
    smtp_g.add_option("--smtp-host", help="SMTP host")
    smtp_g.add_option("--smtp-port", type="int", help="SMTP host port")
    smtp_g.add_option("--smtp-user", type="string", help="SMTP user")
    smtp_g.add_option("--smtp-password", type="string", help="SMTP password")
    smtp_g.add_option("--email-from", type="string", help="Send emeil from this addr.")          
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
    assert httpResponse.getcode() == 200, "HTTP request %s failed: %d\n" % \
                                          (url, httpResponse.getcode())
    page = httpResponse.read()
    return page
        
def TransmissionTorrentDownload(torrent_data, dst_dir, remote=None, cred=None):
    tmpfile = tempfile.NamedTemporaryFile(suffix=".torrent")
    tmpfile.write(torrent_data)
    tmpfile.flush()
    
    if remote and cred:
        cmd = ['transmission-remote', remote, '-a', tmpfile.name, '-w',
               dst_dir, '-n', 'bittorrent:formatc']
    else:
        cmd = ['transmission-cli', '-w', dst_dir, tmpfile.name]
    
    print "Downloading torrent %s to %s\n" % (tmpfile.name, dst_dir)    
    subprocess.check_call(cmd)
    
    tmpfile.close()


class MailNotification:
    def __init__(self, subj, mfrom, recipients):
        self.msg = MIMEMultipart()
        self.recipients = recipients
        self.msg["To"] = ', '.join(recipients)
        self.msg['Subject'] = subj
        self.msg["From"] = mfrom
        
    def add_message(self, message):
        body = MIMEText(message, 'plain', 'utf-8')
        self.msg.attach(body)
        
    def add_attachment(self, file_name, file_data=None):
        sub = MIMEBase('text', 'plain')
        if file_data is not None:
            with open(file_name, 'rb') as fd:
                sub.set_payload(fd.read())
        else:
            sub.set_payload(file_data)
        Encoders.encode_base64(sub)
        sub.add_header('Content-Disposition', 'attachment; filename="%s"' % 
                       os.path.basename(file_name))
        self.msg.attach(sub)
        
    def send(self, host='localhost', port='25', user=None, password=None):
        smtp = SMTP(host, port=port)
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(self.msg['From'], self.recipients, self.msg.as_string())
        smtp.quit()

class Tracker:
    def search(self, name):
        page = download_url(self.get_search_url(name))
        parse_result = self.parse_page(name, page)
        assert parse_result is not None, "Torrent %s was not found" % name
        return parse_result
        
    def get_torrent(self, subfile):
        torrent_link = self.search(subfile.get_name_for_tracker())
        return download_url(torrent_link)
        
    def parse_page(self, name, page):
        raise NotImplementedError()
        
    def get_search_url(self, name):
        raise NotImplementedError()

class AnisourceTracker(Tracker):
    def parse_page(self, name, page):
        pattern = re.compile('<a target="_blank" href="(http://download\.anisource\.net/download/[0-9a-f]*/)"><img src="[^"]*"></a> <a href="[^"]*"><img src="[^"]*"></a></span>\n\s*<span class="hidden">[^<]*</span>\n\s*<span class="info">\n\s*<a href="[^"]*" title="[^ ]* %s' % re.escape(name), re.MULTILINE)
        searchResult = pattern.search(page)
        if searchResult is None:
            return None
        return searchResult.group(1)

    def get_search_url(self, name):
        return 'http://anisource.net/?search=%s' % quote_plus(name)

class NyaaTorrentsTracker (Tracker):
    def parse_page(self, name, page):
        pattern = re.compile('http://www\.nyaa\.se/\?page=download&#38;tid=[0-9]*')
        searchResult = pattern.search(page)
        if searchResult is None:
            return None
        return searchResult.group(0).replace('#38;', '')
    
    def get_search_url(self, name):
        return 'http://www.nyaa.se/?page=search&cats=0_0&filter=0&term=%s' % \
                quote_plus(name)

class SubFile:
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

    def get_name_for_tracker(self):
        pattern = re.compile('\.(ass|srt)$')
        assert pattern.search(self.get_dst_subfilename()) is not None, "File extension mismatch"
        return pattern.sub('', self.get_dst_subfilename())
        
    def copy_to_dst(self, dst_dir):
        shutil.copyfile(os.path.join(self.dirpath, self.src_subfilename),
                        os.path.join(dst_dir, self.dst_subfilename))

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
        self.release_groups = []
        self.episodes = []
        for dirpath, dirs, files in os.walk(self.tmpdir):
            for f in files:
                try:
                    sf = SubFile(dirpath, f)
                    rg = sf.release_group
                    if rg not in self.release_groups:
                        self.release_groups.append(rg)
                    self.episodes.append(sf.episode)
                    self.sub_files.append(sf)
                except Exception as e:
                    print "Error processing file %s: %s" % (f, e)
        self.episodes.sort()
    
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
        self.last_episode = sorted(self.episode_intervals, key=1).pop()
        
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
        print('RG %d has the following: %s (parsed as %s)' % 
              (self.srt_id, episodes, str(intervals)))
        return intervals

    def is_episode_presented(self, episode):
        for i in self.episode_intervals:
            if i[0] <= episode and episode <= i[1]:
                return True
        return False
    
    def is_episode_ready(self, episode, min_release_delay=0, curtime=time()):
        return self.is_episode_presented(episode) and \
               (curtime - min_release_delay >= self.release_ts)

    def download(self):
        httpResponse = urllib2.urlopen('http://fansubs.ru/base.php', 
                                       'srt=%d&x=45&y=2' % self.srt_id)
        assert httpResponse.getcode() == 200, "HTTP request http://fansubs.ru/base.php?srt=%d&x=45&y=2 failed: %d\n" % (self.srt_id, httpResponse.getcode())
        
        _, params = cgi.parse_header(httpResponse.headers.get('Content-Disposition', ''))
        fname = os.path.join(tempfile.gettempdir(), params['filename'])
        print "Writing sub file to %s" % fname
        fd = open(fname, "w")
        fd.write(httpResponse.read())
        fd.close()
        
        return fname

class KageAnimePage:
    def __init__(self, id):
        self.kage_rgs = {}
        page = download_url("http://fansubs.ru/base.php?id=%d" % id)
        self.parse_page(page)

    def parse_page(self, page):
        pattern = re.compile('<td class="row3" width="290"><b>([^<]*)</b></td>\r?\n\s*<td width="100" align="center" class="row3"><a href="base.php\?cntr=([0-9]*)"><font color=#[A-Z0-9]*>([^<]*)</font></a></td>\r?\n\s*<td width="100" align="center" class="row3">([0-9\.]*)</td>', re.MULTILINE)
        searchResult = pattern.findall(page)
        assert searchResult, "could not match anything, may be markup was changed. please check it."
        for match in searchResult:
            srt_id = int(match[1])
            self.kage_rgs[srt_id] = KageRg(srt_id,
                                    match[0].decode('cp1251').encode('utf-8'), 
                                    match[3])
    
    def get_fastest_rg(self):
        return sorted(self.kage_rgs, key=lambda a: a.last_episode).pop()

    def find_episode(self, episode, preferred_srt_id=None, min_release_delay=172800):
        res = None
        if preferred_srt_id is not None and preferred_srt_id in self.kage_rgs and \
           self.kage_rgs[preferred_srt_id].is_episode_ready(episode, 0):
            res = self.kage_rgs[preferred_srt_id]
        else:
            sort_by_last_ep = sorted(self.kage_rgs,
                                     key=lambda a: a.last_episode, reverse=True)
            for srt_id, krg in sort_by_last_ep.iteritems():
                if krg.is_episode_ready(episode, min_release_delay):
                    res = krg
                    break
        return res

class ActRunner:
    def __init__(self):
        self.options = options_parser()
        self.titles = []
        
        self.load_info()
        self.run_action()
        self.write_info()
        
    def run_action(self):
        if self.options.add:
            self.add_title()
        if self.options.delete():
            if self.options.kage_id:
                self.remove_title(self.options.kage_id)
            else:
                self.remove_title(self.options.title_name)
        if self.options.list:
            i = 0
            for title in self.titles:
                i += 1
                print("%d %d '%s'" % (i, title['id'], title['title']))
            return None
        if self.options.update:
            self.get_new_episodes()
            self.send_status_email()
        
    def get_tracker(self, release_group):
        if release_group in ('スカーraws', 'raws-4u', 'leopard-raws'):
            return AnisourceTracker()
        else:
            return NyaaTorrentsTracker()
    
    def mk_dst_dir(self, title_name):
        download_path = os.path.join(self.options.download_dir, title_name)
        if not os.path.isdir(download_path):
            os.mkdir(download_path)
            os.chmod(download_path, 0775)
            #os.chown(download_path, -1, grp.getgrnam('transmission').gr_gid)
        return download_path

    def download_episode(self, subfile, dst_dir):
        subfile.copy_to_dst(dst_dir)
        tracker = self.get_tracker(subfile.release_group)
        torrent_data = tracker.get_torrent(subfile)
        if self.options.use_transmission:
            TransmissionTorrentDownload(torrent_data, dst_dir,
                                        self.options.transmission_host,
                                        self.options.transmission_cred)
        return torrent_data
    
    def add_title(self):
        for title in self.titles:
            if title['id'] == self.options.kage_id:
                print("'%s' with KageID %d already added" % (title['title'], title['id']))
                return None
            
        ka = KageAnimePage(self.options.kage_id)
        
        if self.options.sub_rg_id:
            if not ka.kage_rgs.has_key(self.options.sub_rg_id):
                print("Sub release group %d was't found!" % self.options.sub_rg_id)
                return None
        
        if self.options.last_episode:
            rg = ka.find_episode(self.options.last_episode, self.options.sub_rg_id, 0)
        else:
            rg = ka.get_fastest_rg()
            
        if rg is None:
            print("Can't find subtitles release group!")
            return None
            
        sub_rg_id = rg.srt_id
            
        sa = SubArchive(rg.download())
        sa.clean()

        rg_count = len(sa.release_groups)
        if rg_count > 1:
            print("Avalible %d release groups:" % rg_count)
            for i in range(rg_count):
                print(" %d: %s" % (i, sa.release_groups[i]))
            rg_choise = int(raw_input('which one should I pick? '))
            release_group = sa.release_groups[rg_choise]
        elif rg_count == 0:
            release_group = sa.release_groups[0]
        else:
            release_group = None
            
        new_title = {}    
        new_title['id'] = self.options.kage_id
        new_title['title'] = sa.sub_files[0].title
        new_title['sub_rg'] = sub_rg_id
        if release_group is not None:
            new_title['rg'] = release_group
        if self.options.last_episode is not None:
            new_title['last_episode'] = self.options.last_episode
        else:
            new_title['last_episode'] = sorted(sa.sub_files, 
                                        key=lambda a: a.episode)[0].episode - 1
        
        self.titles.append(new_title)
                
    def get_new_episodes(self, episodes=None):
        for title in self.titles:
            if title.has_key('disabled') and title['disabled']:
                print("==== NOT processing anime '%s' KageID '%d'. Disabled by config!!!" %
                      (title['title'], title['id']))
                continue
            print "==== processing anime %d (%s) rg %d" % (title['id'], title['title'], title['sub_rg'])
            
            ka = KageAnimePage(title['id'])
            
            if episodes is None:
                search_ep = title['last_episode'] + 1
                if title.has_key('episode_correction'):
                    search_ep += title['episode_correction']
            else:
                episodes.sort()
                search_ep = episodes.pop()
                
            print("Looking for episode %02d" % search_ep)
            rg = ka.find_episode(search_ep, title['sub_rg'])
            
            try:
                sa = SubArchive(rg.download())
                sf = sa.find_episode(search_ep, title['title'],
                                     title['rg'] if 'rg' in title else None)
                assert sf is None, "Expected episode %d was not found in archive" % search_ep

                dst_dir = self.mk_dst_dir(sf.title)
                
                d_eps = []
                for sf in sa.sub_files:
                    if episodes is not None:
                        if sf.episode in episodes:
                            self.download_episode(sf, dst_dir)
                    elif not title.has_key('last_episode') or \
                         (title.has_key('last_episode') and   \
                         sf.episode > title['last_episode']):
                        torrent_data = self.download_episode(sf, dst_dir)
                        d_eps.append((sf.episode, torrent_data))
                self.downloaded[sf.title] = d_eps
        
                title['sub_rg'] = rg.srt_id
                title['last_episode'] = sa.episodes.pop()
                if title.has_key('rg'):
                    title['rg'] = rg.release_group
            finally:
                sa.clean()
    def send_status_email(self):
        if len(self.downloaded) == 0:
            return None
        if not self.options.use_smtp:
            return None
            
        subj = "New anime is ready to watch!"
        mail = MailNotification(subj, self.options.email_from,
                                self.options.emails)
        message = "New anime is ready to watch!\n\n"
        for title_name, d_eps in self.downloaded:
            eps = []
            for (ep, data) in d_eps:
                mail.add_attachment("%s-%d.torrent" % (title_name, ep),data)
                eps.append(ep)
            message +="Anime %s ready: %s\n" % (title_name, ', '.join(eps))
        message += "Enjoy!"
        mail.add_message(message)
        mail.send(self.options.smtp_host, self.options.smtp_port, 
                  self.options.smtp_user, self.options.password)

    def remove_title(self, title_id):
        if type(title_id) is int:
            search_key = 'id'
        else:
            search_key = 'name'
            
        for title in self.titles:
            if title[search_key] == title_id:
                self.titles.remove(title)
                
    def load_info(self):
        fmt = {'int'    : ['sub_rg', 'last_episode', 'episode_correction'], 
               'bool'   : ['disabled'],
               'mustbe' : ['title','last_episode'],
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
            title['id'] = int(section)
            self.titles.append(title)
            
        if len(self.titles) == 0:
            print("Info wasn't load for any title in data file '%s'" % 
                  self.options.titles_file)
    
    def write_info(self):
        cfgparser = ConfigParser()
        
        for title in sorted(self.titles, key=lambda k: k['title']):
            anime_id = str(title['id'])
            cfgparser.add_section(anime_id)
            for key in sorted(title.keys()):
                if key == 'id':
                    continue
                cfgparser.set(anime_id, key, title[key])

        with open(self.options.titles_file, 'wb') as datafile:
            cfgparser.write(datafile)
    
if __name__ == "__main__":
    ActRunner()