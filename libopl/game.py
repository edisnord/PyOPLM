#!/usr/bin/env python3
###
# Game Class
# 
import json
from typing import List
from libopl.artwork import Artwork
from libopl.common import usba_crc32, slugify, is_file, read_in_chunks
from enum import Enum
from os import path

import re

from libopl.ul import ULConfigGame

class GameType(Enum):
    UL = "ul (USBExtreme)"
    ISO = "iso"

class Game():
    # constant values for gametypes
    type: GameType = None
    ulcfg = None

    filedir: str 
    filename: str 
    filetype: str 
    filepath: str 
    id: str
    opl_id: str 
    artwork: List[Artwork]
    title: str 
    crc32: str 
    size: float
    src_title: str 
    src_filename: str
    meta: dict

    # Regex for game serial/ids 
    id_regex = re.compile(r'S[a-zA-Z]{3}.?\d{3}\.?\d{2}')

    # Recover generate id from filename
    def __init__(self, filepath=None, id=None, recover_id=True):
        if filepath:
            self.filepath = filepath
            self.get_common_filedata(recover_id)
        if id:
            self.id = id
            self.gen_opl_id()

    def __repr__(self):
        return f"""\n----------------------------------------
LANG=en_US.UTF-8OPL-ID:       {self.opl_id}
Size (MB):    {self.size} 
Source Title: {self.src_title} 
New Title:    {self.title} 
Filename:     {self.filename}

Filetype:     {self.filetype}
Filedir:      {self.filedir}
CRC32:        {self.crc32}
Type:         {self.type}
ID:           {self.id} 
Filepath:     {self.filepath}
"""

    def __str__(self):
        return self.__repr__() 
    
    def print_data(self):
        print(str(self))
    
    # Generate Serial/ID in OPL-Format
    def gen_opl_id(self):
      oplid = self.id.replace('-', '_')
      oplid = oplid.replace('.', '')
      try: 
        oplid = oplid[:8] + "." + oplid[8:]
      except: 
        oplid = None
      self.opl_id = oplid
      return oplid.upper()

    def recover_id(self):
        print('Trying to recover Media-ID...')
        f = open(self.filepath, 'rb')
        for chunk in read_in_chunks(f):
            id = self.id_regex.findall(str(chunk))
            if len(id) > 0:
                print('Success: %s' % id[0])
                self.id = id[0]
                self.gen_opl_id()
                return id[0]
        return None

    # Set missing attributes using api metadata
    def set_metadata(self, api, override=False):
        if not self.id:
            return False

        try:
            meta = api.get_metadata(self.id)
            self.meta = meta
        except:
            return False
        
        self.src_title = self.title
        if self.meta:
            try:
                if not self.title or override: self.title = self.meta["name"][:64]
                if not self.id or override: self.id = self.metadata["id"]
                if not self.opl_id or override: self.opl_id = self.metadata["opl_id"]
            except: pass

        # Max iso filename length = 64
        # Max UL title length = 32
        # FIXME: dynmaic length of filetype 
        if override:
            try:
                self.title = slugify(self.meta["name"][:32])
            except: pass
            
        self.filename = self.opl_id + "." + self.title

        return True 
        #new_filename = self.filename[:64-len(".iso")]
        #self.new_filename = new_filename

    # Getting usefill data from filename
    # for ul & iso names
    def get_common_filedata(self, recover_id=True):
        self.filename = path.basename(self.filepath)
        self.filedir = path.dirname(self.filepath)

        if re.match(r'.*\.iso$', str(self.filename)):
            self.filetype = "iso"
            self.type = GameType.ISO

        # try to get id out of filename
        try:
            self.id = self.id_regex.findall(self.filename)[0]
        except:
            #else try to recover
            self.recover_id()
        if not self.get('id'):
            return False

        self.gen_opl_id()
        self.size = path.getsize(self.filepath)>>20
        return True

####
# UL-Format game, child-class of "Game"
class ULGameImage(Game):
    # ULConfigGame object
    ulcfg: ULConfigGame
    type: GameType = GameType.UL
    crc32: str

    # Chunk size matched USBUtil
    CHUNK_SIZE = 1073741824

    # Generate ULGameImage from filepath, ulcfg, or raw (meta-)data
    def __init__(self, filepath=None, ulcfg=None, data=None):
        # From file
        if filepath:
            super().__init__(filepath=filepath)
            self.get_filedata()
        # FRom ul.cfg
        elif ulcfg:
            self.ulcfg = ulcfg
            self.opl_id = self.ulcfg.region_code.replace('ul.', '')
            self.id = self.opl_id
            self.title = self.ulcfg.name
            self.crc32 = self.ulcfg.crc32
            self.filename = "ul." + self.crc32.replace('0x', '').upper()
            self.filename = self.filename + "." + self.opl_id + ".00"
        # Evolved from Game-Class
        elif data:
            self.data = data
        else: return None

    # Try to parse a filename to usefull data
    def get_filedata(self):
        self.filetype = None

        # Pattern: ul.{CRC32(title)}.{OPL_ID}.{PART}
        parts = self.filename.split('.')
        self.crc32 = parts[1]

        # Trim Title to 32chars
        self.title = self.title[:32]
        
        #self.crc32 = usba_crc32(self.title)
        return True

    # (Split) ISO into UL-Format
    def to_UL(self, dest_path, force=False):
        file_part = 0
        with open(self.filepath, 'rb') as f:
            chunk = f.read(ULGameImage.CHUNK_SIZE)
            while chunk:
                filename =  'ul.%s.%s.%.2X' % ( self.crc32[2:].upper(), \
                            self.opl_id, file_part)
                filepath = path.join(dest_path, filename)

                if is_file(filepath) and not force:
                    print("Warn: File '%s' already exists! Use -f to force overwrite." % filename)
                    return 0

                print("Writing File '%s'..." % filepath)
                with open(filepath, 'wb') as outfile:
                    outfile.write(chunk)
                    file_part += 1 
                    chunk = f.read(ULGameImage.CHUNK_SIZE)
        self.parts = file_part
        return file_part

####
# Class for ISO-Games (or alike), child-class of "Game"
class IsoGameImage(Game):
    type = GameType.ISO
    # Create Game based on filepath
    def __init__(self, filepath=None, data=None):
        if filepath:
            super().__init__(filepath)
            self.get_filedata() 
        if data:
            self.data = data

    # Get (meta-)data from filename
    def get_filedata(self):
        self.filetype = "iso"

        # FIXME: Better title / id sub
        self.title = self.id_regex.sub('', self.filename)
        self.title = self.title.replace("."+self.filetype, '')
        self.title = self.title.strip('._-\ ')
        self.filename = self.filename.replace("."+self.filetype, '')
        self.crc32 = hex(usba_crc32(self.title))
