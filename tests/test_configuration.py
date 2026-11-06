import sys
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'lib'))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
firstboot = load('firstboot', BASE/'overlay/firstboot.py')


class ConfigurationTests(unittest.TestCase):
    def config(self):
        return 'SSID= Room=1\r\nPSK= abc=def\\ghi\r\nCOUNTRY=CA\r\nHIDDEN=false\r\nTIMEZONE=America/Edmonton\r\nROOT_PASSWORD=good$pass123\r\n'
    def test_literal_values_and_wpa_profile(self):
        values = firstboot.parse(self.config())
        self.assertEqual(values['SSID'], ' Room=1')
        self.assertEqual(values['PSK'], ' abc=def\\ghi')
        content = firstboot.profile(values, '12345678-1234-1234-1234-123456789abc')
        self.assertIn('ssid='+';'.join(str(b) for b in values['SSID'].encode())+';', content)
        self.assertNotIn(values['PSK'], content)
        self.assertIn('autoconnect=true', content)
    def test_known_wpa_vector(self):
        content = firstboot.profile({'SSID':'IEEE','PSK':'password','HIDDEN':'false'},'12345678-1234-1234-1234-123456789abc')
        self.assertIn('f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e', content)
    def test_scrub_only_secrets(self):
        result = firstboot.scrub(self.config())
        self.assertIn('SSID= Room=1\n', result)
        self.assertIn('PSK=\n', result)
        self.assertIn('ROOT_PASSWORD=\n', result)
        self.assertNotIn('good$pass', result)
    def test_bad_config(self):
        for change in ('COUNTRY=ca', 'HIDDEN=yes', 'TIMEZONE=../../etc/shadow','ROOT_PASSWORD=x'):
            key = change.partition('=')[0]
            lines = self.config().splitlines()
            text = '\n'.join(change if l.startswith(key+'=') else l for l in lines)
            with self.assertRaises(ValueError): firstboot.parse(text)
        with self.assertRaises(ValueError): firstboot.parse(self.config()+'SSID=duplicate\n')
    def test_atomic_write_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config'
            firstboot.atomic(p, 'value')
            self.assertEqual(p.read_text(), 'value')
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
