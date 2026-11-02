"""Tests for binary XML and XML stream decoding."""

import struct
import unittest
import xml.etree.ElementTree as ET

from audacity_to_reaper.aup3_reader import (
    FT_CharSize,
    FT_Double,
    FT_EndTag,
    FT_Float,
    FT_Int,
    FT_Name,
    FT_StartTag,
    FT_String,
    decode_audacity_binary_xml,
)


class TestBinaryXMLDecoding(unittest.TestCase):
    """Test suite for Audacity ProjectSerializer binary XML stream decoder."""

    def test_empty_stream(self):
        result = decode_audacity_binary_xml(b"")
        self.assertIsNone(result)

    def test_basic_tree_utf16le(self):
        """Test encoding and decoding a basic project tree with UTF-16LE strings."""
        names = ["project", "wavetrack", "name", "rate", "gain", "pan"]
        stream = bytearray()

        # FT_CharSize = 2 (UTF-16LE)
        stream.append(FT_CharSize)
        stream.append(2)

        # Dictionary names
        for idx, name in enumerate(names):
            stream.append(FT_Name)
            bname = name.encode("utf-16le")
            stream.extend(struct.pack("<HH", idx, len(bname)))
            stream.extend(bname)

        # <project rate="48000">
        stream.append(FT_StartTag)
        stream.extend(struct.pack("<H", 0))  # project
        stream.append(FT_Double)
        stream.extend(struct.pack("<H", 3))  # rate
        stream.extend(struct.pack("<d", 48000.0))
        stream.extend(struct.pack("<i", -1))

        #   <wavetrack name="Vocal Lead" gain="1.5" pan="-0.5">
        stream.append(FT_StartTag)
        stream.extend(struct.pack("<H", 1))  # wavetrack
        stream.append(FT_String)
        stream.extend(struct.pack("<H", 2))  # name
        bval = "Vocal Lead".encode("utf-16le")
        stream.extend(struct.pack("<i", len(bval)))
        stream.extend(bval)

        stream.append(FT_Float)
        stream.extend(struct.pack("<H", 4))  # gain
        stream.extend(struct.pack("<f", 1.5))
        stream.extend(struct.pack("<i", -1))

        stream.append(FT_Float)
        stream.extend(struct.pack("<H", 5))  # pan
        stream.extend(struct.pack("<f", -0.5))
        stream.extend(struct.pack("<i", -1))

        #   </wavetrack>
        stream.append(FT_EndTag)
        stream.extend(struct.pack("<H", 1))

        # </project>
        stream.append(FT_EndTag)
        stream.extend(struct.pack("<H", 0))

        root = decode_audacity_binary_xml(bytes(stream))
        self.assertIsNotNone(root)
        self.assertEqual(root.tag, "project")
        self.assertEqual(root.attrib.get("rate"), "48000")

        children = list(root)
        self.assertEqual(len(children), 1)
        track = children[0]
        self.assertEqual(track.tag, "wavetrack")
        self.assertEqual(track.attrib.get("name"), "Vocal Lead")
        self.assertEqual(track.attrib.get("gain"), "1.5")
        self.assertEqual(track.attrib.get("pan"), "-0.5")

    def test_utf8_strings(self):
        """Test decoding when char_size = 1 (UTF-8)."""
        names = ["project", "title"]
        stream = bytearray()
        stream.append(FT_CharSize)
        stream.append(1)  # 1 byte per char

        for idx, name in enumerate(names):
            stream.append(FT_Name)
            bname = name.encode("utf-8")
            stream.extend(struct.pack("<HH", idx, len(bname)))
            stream.extend(bname)

        stream.append(FT_StartTag)
        stream.extend(struct.pack("<H", 0))
        stream.append(FT_String)
        stream.extend(struct.pack("<H", 1))
        val = "Podcast Episode 1".encode("utf-8")
        stream.extend(struct.pack("<i", len(val)))
        stream.extend(val)
        stream.append(FT_EndTag)
        stream.extend(struct.pack("<H", 0))

        root = decode_audacity_binary_xml(bytes(stream))
        self.assertIsNotNone(root)
        self.assertEqual(root.tag, "project")
        self.assertEqual(root.attrib.get("title"), "Podcast Episode 1")


if __name__ == "__main__":
    unittest.main()
