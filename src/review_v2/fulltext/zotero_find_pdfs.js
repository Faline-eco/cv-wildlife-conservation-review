// "Find Available PDF" for the review papers that have no PDF yet, slowly and one at a time.
//
// Works on the items in the subcollections of the collection "literature_review3" whose names start with
// one of COLLECTIONS (the subcollections are named like the DOI lists in review_output/v2/fetch/).
//
// How to run (Zotero 7): Tools -> Developer -> Run JavaScript, paste this whole file, keep
// "Run as async function" ticked, press Run. The call returns at once; the work continues in the
// background as long as Zotero stays open.
//   Progress: review_output/v2/fetch/zotero_find_pdf_log.txt (rewritten after every paper)
//   Stop:     create an empty file review_output/v2/fetch/zotero_find_pdf_STOP (or close Zotero)
//   Resume:   run the script again; papers that have a PDF by then are skipped.

const DIR = "<repo>\\review_output\\v2\\fetch\\"  // set to your checkout;
const PARENT = "literature_review3";           // parent collection (case is ignored)
const COLLECTIONS = ["FINAL_5"];  // subcollections to work on (name prefix); FINAL_1/2 were run to the end on 2026-10-15, FINAL_4 on 2026-10-23
const SKIP_DOI = [/^10\.1007\/978-/, /^10\.1016\//];  // Springer book chapters: no institutional access; Elsevier: saved by hand
const PAUSE_S = 25;          // seconds between two papers
const LONG_PAUSE_EVERY = 50; // after this many requests ...
const LONG_PAUSE_S = 300;    // ... wait this long
const GIVE_UP_AFTER = 15;    // consecutive misses of one publisher before it is skipped for this run

// the subcollections, in every library (user library and groups)
const parents = [];
for (const lib of Zotero.Libraries.getAll()) {
    for (const c of Zotero.Collections.getByLibrary(lib.libraryID, true)) {
        if (c.name.trim().toLowerCase() == PARENT) parents.push(c);
    }
}
if (!parents.length) return `No collection named "${PARENT}" found.`;
const subs = parents.flatMap(p => Zotero.Collections.getByParent(p.id, true))
    .filter(c => COLLECTIONS.some(prefix => c.name.startsWith(prefix)));
if (!subs.length) return `No subcollection of "${PARENT}" starts with ${COLLECTIONS.join(" or ")}.`;

// DOI field, or "DOI: ..." in Extra (book sections have no DOI field)
function getDOI(item) {
    let doi = "";
    try { doi = item.getField("DOI") || ""; } catch (e) {}
    if (!doi) doi = ((item.getField("extra") || "").match(/^DOI:\s*(\S+)/im) || [])[1] || "";
    return doi.trim().toLowerCase().replace(/^https?:\/\/(dx\.)?doi\.org\//, "");
}

async function hasPDF(item) {
    for (const id of item.getAttachments()) {
        const att = await Zotero.Items.getAsync(id);
        if (att.attachmentContentType == "application/pdf" && await att.getFilePathAsync()) return true;
    }
    return false;
}

// items without PDF, grouped by publisher (DOI prefix), then interleaved so that no publisher is asked
// twice in a row while others are left
const stats = { items: 0, had_pdf: 0, skipped_doi: 0, todo: 0, found: 0, not_found: 0, error: 0,
    skipped_publisher: 0 };
const seen = new Set();
const groups = new Map();
for (const c of subs) {
    for (const item of c.getChildItems(false, false)) {
        if (!item.isRegularItem() || seen.has(item.id)) continue;
        seen.add(item.id);
        stats.items++;
        if (await hasPDF(item)) { stats.had_pdf++; continue; }
        const doi = getDOI(item);
        if (SKIP_DOI.some(re => re.test(doi))) { stats.skipped_doi++; continue; }
        const publisher = doi ? doi.split("/")[0] : "no-doi";
        if (!groups.has(publisher)) groups.set(publisher, []);
        groups.get(publisher).push(item);
    }
}
const queue = [];
const lists = [...groups.values()];
for (let i = 0; lists.some(l => i < l.length); i++) {
    for (const l of lists) if (i < l.length) queue.push(l[i]);
}
stats.todo = queue.length;

const sleep = s => new Promise(resolve => setTimeout(resolve, s * 1000));
const misses = {};   // publisher -> consecutive misses
const lines = [];

async function report(state) {
    const head = `${new Date().toISOString()}  ${state}  ${JSON.stringify(stats)}\n`
        + `collections: ${subs.map(c => c.name).join(", ")}\n`
        + `given up for this run: ${Object.keys(misses).filter(p => misses[p] >= GIVE_UP_AFTER).join(", ") || "-"}\n\n`;
    await Zotero.File.putContentsAsync(DIR + "zotero_find_pdf_log.txt", head + lines.join("\n") + "\n");
}

(async () => {
    let requests = 0;
    await report("started");
    for (const item of queue) {
        if (await IOUtils.exists(DIR + "zotero_find_pdf_STOP")) { await report("stopped by STOP file"); return; }
        const doi = getDOI(item);
        const label = doi || `[${item.key}] ${item.getField("title").slice(0, 60)}`;
        const publisher = doi ? doi.split("/")[0] : "no-doi";
        if ((misses[publisher] || 0) >= GIVE_UP_AFTER) { stats.skipped_publisher++; continue; }
        if (await hasPDF(item)) { stats.had_pdf++; continue; }   // e.g. added by hand meanwhile
        let result;
        try {
            const find = Zotero.Attachments.addAvailableFile || Zotero.Attachments.addAvailablePDF;
            const att = await find.call(Zotero.Attachments, item);
            result = att ? "found" : "not_found";
            lines.push(`${label}\t${result}`);
        }
        catch (e) {
            result = "error";
            lines.push(`${label}\terror\t${String(e).slice(0, 150)}`);
        }
        stats[result]++;
        misses[publisher] = result == "found" ? 0 : (misses[publisher] || 0) + 1;
        requests++;
        await report("running");
        await sleep(requests % LONG_PAUSE_EVERY == 0 ? LONG_PAUSE_S : PAUSE_S);
    }
    await report("finished");
})().catch(e => Zotero.logError(e));

return `Started: ${stats.todo} items without PDF in ${subs.map(c => c.name).join(", ")} `
    + `(${stats.items} items, ${stats.had_pdf} with PDF). Progress in ${DIR}zotero_find_pdf_log.txt`;
