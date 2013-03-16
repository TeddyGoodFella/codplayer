# codplayer - file system database interface
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Provide interfaces to working with the CD database in the file system.
"""

import os
import string
import base64
import re

from . import model


class DatabaseError(Exception):
    def __init__(self, dir, msg = None, entry = None, exc = None):
        if entry:
            m = '%s (%s): ' % (dir, entry)
        else:
            m = '%s: ' % dir

        if msg:
            m += str(msg)
        elif exc:
            m += str(exc)
        else:
            m += 'unknown error'

        super(DatabaseError, self).__init__(m)


class Database(object):
    """Access the filesystem database of ripped discs.

    The database uses the following directory structure:

    DB_DIR/.codplayerdb
      Identifies that this is a database directory.  Contains a single
      number that is the version of the database format.

    DB_DIR/discs/
      Contains all ripped discs by a hex version of the Musicbrainz
      disc ID.

    DB_DIR/discs/0/
    ...
    DB_DIR/discs/9/
    DB_DIR/discs/a/
    ...
    DB_DIR/discs/f/
      Buckets for the disc directories, based on first four bits of
      the disc ID (the first hex character).

    DB_DIR/discs/b/b8ffac79b6688994986a4661fa0ddca0aae67bc2/
      Directory for a ripped disc, named by hex version of disc ID.
      Referenced as DISC_DIR below.

    The files of a disc are all based on the first eight characters of
    the hex ID, to aid in reconstructing a trashed database:

    DISC_DIR/b8ffac79.id
      Contains the Musicbrainz version of the disc ID.
      
    DISC_DIR/b8ffac79.cdr
      Raw audio data (PCM samples) from the disc.

    DISC_DIR/b8ffac79.toc
      TOC read by cdrdao from the disc.

    DISC_DIR/b8ffac79.cod (optional)
      If present, the cooked disc TOC with album information and track
      edits.

    DISC_DIR/b8ffac79.riplog (optional)
      The log from the ripping process (may be discarded once complete).
    """

    VERSION = 1

    VERSION_FILE = '.codplayerdb'
    DISC_DIR = 'discs'

    DISC_BUCKETS = tuple('0123456789abcdef')
    
    DISC_ID_SUFFIX = '.id'
    AUDIO_SUFFIX = '.cdr'
    ORIG_TOC_SUFFIX = '.toc'
    COOKED_TOC_SUFFIX = '.cod'
    RIP_LOG_SUFFIX = '.riplog'

    #
    # Helper class methods
    #
    
    DISC_ID_TO_BASE64 = string.maketrans('._-', '+/=')
    BASE64_TO_DISC_ID = string.maketrans('+/=', '._-')

    VALID_DB_ID_RE = re.compile('^[0-9a-fA-F]{40}$')

    @classmethod
    def disc_to_db_id(cls, disc_id):
        """Translate a Musicbrainz Disc ID to database format."""

        id64 = disc_id.translate(cls.DISC_ID_TO_BASE64)
        idraw = base64.b64decode(id64)
        return base64.b16encode(idraw).lower()

    @classmethod
    def db_to_disc_id(cls, db_id):
        """Translate a database ID to Musicbrainz Disc ID."""

        idraw = base64.b16decode(db_id, True)
        id64 = base64.b64encode(idraw)
        return id64.translate(cls.BASE64_TO_DISC_ID)
    
    @classmethod
    def is_valid_db_id(cls, db_id):
        return cls.VALID_DB_ID_RE.match(db_id) is not None


    @classmethod
    def bucket_for_db_id(cls, db_id):
        return db_id[0]


    @classmethod
    def filename_base(cls, db_id):
        return db_id[:8]


    #
    # Database operations
    #

    @classmethod
    def init_db(cls, db_dir):
        """Initialise a database directory.

        @param db_dir: database top directory, must exist and be empty

        @raise DatabaseError: if directory doesn't exist or isn't empty
        """

        try:
            if not os.path.isdir(db_dir):
                raise DatabaseError(db_dir, 'no such dir')

            if os.listdir(db_dir):
                raise DatabaseError(db_dir, 'dir is not empty')

            f = open(os.path.join(db_dir, cls.VERSION_FILE), 'wt')
            f.write('%d\n' % cls.VERSION)
            f.close()

            disc_top_dir = os.path.join(db_dir, cls.DISC_DIR)
            os.mkdir(disc_top_dir)
            
            for b in cls.DISC_BUCKETS:
                os.mkdir(os.path.join(disc_top_dir, b))

        # translate into a DatabaseError
        except (IOError, OSError), e:
            raise DatabaseError(self.db_dir, exc = e)

    
    def __init__(self, db_dir):
        """Create an object accessing a database directory.

        @param db_dir: database top directory.

        @raise DatabaseError: if the directory structure is invalid
        """

        self.db_dir = db_dir

        try:
            # Must be a directory
            if not os.path.isdir(self.db_dir):
                raise DatabaseError(self.db_dir, 'no such directory')

            version_path = os.path.join(self.db_dir, self.VERSION_FILE)

            # Must have signature file
            if not os.path.isfile(version_path):
                raise DatabaseError(self.db_dir, 'missing version file',
                                    entry = self.VERSION_FILE)

            # Read first line to determine DB version
            f = open(version_path, 'rt')
            try:
                raw_version = f.readline()
                version = int(raw_version)
            except ValueError:
                raise DatabaseError(self.db_dir,
                                    'invalid version: %r' % raw_version,
                                    entry = self.VERSION_FILE)
                                    

            # Check that it is the expected version
            # (In the future: handle backward compatibility)

            if version != self.VERSION:
                raise DatabaseError(self.db_dir,
                                    'incompatible version: %d' % version,
                                    entry = self.VERSION_FILE)
                

            # Must have disc top dir

            disc_top_dir = os.path.join(self.db_dir, self.DISC_DIR)

            if not os.path.isdir(disc_top_dir):
                raise DatabaseError(self.db_dir, 'missing disc dir')


            # Must have all bucket dirs
            for b in self.DISC_BUCKETS:
                d = os.path.join(disc_top_dir, b)

                if not os.path.isdir(d):
                    raise DatabaseError(self.db_dir, 'missing bucket dir',
                                        entry = b)


        # translate into a DatabaseError
        except (IOError, OSError), e:
            raise DatabaseError(self.db_dir, exc = e)


    def get_disc_dir(self, db_id):
        """@return the path to the directory for a disc, identified by
        the db_id."""
        
        return os.path.join(self.db_dir,
                            self.DISC_DIR,
                            self.bucket_for_db_id(db_id),
                            db_id)

    def iterdiscs_db_ids(self):
        """@return an iterator listing the datbase IDs of all discs in
        the database.

        This method only looks at the directories, and may return IDs
        for discs that can't be opened (e.g. because it is in the
        progress of being ripped.)
        """

        disc_top_dir = os.path.join(self.db_dir, self.DISC_DIR)

        for b in self.DISC_BUCKETS:
            d = os.path.join(disc_top_dir, b)

            try:
                for f in os.listdir(d):
                    if self.is_valid_db_id(f) and self.bucket_for_db_id(f) == b:
                        yield f

            # translate into a DatabaseError
            except OSError, e:
                raise DatabaseError(self.db_dir, exc = e, entry = b)


    def get_disc_by_disc_id(self, disc_id):
        """@return a Disc basted on a MusicBrainz disc ID, or None if
        not found in database.
        """
        
        return self.get_disc_by_db_id(self.disc_to_db_id(disc_id))


    def get_disc_by_db_id(self, db_id):
        """@return a Disc basted on a database ID, or None if not
        found in database.
        """

        if not self.is_valid_db_id(db_id):
            raise ValueError('invalid DB ID: {0!r}'.format(db_id))

        path = self.get_disc_dir(db_id)
        fbase = self.filename_base(db_id)


        # TODO: check cooked TOC before original

        audio_file = os.path.join(path, fbase + self.AUDIO_SUFFIX)
        orig_toc_file = os.path.join(path, fbase + self.ORIG_TOC_SUFFIX)

        # Check that mandatory files are there
        if not (os.path.exists(audio_file) and
                os.path.exists(orig_toc_file)):
            return None
        
        try:
            f = open(orig_toc_file, 'rt')
            toc_data = f.read(50000) # keep it sane
            f.close()
        except IOError, e:
            raise DatabaseError('error reading {0}: {1}'.format(
                    orig_toc_file, e))
        
        return model.Disc.from_toc(toc_data, self.db_to_disc_id(db_id))


    def create_disc_dir(self, disc_id):
        """Create a directory for a new disc to be ripped into the
        database, identified by disc_id.

        @return a mapping of the paths to use when ripping the disc:

        - disc_path: path of disc directory
        - audio_file: file containing audio data
        - toc_file: raw TOC file
        - log_path: full path to log file for the ripping process
        """

        db_id = self.disc_to_db_id(disc_id)
        path = self.get_disc_dir(db_id)
            
        # Be forgiving if the dir already exists, to allow aborted
        # rips to be restarted easily

        if not os.path.isdir(path):
            try:
                os.mkdir(path)
            except OSError, e:
                raise DatabaseError('error creating disc dir {0}: {1}'.format(
                        path, e))


        fbase = self.filename_base(db_id)

        # Write the disc ID
        try:
            disc_id_path = os.path.join(path, fbase + self.DISC_ID_SUFFIX)
            f = open(disc_id_path, 'wt')
            f.write(disc_id + '\n')
            f.close()
        except IOError, e:
            raise DatabaseError('error writing disc ID to {0}: {1}'.format(
                    disc_id_path, e))

        return {
            'disc_path': path,
            'audio_file': fbase + self.AUDIO_SUFFIX,
            'toc_file': fbase + self.ORIG_TOC_SUFFIX,

            'log_path': os.path.join(path,
                                     fbase + self.RIP_LOG_SUFFIX)
            }

    