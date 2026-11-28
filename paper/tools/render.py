import sys, pymupdf
pdf, outp, pages, dpi = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 70
d = pymupdf.open(pdf); print("pages", d.page_count)
sel = range(d.page_count) if pages == "all" else [int(x) - 1 for x in pages.split(",")]
for i in sel:
    d[i].get_pixmap(dpi=dpi).save(f"{outp}-{i+1:02d}.png")
