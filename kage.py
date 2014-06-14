#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import os, sys, getopt, tempfile, shutil, subprocess, grp
import urllib, urllib2, cgi
import sqlite3
import re
import json

from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders
from smtplib import SMTP

import time
import datetime

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
			"127.0.0.1:9091", "-a",
			tmpfile.name,
			"-w",
			dst_dir,
			"-n",
			"bittorrent:123"])
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
		pattern = re.compile('\[([^\]]*)\]\ (.*)\ -\ ([0-9]*)')
		searchResult = pattern.search(subfilename)
		assert searchResult is not None, "Regular expression mismatch"
		self.dirpath = dirpath
		self.src_subfilename = subfilename
		self.release_group = searchResult.group(1).lower()
		self.title = searchResult.group(2)
		self.episode = int(searchResult.group(3))

	def get_release_group(self):
		return self.release_group

	def get_title(self):
		return self.title

	def get_episode(self):
		return self.episode

	def get_src_subfile(self):
		return self.dirpath + "/" + self.src_subfilename

	def get_dst_subfilename(self):
		dst_subfilename = self.src_subfilename

		if self.release_group == "horriblesubs":
			dst_subfilename = dst_subfilename.replace("[480p]", "[1080p]")
			dst_subfilename = dst_subfilename.replace("[720p]", "[1080p]")

		#pattern = re.compile('\.[^\.]*(\.[^\.]*)$')
		#if pattern.search(dst_subfilename) is not None:
		#	dst_subfilename = pattern.sub(r'\1', dst_subfilename)

		return dst_subfilename

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
		self.release_ts = time.mktime(datetime.datetime.strptime(date, "%d.%m.%y").timetuple())

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
	
	def is_episode_ready(self, episode, min_release_delay=0):
		return self.is_episode_presented(episode) and (time.time() - min_release_delay >= self.release_ts)

	def download(self):
		httpResponse = urllib2.urlopen('http://fansubs.ru/base.php', 'srt=%d&x=45&y=2' % self.srt_id)
		assert httpResponse.getcode() == 200, "HTTP request %s failed: %d\n" % (url, httpResponse.getcode())
		
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
	config_file = "/home/tolich/anime-fetch/config.json"
	config = None
	act_add = None 
	act_del = None 
	act_upd = False
	act_start_episode = 0

	def usage(self, call_exit=True):
		print "Usage: kage.py [-aduU]"
		if call_exit:
			sys.exit(2)

	def getopt(self):
		try:
			opts, args = getopt.getopt(sys.argv[1:], "a:d:uU")
		except getopt.GetoptError as err:
			self.usage()

		for o, a in opts:
			if o == "-a":
				self.act_add = int(a)
			elif o == "-d":
				self.act_del = int(a)
			elif o == "-u":
				self.act_upd = 'inc'
			elif o == "-U":
				self.act_upd = 'full'
			else:
				assert False, "unhandled option %s" % o

	def run_action(self):
		if self.act_add:
			ka = KageAnimePage(self.act_add)
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
			new_title = {'id': self.act_add, 'srt_id': srt_id, 'start_episode': start_episode, 'title': titles_raws[rg_title_comb][0], 'rg': titles_raws[rg_title_comb][1]}
			self.config['series'].append(new_title)
		elif self.act_del:
			for (key, title) in enumerate(self.config['series']):
				if title['id'] == self.act_del:
					del self.config['series'][key]

		if self.act_upd:
			base_download_path = "/place/transmission/downloads/Anime"

			for (key, title) in enumerate(self.config['series']):
				if not 'title' in title:
					title['title'] = None

				if 'disabled' in title:
					print "==== NOT processing anime %d (%s) rg %d\n!!! disabled by config !!!" % (title['id'], title['title'], title['srt_id'])
					continue

				print "==== processing anime %d (%s) rg %d" % (title['id'], title['title'], title['srt_id'])
				ka = KageAnimePage(title['id'])

				search_ep = title['start_episode'] + 1
				episode_correction = 0
				if 'episode_correction' in title:
					episode_correction = title['episode_correction']

				sa = None
				while True:
					print "Looking for episode %02d" % (search_ep + episode_correction)
					rg = ka.find_episode(search_ep + episode_correction, title['srt_id'])
					if rg is not None:
						if self.config['series'][key]['srt_id'] != rg.srt_id:
							self.config['series'][key]['srt_id'] = rg.srt_id
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
						self.config['series'][key]['start_episode'] += 1
						self.config['series'][key]['title'] = sf.get_title()
						if self.act_upd != 'full':
							sf.send_notification()
							break
					else:
						print "Episode was not found :("
						if sa is not None:
							sa.clean()
						break

		
		if not self.act_upd and not self.act_add and not self.act_del:
			self.usage()
		
	def read_config(self):
		try:
			config_fd = open(self.config_file, 'r')
			self.config = json.load(config_fd)
			config_fd.close()
		except:
			print "Invalid or missed config, empty new will be created"
		if self.config is None:
			self.config = { 'series': [] }
	
	def write_config(self):
		config_fd = open(self.config_file, 'w')
		json.dump(self.config, config_fd)
		config_fd.close()

	def __init__(self):
		self.getopt()
		self.read_config()
		self.run_action()
		self.write_config()

def main():
	runner = ActRunner()

	return 0
	

if __name__ == "__main__":
	main()
