import csv
from dataclasses import dataclass
from functools import reduce
from io import BytesIO
from enum import Enum
from itertools import islice
from pathlib import Path
import sqlite3
import re
from typing import Dict, Iterator, List, Set, Tuple, NewType
from urllib.request import urlopen
from urllib.parse import quote, urljoin
from urllib.error import HTTPError, URLError
from sys import stderr
from PIL import Image
from io import StringIO
import os

from bs4 import BeautifulSoup


def urls_for_odd_type(region_code: str, art_type: str, url=None) -> Iterator[Tuple[str, str]]:
    """URL generator for types SCR and BG, which do not follow other 
    art type's naming conventions in danielb's art backups"""
    curr_num = 0
    while True:
        parts = [url if url else '', "PS2", region_code,
                 f"{region_code}_{art_type}_{str(curr_num).rjust(2, '0')}"]

        path_no_extension = reduce(urljoin if url else os.path.join, parts)
        yield (f"{path_no_extension}.jpg", f"{path_no_extension}.png")
        curr_num += 1


def csv_delete_cols_to_dict(file: str, cols_to_delete: List[str]) -> Dict[str, str]:
    """Read a CSV file, delete columns listed in cols_to_delete from it and create a
    dict. Fails if the CSV is left with more than 2 columns.
    """
    source = StringIO(urlopen(str(file)).read().decode('utf-8'))
    next(source)
    output = StringIO()

    reader = list(csv.reader(source))
    headers = reader[0]

    indexes_to_delete = [idx for idx, elem in enumerate(
        headers) if elem in cols_to_delete]
    result = [[o for idx, o in enumerate(
        obj) if idx not in indexes_to_delete] for obj in reader]

    writer = csv.writer(output)
    writer.writerows(result)

    output.seek(0)
    return dict(csv.reader(output))


@dataclass(unsafe_hash=True, frozen=True, eq=True)
class Artwork:
    region_code: str
    console: str
    art_type: str
    file_extension: str
    src_filename: str
    dest_filename: str

    def get_relative_source_path(self) -> Path:
        """Get relative path to the file in the storage, can be 
        joined with a URL or system path"""
        return Path(self.console, self.region_code, self.src_filename)

    def get_relative_destination_path(self) -> Path:
        """Get relative path to where this art file will be saved to,
          can be joined with a URL or system path"""
        return Path("ART", self.dest_filename)


class Indexing:
    con: sqlite3.Connection
    zip_contents_url: str
    storage_path: Path | str
    title_csv_location: str
    INDEX_FILENAME = "indexed_storage.db"

    ART_FILENAME_PATTERN = r'[HMPGNCSJTBDAKs][a-zA-Z]{3}.?\d{3}\.?\d{2}_([A-Z]*(2|_\d\d)?)'

    CREATE_TABLE_ARTWORKS_DDL = """
    CREATE TABLE IF NOT EXISTS Artworks (
        region_code VARCHAR(11) NOT NULL,
        console VARCHAR(3)
            CHECK (console IN ('PS1', 'PS2')) NOT NULL,
        art_type VARCHAR(4)
            CHECK (art_type IN ('COV', 'COV2', 'ICO', 'SCR'
                              , 'SCR2', 'LAB', 'BG', 'LGO')) NOT NULL,
        file_extension VARCHAR(4)
            CHECK (file_extension IN ('png', 'jpg')) NOT NULL,
        src_filename VARCHAR(20) NOT NULL,
        dest_filename VARCHAR(20) NOT NULL,
        PRIMARY KEY (region_code, console ,art_type)
    );"""

    CREATE_TABLE_TITLES = """
    CREATE TABLE IF NOT EXISTS Titles (
        region_code VARCHAR(11) PRIMARY KEY NOT NULL,
        title text
    );
"""

    def __init__(self, opl_dir: Path, zip_contents_url: str, title_csv_location: str):
        self.con = sqlite3.connect(opl_dir.joinpath(self.INDEX_FILENAME))
        self.zip_contents_url = zip_contents_url
        self.title_csv_location = title_csv_location
        cur = self.con.cursor()
        cur.execute(self.CREATE_TABLE_TITLES)
        cur.execute(self.CREATE_TABLE_ARTWORKS_DDL)
        self.con.commit()
        # Check if there are no rows in the table
        if not int(cur.execute("SELECT COUNT(*) FROM Artworks").fetchone()[0]):
            self.index_artwork()

        if not int(cur.execute("SELECT COUNT(*) FROM Titles").fetchone()[0]):
            self.index_titles()

    def get_artworks_for_game(self, region_code: str) -> Iterator[Artwork]:
        cur = self.con.cursor()

        console_ps1: Iterator[Tuple[str, str, str, str, str, str]] = cur.execute(
            "SELECT * FROM Artworks WHERE region_code=? and console='PS1'", (region_code,)).fetchall()
        console_ps2: Iterator[Tuple[str, str, str, str, str, str]] = cur.execute(
            "SELECT * FROM Artworks WHERE region_code=? and console='PS2'", (region_code,)).fetchall()

        # Sometimes PS1 games can be in PS2 folder, and PS2 games can be in PS1 folder
        # Magical stuff
        return map(lambda x: Artwork(*x), max(console_ps1, console_ps2, key=len))

    def get_title_for_game(self, region_code: str) -> str | None:
        cur = self.con.cursor()
        row = cur.execute(
            "SELECT title FROM Titles WHERE region_code=?", (region_code,))
        return row.fetchone()[0] if row else None

    def index_titles(self) -> None:
        cur = self.con.cursor()
        try:
            processed_csv = csv_delete_cols_to_dict(
                self.title_csv_location, ["ID"])

            # TODO: Make code cross platform
            split_path = self.title_csv_location.split("/")
            new_file = "PS2_LIST.CSV" if split_path[-1].startswith(
                "PS1") else "PS1_LIST.CSV"
            new_path = "/".join(split_path[0:-1] + [new_file])

            processed_csv.update(csv_delete_cols_to_dict(
                new_path,
                ["ID"]
            ))
        except HTTPError as e:
            print(
                "Cannot find game list in online storage, not indexing titles", file=stderr)
            return
        except URLError as e:
            print(
                "Cannot find game list in storage, not indexing titles", file=stderr)
            return

        print("Begin indexing titles...")

        cur.executemany("INSERT INTO Titles VALUES(?, ?)",
                        processed_csv.items())
        self.con.commit()
        print("Finished indexing titles")

    def index_artwork(self) -> None:
        cur = self.con.cursor()
        print("Begin indexing artwork...")
        print("Requesting artwork file table...")
        try:
            contents = urlopen(self.zip_contents_url)
        except HTTPError as e:
            print(
                f"Attempt to access storage file list on the web failed, no caching on this run, reason: {e.reason}", file=stderr)
            print(f"Error code: {e.code}", file=stderr)
            print(f"Response headers: {e.headers}", file=stderr)
        except URLError as e:
            print(
                f"Error accessing storage file list on the given URL, no caching on this run, reason: {e.reason}", file=stderr)
        print("Done!")
        print("Parsing artwork file table...")
        games_page = BeautifulSoup(
            contents.read(), features='lxml')
        print("Done!")

        contents.close()

        table = games_page.find('table')
        if not table:
            raise ValueError(
                "STORAGE.CACHING's 'zip_contents_location' key in the 'pyoplm.ini' does not lead to an internet archive zip content view page, please enter a proper link. Disabling caching for this run.")

        rows = table.find_all('tr')

        records = []

        print("Processing rows...")
        for row in rows:
            image_path = row.find('td')
            if image_path:
                path = image_path.text.strip()
                if path.endswith(('.jpg', '.png')):
                    split_path = path.split('/')
                    if len(split_path) < 3:
                        continue

                    game_id = split_path[1]
                    console = split_path[0]
                    filename = split_path[2]
                    art_type_match = re.findall(
                        self.ART_FILENAME_PATTERN, filename)
                    if art_type_match:
                        art_type = art_type_match[0][0]
                    else:
                        continue

                    # Handle BG and SCR files
                    if '_' in art_type:
                        split_art_type = art_type.split('_')
                        nr = split_art_type[1]
                        base_type = split_art_type[0]
                        if int(nr) <= 1 and base_type == 'SCR':
                            art_type = f"{base_type}{'' if int(nr) == 0 else '2'}"
                        elif base_type == 'BG' and int(nr) == 0:
                            art_type = 'BG'
                        else:
                            continue
                    file_extension = filename.split('.')[2]
                    dest_filename = f'{game_id}_{art_type}.{file_extension}'
                    records.append((game_id, console, art_type,
                                    file_extension, filename, dest_filename))
        print("Done!")

        print("Saving to index database...")
        cur.executemany('INSERT INTO Artworks VALUES (?,?,?,?,?,?)', records)
        self.con.commit()
        print("Done indexing!")
        pass


class Storage:
    """Class which manages all storage-related features such as updating game
    names from the CSVs in the backups and placing a game's artwork files into
    OPL's ART directory"""

    class OperationState(Enum):
        """The storage's operation states"""
        FILESYSTEM = 1
        ONLINE = 2
        DISABLED = 3

    Dimensions = NewType("Dimensions", Tuple[int, int])

    operation_state: OperationState
    """The Storage's current operation state"""

    storage_location: str | Path
    """Location of the backup"""

    old_dir: Path
    """Path to OPL folder"""

    cached_game_list: Dict[str, str]

    index: Indexing | None

    global urls_for_odd_type
    global csv_delete_cols_to_dict

    PS2_TYPES_OF_ART: Set[str] = set(
        ("COV", "COV2", "ICO", "LAB", "SCR", "BG", "LGO"))
    """All the types of OPL PS2 art files"""

    PS2_ART_SIZES: Dict[str, Dimensions] = {
        "COV": (140, 200),
        "COV2": (242, 344),
        "ICO": (64, 64),
        "LAB": (18, 240),
        "SCR": (250, 188),
        "BG": (640, 480),
        "SCR2": (250, 188),
        "LGO": (300, 125)
    }
    """Sizes for different types of PS2 art"""

    def __init__(self, backup_location: str | None, opl_dir: Path, indexing_url: str = None):
        self.index = None
        self.cached_game_list = {}
        if not backup_location:
            self.operation_state = self.OperationState.DISABLED
            return

        self.opl_dir = opl_dir
        if backup_location[-1] != "/":
            backup_location += "/"

        if (loc := Path(backup_location)).exists():
            self.operation_state = self.OperationState.FILESYSTEM
            self.storage_location = loc
            if indexing_url:
                self.index = Indexing(
                    opl_dir, indexing_url, self.storage_location.joinpath("PS1_LIST.CSV").as_uri())
        else:
            try:
                url = urlopen(backup_location)
                url.close()
                if indexing_url:
                    self.index = Indexing(opl_dir, indexing_url, urljoin(
                        backup_location, "PS1_LIST.CSV"))
                self.operation_state = self.OperationState.ONLINE
                self.storage_location = backup_location
            except HTTPError as e:
                print(
                    f"Attempt to access storage on the web failed, reason: {e.reason}")
                print(f"Error code: {e.code}", file=stderr)
                print(f"Response headers: {e.headers}", file=stderr)
                print(f"WARNING: Features depending on storage have been disabled, there were issues finding and accessing the supplied storage.")
                self.disable_storage()
            except URLError as e:
                print(
                    f"Error accessing web or filesystem storage on the given link, reason: {e.reason}", file=stderr)
                print(f"WARNING: Features depending on storage have been disabled, there were issues finding and accessing the supplied storage.")
                self.disable_storage()
            except Exception as e:
                print(e, file=stderr)
                print(f"WARNING: Features depending on storage have been disabled, there were issues finding and accessing the supplied storage.")
                self.disable_storage()

    def is_enabled(self):
        match self.operation_state:
            case self.OperationState.DISABLED:
                return False
            case _:
                return True

    def process_game_list_csv(self, file) -> Dict[str, str]:
        if not self.cached_game_list:
            self.cached_game_list = csv_delete_cols_to_dict(file, ["ID"])
        return self.cached_game_list

    def disable_storage(self):
        """Set the Storage's operation state to Disabled, effectively
        disabling all Storage dependent features on the app"""
        self.operation_state = self.OperationState.DISABLED

    def should_resize(self, art_type: str) -> bool:
        """Checks whether an art file should be automatically resized or not
        based on its art type"""
        return art_type == "COV" or art_type == "LAB"\
            or art_type == "SCR" or art_type == "BG"

    def resize_artwork(self, art_type: str, image_data: bytes, filename: str) -> BytesIO:
        file_format = "jpeg" if filename.split(".")[-1] == "jpg" else "png"
        output: BytesIO = BytesIO()
        if self.should_resize(art_type):
            image = Image.open(BytesIO(image_data))
            image = image.resize(self.PS2_ART_SIZES[art_type])
            image.save(output, file_format)
        else:
            output.write(image_data)
        output.seek(0)
        return output

    def get_filename_options(self, region_code: str, art_type: str, url: str = None) -> Iterator[Tuple[str, str]]:
        if art_type != "SCR" and art_type != "BG":
            return [(self.storage_location
                     + f"PS2/{region_code}/{region_code}_{art_type}{ext}"
                     for ext in [".png", ".jpg"])]
        else:
            return urls_for_odd_type(region_code, art_type, url)

    def __get_already_existing_art_types_for_game(self, region_code) -> Set[str]:
        existing = self.opl_dir.glob(f"ART/{region_code}*")
        return set(
            map(lambda x: re.findall(
                r'S[a-zA-Z]{3}.?\d{3}\.?\d{2}_([A-Z]*2?)', x.name)[0], existing)
        )

    def get_artwork_for_game(self, region_code: str, overwrite: bool) -> None:
        """Retrieves  all artwork files related to a title, properly resizes them 
        and places them in the OPL ART directory."""

        existing_types = self.__get_already_existing_art_types_for_game(
            region_code)

        if self.index:
            if self.__get_artwork_for_game_indexed(region_code, overwrite):
                return

        for art_type in self.PS2_TYPES_OF_ART:
            if art_type in existing_types and not overwrite:
                continue
            match self.operation_state:
                case self.OperationState.ONLINE:
                    possible_locations = self.get_filename_options(
                        region_code, art_type, self.storage_location)

                    count = 0

                    for possibilities in islice(possible_locations, 2 if art_type == "SCR" else 1):
                        found = False
                        for possibility in possibilities:
                            try:
                                with urlopen(possibility) as dl_art_file:
                                    file_extension = possibility.split(
                                        '.')[-1]
                                    dest_filename = f"{region_code}_{art_type}{'' if count == 0 else '2'}.{file_extension}"
                                    count += 1

                                    art_file_path = self.opl_dir.joinpath(
                                        "ART", dest_filename)

                                    if not art_file_path.exists() or overwrite:
                                        art_file = art_file_path.open('wb')

                                        art_file.write(self.resize_artwork(
                                            art_type, dl_art_file.read(), possibility).read())
                                        art_file.close()
                                        found = True
                                        break
                            except HTTPError:
                                pass
                        if not found or count > 1:
                            break

                case self.OperationState.FILESYSTEM:
                    glob_pattern_suffix = "_*" if art_type == "SCR" and art_type == "BG" else "*"
                    ps2_art_files: Iterator[Path] = list(self.storage_location.joinpath("PS2", region_code)\
                        .glob(f"{region_code}_{art_type}{glob_pattern_suffix}"))
                    ps1_art_files: Iterator[Path] = list(self.storage_location.joinpath("PS1", region_code)\
                        .glob(f"{region_code}_{art_type}{glob_pattern_suffix}"))
                    

                    for art_file in islice(max(ps1_art_files, ps2_art_files, key=len), 2 if art_type == "SCR" else 1):
                        art_nr = ''
                        if art_type == "SCR" and art_type == "BG":
                            art_nr = int(art_file.name[16:18])+1

                        dest_filename = f"{region_code}_{art_type}{art_nr}{art_file.suffix}"
                        dest_file = self.opl_dir.joinpath(
                            "ART", dest_filename)

                        if not dest_file.exists() or overwrite:
                            if not dest_file.exists():
                                dest_file.touch()

                            with dest_file.open("wb") as dest,\
                                    art_file.open("rb") as src:
                                dest.write(self.resize_artwork(
                                    art_type, src.read(), str(art_file)).read())

                case self.OperationState.DISABLED:
                    raise DisabledException(
                        "Storage features disabled, code should not have reached this point")

    def __get_artwork_for_game_indexed(self, region_code: str, overwrite: bool):
        art_count = 0
        for artwork in self.index.get_artworks_for_game(region_code):
            match self.operation_state:
                case self.OperationState.ONLINE:
                    try:
                        src_file = urlopen(
                            urljoin(self.storage_location
                            , str(artwork.get_relative_source_path()))
                        )
                    except HTTPError:
                        print(f"Error retrieving file \'{artwork.get_relative_source_path()}\' from online storage, are you sure the ZIP you uploaded is the same with the index link?", file=stderr)
                        continue
                case self.OperationState.FILESYSTEM:
                    try:
                        src_file = self.storage_location.joinpath(artwork.get_relative_source_path()).open("rb") 
                    except FileNotFoundError:
                        print(f"Error retrieving file \'{artwork.get_relative_source_path()}\' from online storage, are you sure the ZIP you uploaded is the same with the index link?", file=stderr)
                        continue
                case self.OperationState.DISABLED:
                    raise DisabledException(
                        "Storage features disabled, code should not have reached this point")

            picture_data  = src_file.read()
            picture_buffer: BytesIO = self.resize_artwork(artwork.art_type, picture_data, artwork.src_filename)
            dest_file = self.opl_dir.joinpath(
                    artwork.get_relative_destination_path())

            if not dest_file.exists() or overwrite:
                if not dest_file.exists():
                    dest_file.touch()

                dest_file = dest_file.open("wb")


                dest_file.write(picture_buffer.read())
                dest_file.close()

            src_file.close()
            art_count += 1
        return art_count


    def get_game_title_csv_location(self, console: str = "PS1"):
        match self.operation_state:
            case self.OperationState.ONLINE:
                return f"{self.storage_location}{console}_LIST.CSV"
            case self.OperationState.FILESYSTEM:
                return 'file://' + \
                    quote(str(self.storage_location.joinpath(
                        "{console}_LIST.CSV")))
            case _:
                raise DisabledException(
                    "Storage features disabled, code should not have reached this point")

    def get_game_title(self, region_code: str) -> str | None:
        """Retrieve game title from the storage game title CSVs

        Returns None if title cannot be found
        """

        if self.index:
            title = self.index.get_title_for_game(region_code)
            if title:
                return title
        # On the august backup there are PS2 games located in PS1_LIST.CSV and vice versa....
        # Have to search both
        for console in ["PS1", "PS2"]:
            game_csv_location = self.get_game_title_csv_location(console)

            try:
                processed_csv = self.process_game_list_csv(
                    game_csv_location)
                try:
                    return processed_csv[region_code]
                except KeyError:
                    continue
            except HTTPError as e:
                print(
                    "Cannot find game list in online storage, not retrieving name for " + region_code, file=stderr)
            except URLError as e:
                print(
                    "Cannot find game list in storage, not retrieving name for " + region_code, file=stderr)
        print("Cannot find game " + region_code +
              " in PS1_LIST.CSV in the storage, not retrieving name.", file=stderr)
        return None


class DisabledException(Exception):
    pass
