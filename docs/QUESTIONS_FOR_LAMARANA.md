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

---

## Open — data

### 1. Which layers belong on the map?

We hold data for **603** of their layers. Only **80** are currently offered as map
toggles; the rest are searchable and the assistant can answer from them, but they
are not in the panel.

This is a design limit, not a technical one. A panel of 600 layers is unusable,
and most would never be opened.

- Which layers does your team actually reach for in a typical week?
- Are there layers that matter for particular audiences — funders,
  municipalities, community workshops — even if rarely used?
- Is there a grouping you use in practice that differs from the categories on the
  inventory sheet?

*Our suggestion: a core of 30–50 that load fast and are properly labelled, with
the rest reachable through search.*

### 2. 42 layers we cannot find anywhere in the Drive

The catalogue listed 119 layers with no data. We went through all of them against
your Drive on 3 October, and most were our problem rather than yours: 46 are
already loaded and just not linked, 16 are in your Drive and we had not loaded
them, and 15 are PDF maps catalogued as though they were GIS layers.

That leaves **42 we cannot find under any name**, including Cuevas, Playas,
Islotes y cayos, Superfunds sites, Yacimientos arqueológicos, Hoteles OCT2014,
Puentes, RUTAS PÚBLICOS TERMINALES and the PREPA transmission data. The full list
is in `docs/DATA_GAPS.md`.

For each: is there a copy we have not been given, or was the row added in
anticipation of data you never received either?

Also worth knowing: the **AAA water and sewer network** — gravity lines, pump
stations, filtration plants, sampling points, 13 layers in total — is fully
documented in your reconstructed metadata workbook, but we hold none of the data.
Was it ever shared?

### 3. 46 metadata tabs do not match any layer name

The reconstructed metadata workbooks describe layers under the names used in the
GIS files — `habitat_1`, `pajaros`, `Hidrante`, `RUTAS_AMA` — while the inventory
catalogues them differently. We attach metadata only where the match is certain,
so 46 of 61 tabs are unattached rather than attached to a guess.

A list of the 46 can be sent. Which name is authoritative?

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

### 14. Ownership of the project and domain

The Google Cloud project and `mappealo.org` should end up in La Maraña's name.
Easier to register them to you now than transfer later.

### 15. What should support look like after handover, and for how long?

---

## How to use this file

Add a question the moment it comes up, with enough context that it can be read
cold. When a batch is sent, note the date. When an answer arrives, record it
under *Asked and answered* with what changed as a result — that section is the
record of why the system is the way it is.
