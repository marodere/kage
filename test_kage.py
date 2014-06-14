#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import unittest
import os

import kage
data_basedir = 'test_data'

class TestTracker:
	def test_parse_page_only(self):
		page = open(os.path.join(data_basedir, 'html', self.filename), 'rb').read()
		self.assertEqual(self.link, self.tracker.parse_page(self.name, page))
	
	def test_search(self):
		page = self.tracker.search(self.name)
		self.assertEqual(self.link, page)

class TestAnisource(TestTracker, unittest.TestCase):
	tracker = kage.AnisourceTracker()
	name = '[Leopard-Raws] Nobunaga the Fool - 20 RAW (TX 1280x720 x264 AAC)'
	filename = 'anisource.net.search.nobunaga.20.html'
	link = 'http://download.anisource.net/download/f15d58dafcd9a864192fe3187411cd8c730eb05f/'

class TestNyaaTorrents(TestTracker, unittest.TestCase):
	tracker = kage.NyaaTorrentsTracker()
	name = '[HorribleSubs] Fairy Tail - 134 [1080p]'
	filename = 'nyaa.se.fairy.tail.134.html'
	link = 'http://www.nyaa.se/?page=download&tid=321446'

class TestSubFile:
	def setUp(self):
		self.subfile = kage.SubFile(os.path.join(data_basedir, 'subs'), self.subfilename)
	
	def test_get_release_group(self):
		self.assertEqual(self.release_group, self.subfile.get_release_group())
	
	def test_get_title(self):
		self.assertEqual(self.title, self.subfile.get_title())

	def test_get_episode(self):
		self.assertEqual(self.episode, self.subfile.get_episode())
	
	def test_get_dst_subfilename(self):
		self.assertEqual(self.dst_subfilename,  self.subfile.get_dst_subfilename())

	def test_get_name_for_tracker(self):
		self.assertEqual(self.name_for_tracker, self.subfile.get_name_for_tracker())

	def test_get_tracker(self):
		self.assertIsInstance(self.subfile.get_tracker(), kage.Tracker)

class TestSubFile_Fairy_Tail_S2_10(TestSubFile, unittest.TestCase):
	subfilename = '[HorribleSubs] Fairy Tail S2 - 10 [480p].ass'
	release_group = 'horriblesubs'
	title = 'Fairy Tail S2'
	episode = 10
	dst_subfilename = '[HorribleSubs] Fairy Tail S2 - 10 [1080p].ass'
	name_for_tracker = '[HorribleSubs] Fairy Tail S2 - 10 [1080p]'

class TestSubFile_Space_Dandy_02(TestSubFile, unittest.TestCase):
	subfilename = '[Leopard-Raws] Space Dandy - 02 RAW (MX 1280x720 x264 AAC).ass'
	release_group = 'leopard-raws'
	title = 'Space Dandy'
	episode = 2
	dst_subfilename = '[Leopard-Raws] Space Dandy - 02 RAW (MX 1280x720 x264 AAC).ass'
	name_for_tracker = '[Leopard-Raws] Space Dandy - 02 RAW (MX 1280x720 x264 AAC)'

class TestSubFile_No_Game_No_Life_10(TestSubFile, unittest.TestCase):
	subfilename = '[HorribleSubs] No Game No Life - 10 [720p].unCreate.ass'
	release_group = 'horriblesubs'
	title = 'No Game No Life'
	episode = 10
	dst_subfilename = '[HorribleSubs] No Game No Life - 10 [1080p].ass'
	name_for_tracker = '[HorribleSubs] No Game No Life - 10 [1080p]'

class TestSubFile_Sidonia_No_Kishi_09(TestSubFile, unittest.TestCase):
	subfilename = '[Zero-Raws] Sidonia no Kishi - 09 (MBS 1280x720 x264 AAC).[HUNTA & Fratelli].ass'
	release_group = 'zero-raws'
	title = 'Sidonia no Kishi'
	episode = 9
	dst_subfilename = '[Zero-Raws] Sidonia no Kishi - 09 (MBS 1280x720 x264 AAC).ass'
	name_for_tracker = '[Zero-Raws] Sidonia no Kishi - 09 (MBS 1280x720 x264 AAC)'

class TestSubFile_Chuunibyou_Ren_04(TestSubFile, unittest.TestCase):
	subfilename = '[FTW]_Chuunibyou_demo_Koi_ga_Shitai!_Ren_-_04_[720p][885CC218].ass'
	release_group = 'ftw'
	title = 'Chuunibyou demo Koi ga Shitai! Ren'
	episode = 4
	dst_subfilename = '[FTW] Chuunibyou demo Koi ga Shitai! Ren - 04 [720p][885CC218].ass'
	name_for_tracker = '[FTW] Chuunibyou demo Koi ga Shitai! Ren - 04 [720p][885CC218]'

class SubArchiveTestExtract(unittest.TestCase):
	def test_extract_rar(self):
		kage.SubArchive(os.path.join(data_basedir, 'arch', 'no_game_no_life_unCreate_1_10.rar')).clean()
	
	def test_extract_7z(self):
		kage.SubArchive(os.path.join(data_basedir, 'arch', 'killa_(8411).7z')).clean()

class SubArchiveTestFindEpisode(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.subarchive = kage.SubArchive(os.path.join(data_basedir, 'arch', 'chuunibyou_demo_koi_ga_shitai_ren_tv1_9_ona1_5.rar'))

	@classmethod
	def tearDownClass(cls):
		cls.subarchive.clean()
	
	def __subtest_find_episode(self, n, should_exists, preferred_title=None, preferred_rg=None):
		print "Looking for ep %d" % n
		ep = self.subarchive.find_episode(n, preferred_title, preferred_rg)
		if should_exists:
			self.assertIsInstance(ep, kage.SubFile)
			print "Found!"
			if preferred_title is not None:
				self.assertEqual(preferred_title, ep.get_title())
				print "Title match!"
			if preferred_rg is not None:
				# There's no strict test condition, its for information only
				print "Chosen RG: %s" % preferred_rg
		else:
			self.assertIsNone(ep)
			print "Not found!"


	def test_find_episode(self):
		for n in range(1, 12):
			self.__subtest_find_episode(n, n <= 9)
			

	def test_find_episode_with_title(self):
		for n in range(1, 12):
			self.__subtest_find_episode(n, n <= 9, 'Chuunibyou demo Koi ga Shitai! Ren')
		for n in range(1, 12):
			self.__subtest_find_episode(n, n <= 5, 'Chuunibyou demo Koi ga Shitai! Ren Lite')
	
	def test_find_episode_with_rg(self):
		self.__subtest_find_episode(3, True, None, 'ftw')
	
	# Episode 08 by UTW is not presented in the test archive
	# SubArchive should choose alternative RG
	def test_find_episode_with_rg_alternative(self):
		self.__subtest_find_episode(8, True, None, 'utw')

class TestKageRg(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.kage_rg = kage.KageRg(8668, 'ТВ 1-12,25-84 + Спецвыпуск 1-7', '10.06.14')

	def __subtest_episode_ready(self, n, should_exists, min_release_delay=0):
		self.assertEqual(should_exists, self.kage_rg.is_episode_ready(n, min_release_delay, 1402377102)) # Tue, 10 Jun 2014 05:11:42 GMT

	def test_episode_ready(self):
		for n in range(10,30):
			self.__subtest_episode_ready(n, n <= 12 or 25 <= n)
	
	def test_episode_min_release_delay(self):
		self.__subtest_episode_ready(27, False, 172800)

class TestKageAnimePage(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.kage_anime = kage.KageAnimePage(4495)
	
	def test_find_episode(self):
		self.assertIsInstance(self.kage_anime.find_episode(10, 8668), kage.KageRg)
	
	def test_find_episode_notfound(self):
		self.assertIsNone(self.kage_anime.find_episode(18, 8668))
	
	def test_find_episode_different_srt(self):
		rg = self.kage_anime.find_episode(2, 8722)
		self.assertIsInstance(rg, kage.KageRg)

if __name__ == '__main__':
	unittest.main()
