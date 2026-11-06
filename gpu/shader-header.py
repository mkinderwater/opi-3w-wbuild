#!/usr/bin/env python3
import struct
import sys
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes()
if len(raw)%4 or raw[:4]!=b'\x03\x02\x23\x07':raise SystemExit('Invalid SPIR-V shader')
words=struct.unpack('<'+str(len(raw)//4)+'I',raw)
Path(sys.argv[2]).write_text('#include <stdint.h>\nstatic const uint32_t shader_words[] = {'+','.join(hex(w) for w in words)+'};\n')
