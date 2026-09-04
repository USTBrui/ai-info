# -*- coding: utf-8 -*-
"""临时脚本：把 bat 转成 GBK 编码（先读后写，跑完即删）"""
import io

files = ['一键刷新.bat', '探测数据源.bat', '探测网页源.bat']

for name in files:
    text = io.open(name, encoding='utf-8').read()          # 1. 先完整读出来
    io.open(name, 'w', encoding='gbk', newline='\r\n').write(text)  # 2. 再写回去
    raw = io.open(name, 'rb').read()
    # 复核：确认内容是 GBK 且第一句正确
    text2 = io.open(name, encoding='gbk').read()
    print(f'{name}: {len(raw)} 字节, 首行={text2.splitlines()[0]!r}, 含中文={any(ord(c) > 127 for c in text2)}')
