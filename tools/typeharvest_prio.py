import csv, re, sys, collections
d = "/data/attempts/typeharvest/"
STRICT = re.compile(r"^(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}$|^\+\d{1,3}[\s.-]\(?\d{1,4}\)?(?:[\s.-]\d{2,4}){2,4}$|^\d{2}[ .]\d{3}[ .]\d{2}[ .]\d{2}$|^00\d{2}[-\s]")
TOOLHOST = re.compile(r"(font|schema|cairo|matplotlib|pdf-tools|slic3r|bambulab|prusa|ultimaker|jsdelivr|cdn|googleapis|gstatic|cloudflare|unpkg|ns\.|xmlns|qt\.io|openxml|iteh\.ai)", re.I)
REALTLD = re.compile(r"\.(com|org|net|edu|gov|io|de|uk|fr|es|it|nl|ch|se|no|dk|fi|jp|cn|au|nz|ca|us|ru|pl|cz|be|at|br|in|eu|info|co|kr|tw|mx|ar|pt|gr|il|sg|hk|ie|ac\.\w\w)$", re.I)
keep = {"phone","address","email","username","host","url","projcode","partno:label","invented.segment","invented.dotted","invented","partno:filename","code"}
out = []
for r in csv.DictReader(open(d+"candidates.tsv"), delimiter="\t"):
    t, v = r["type"], r["value"]
    if t not in keep or r["in_registry"] == "full": continue
    files, occ, src = int(r["files"]), int(r["occ"]), r["sources"]
    if t == "phone" and not (STRICT.match(v) or not re.search(r"texthead|dxftext", src)): continue
    if t == "phone" and (re.fullmatch(r"(texthead|dxftext):\d+", src) or re.fullmatch(r"[\d ]+", v) and not STRICT.match(v)): continue
    if t == "url" and r["in_registry"]: continue
    if t == "email" and (not REALTLD.search(v) or re.search(r"\.(png|tlb|jpg)$", v)): continue
    if t in ("host","url") and TOOLHOST.search(v): continue
    if t == "invented.dotted" and re.search(r"\.(ttc|ttf|otf|eps|drw|ligo)$|^vnd\.", v): continue
    if t in ("code","partno:filename","invented") and files < 3: continue
    if t not in ("code","partno:filename","invented") and files < 2 and occ < 3: continue
    # score: spread + bonus for path/filename (cross-file links) and text (PDF scoring)
    score = files * (2 if r["also_filename"] else 1) * (1.5 if "pdftext" in src else 1)
    out.append((t, round(score,1), r))
out.sort(key=lambda x: (x[0], -x[1]))
cnt = collections.Counter()
with open(d+"priority.tsv","w") as f:
    f.write("type\tscore\tvalue\tocc\tfiles\tsources\tin_registry\talso_filename\tcontexts\n")
    for t, sc, r in out:
        cnt[t] += 1
        f.write("\t".join([t, str(sc)] + [r[k] for k in ("value","occ","files","sources","in_registry","also_filename","contexts")]) + "\n")
for t in sorted(cnt): print(t, cnt[t])
