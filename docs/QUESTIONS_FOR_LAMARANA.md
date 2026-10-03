# Open questions for La Maraña

A running list. Questions accumulate here as they come up, so they can be sent in
batches rather than one at a time — their team answers in Spanish, often needs to
check with colleagues, and a trickle of single questions is harder for them than
a considered list.

**Append, don't rewrite.** Mark answers inline with the date, so the history of
what was asked and what came back stays readable.

Last updated: 2026-10-02 · figures measured against the live system that day

---

## Asked and answered

**Does the format change work for us?** *(asked by Ailani, Sep 2026)*
Yes. Adding "source" and "metadata status" to the original format works — both
already exist on our side, and metadata status uses their own vocabulary
(confirmed / inferred / reconstructed / unknown), which the product displays.
Ahmed also asked for publication date and update date, which we can take even
where blank. **Answered.** One warning given: the import matches their column
headers by exact name, so renaming one silently stops that field loading.

**Do edits to the Drive sheet reach the backend automatically?** *(asked by Ailani)*
No. The import is a manual run against a downloaded copy. **Answered**, and a
scheduled sync is now on our roadmap.

**Can the system support units smaller than the municipality later?** *(asked by
La Maraña, 22 Jul 2026: "we would like to know whether the system can be designed
to support additional reference units in the future, such as barrios or parcels")*
Yes, and as of 3 October it does. Municipio remains the primary unit as they
asked, and **902 barrios and 713 comunidades especiales** are now resolvable:
"¿Cuántas escuelas hay en Santurce?" answers for the barrio, not for all of San
Juan. Parcels are not in yet. **Worth telling them** — it was their question and
it is now done.

**Is the GIS set complete?** *(stated by La Maraña, 11 Sep 2026)*
Yes: *"This is the completed gdb and we are not planning on adding anything else
given the scale of it (contains 600 layers)."* So the catalogue rows we cannot
find are almost certainly older inventory entries that never made it into the
final geodatabase, rather than files still to come. That reframes question 2 —
it is a question about **the catalogue**, not about missing deliveries.

---

## Open — data

### 1. Which layers belong on the map? — THEY ALREADY ANSWERED THIS

**Ailani sent a prioritised shortlist on 28 July 2026**, as an attachment to the
"Technical details for setting up Mappa data pipelines" thread: *"the short list
of the layers we consider reliable enough to prioritize first based on their
publication date and the metadata available."*

That file was never used. The 80 layers currently on the map were chosen by us.

**Action is ours, not theirs:** retrieve that attachment and set the map from it.
It is not in the Drive folders they shared — it went to the NYU mailbox only. Do
not re-ask them for it.

Still worth confirming once the list is applied:
- Has the shortlist changed since July, now that the metadata work is finished?
- Are there layers that matter for particular audiences — funders,
  municipalities, community workshops — even if rarely used?

### 2. 71 catalogue rows with no data anywhere

The catalogue listed 119 layers with no data. We went through all of them against
your Drive on 3 October. Much of it was our problem rather than yours: 17 are
duplicate catalogue rows for layers that are already live under a different GIS
ID, 13 describe a geodatabase or folder whose contents are already loaded under
their own names, 3 are in your Drive and we had not loaded them, and 15 are PDF
maps catalogued as though they were GIS layers.

That leaves **71 we cannot find under any name**, including Cuevas, Playas,
Islotes y cayos, Superfunds sites, Yacimientos arqueológicos, Hoteles OCT2014,
Puentes, RUTAS PÚBLICOS TERMINALES and the PREPA transmission data. The full list
is in `docs/DATA_GAPS.md`.

You told us in September that the geodatabase is complete and nothing more is
coming, and we hold 603 layers with data — so these are most likely older
inventory rows that never made it into the final file. **Can they be retired?**
If any of them describe something you still intend to produce, we will keep the
row and leave room for it.

Also worth knowing: the **AAA water and sewer network** — gravity lines, pump
stations, filtration plants, sampling points, 13 layers in total — is fully
documented in your reconstructed metadata workbook, but we hold none of the data.
Was it ever shared?

### 3. Seven metadata tabs that could describe more than one layer

Your reconstructed metadata now attaches to **24 layers**, up from 15. Nine tabs
were matched by hand where the name differed only in spelling — `Hidrante` is
our `hidrantes`, `peces_1` is our `peces`.

Seven we have left unattached, because each could describe two to four of the
layers you sent and nothing in the tab says which:

| Your tab | Could be |
|---|---|
| `Refugios` (FEMA certified, 2015) | refugios 2009, refugios 2023, FWS refuges |
| `Desalojo` | four tsunami-evacuation layers |
| `Residenciales` | residenciales 2009, residenciales públicos 2009 |
| `Comunidades_Especiales` | three comunidades especiales layers |
| `Critical_wildlife` and `Critical_Wildlife_Areas_20` | two critical wildlife layers |
| `TREN_URBANO_DETALLE` | four Tren Urbano layers |

Which layer does each describe? We would rather leave provenance blank than
attach it to the wrong layer — it is a claim about where a number came from.

The other 30 tabs describe layers we do not hold, including the whole **AAA water
and sewer network** (13 layers). See question 2.

### 4. Communities that are not in any boundary layer

We can now answer questions about 902 barrios and 713 comunidades especiales.
But several places that appear in your own documents have no boundary:
**Villa Cañona**, **Caño Martín Peña**, **La Parguera**.

Is there a layer delimiting these, or are they known by barrio instead?

### 5. Accented municipality names are corrupt in the comunidades layer

In `Asentamientos_Delimitacion_Comunidades_Especiales_2006`, the municipality
column is damaged in **139 of its 713 rows**. The accented character is replaced
by a different one in each row, so Añasco appears as *Aaasco*, *Aeasco*,
*Aiasco*, *Aoasco*, *AOasco* and *Asasco*; Bayamón has eleven spellings and
Canóvanas ten. The community names themselves look intact.

We no longer read that column — each community's municipality is worked out from
where its polygon sits, which the 78 municipality boundaries give reliably. So
nothing is blocked. But it suggests the file was converted through an encoding
that lost the accents, and **if this is your working copy, other columns in it
may have the same damage**. Worth checking against the original.

### 6. Two duplicate rows on the inventory

`Census2020` and `Agroturismo_2021` each appear twice under different GIS IDs,
with different categories and sources. Which row is authoritative?

### 7. 96 documents on the inventory have no file

Mostly municipal Planes de Mitigación — Adjuntas, Aguadilla, Dorado, Loíza,
Peñuelas among them. The inventory lists a link but no file was supplied.

- Do you have the files? We would rather take them from you than download from
  the original sites.
- If not, may we download from the link you listed? *(We will not download
  anything you have not listed.)*

### 8. 70 documents are scans with no searchable text

We can read them with OCR, and early results on your Spanish text are good. Do
digital originals exist for any of them? Legal texts in particular — a mistake in
an OCR'd reglamento is worse than not having it.

Three of the 70 are map sheets rather than documents (`GIS-001`, `GIS-010`,
`GIS-014`) and are excluded rather than read as noise.

### 9. Documents with no title on the sheet

`POT-047.2`, `POT-067.4`, `POT-067.5` are listed by ID with the title field empty
or repeated. These look like multi-part documents the sheet has not caught up
with.

---

## Open — product

### 10. Who is this for?

The decision that shapes the most, and it is not yet answered.

- Your team only, municipalities, community organisations, or the general public?
- Roughly how many people, and how often?
- Should anyone with the link be able to use it, or should access be controlled?
  *It is currently open to anyone with the address — fine for demonstrations, but
  a decision worth making deliberately.*
- Is any data not for public view — sensitive sites, community-submitted
  information, anything held under agreement with a municipality?

### 11. Spanish-first, or English equal?

Both work today. It affects what we prioritise, and whether layer names get
English translations.

---

## Open — handover

### 12. Who maintains this after April 2027?

Is there someone technical on your team, or would you work with a contractor?
This changes how we build — a team without an engineer needs a markedly simpler
system.

### 13. Running cost

Roughly **$55/month** today (database, storage, hosting) plus usage of about
**$0.04 per 100 questions**. That becomes your cost at handover. Worth confirming
it is workable before we build more on top of it.

### 14. Is the name settled, and is it the right domain?

They raised a real concern on 28 July and it was never closed out: *"We like the
name MAPPA but are not fully convinced because we believe it might create a lot
of confusion when we publish and share it in Puerto Rico."* They preliminarily
picked **`Mappapr.org`** and asked for marketing input, which nobody gave.

Since then we bought **`mappealo.org`**, branded the product **Mappa**, and put it
live. That decision was ours, not theirs, and it went past an open question they
had asked for help with.

- Is `mappealo.org` the name you want, or should the live site move?
- Did you ever register `Mappapr.org`?

Better to change this now than after it is printed on anything.

### 15. Ownership of the project and domain

The Google Cloud project and the domain should end up in La Maraña's name. They
confirmed on 22 July that **prsostenible@lamarana.org** is the address to use and
chose Option A — built on NYU's side, transferred to them later. Worth agreeing
the date for that transfer.

### 16. What should support look like after handover, and for how long?

---

## How to use this file

Add a question the moment it comes up, with enough context that it can be read
cold. When a batch is sent, note the date. When an answer arrives, record it
under *Asked and answered* with what changed as a result — that section is the
record of why the system is the way it is.
