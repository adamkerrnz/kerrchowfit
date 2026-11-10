#!/usr/bin/env python3
"""Build the Claude-artifact version of index.html.

The artifact publisher adds its own <html>/<head>/<body> wrapper, so this strips
ours and writes the page content to the given path (default: artifact.html).
index.html is the single source; never edit the output by hand.
"""
import sys

src = open("index.html", encoding="utf-8").read()
head = src[src.index("<title>"):src.index("</head>")]
body = src[src.index("<body>") + len("<body>"):src.index("</body>")]
head = head.replace("</title>", '</title>\n<meta name="claude:viewport-fit-sides" content="cover">', 1)
out = sys.argv[1] if len(sys.argv) > 1 else "artifact.html"
open(out, "w", encoding="utf-8").write(head.strip() + "\n" + body.strip() + "\n")
print(f"wrote {out}")
