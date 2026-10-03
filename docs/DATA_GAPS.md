# Where the missing layer data actually is

Measured 3 October 2026 against their Drive and our database.

> **Status, end of 3 Oct:** the 17 duplicate rows are now marked `duplicate` and
> point at the row holding their data — catalogued is 102, not 119. Their
> reconstructed metadata attaches to 24 layers, up from 15. Of the 16 datasets
> found in their Drive, 13 turned out to be loaded already under their inner
> layer names; 3 genuinely are not.

The catalogue says **119 layers have no data**. That number had never been taken
apart. It is four different problems, and only one of them is theirs.

| | count | whose |
|---|---|---|
| Duplicate catalogue row — the layer is live under a different GIS ID | **17** | ours, retire the row |
| The file is in their Drive and we never loaded it | **3** | ours, load it |
| Catalogue row describes a container whose contents *are* loaded | **13** | ours, mark it |
| Catalogued as a layer but it is a PDF map image | **15** | ours, re-file |
| No data found anywhere | **71** | ask them |

**Two earlier counts in this file were wrong and are corrected above.** The first
pass matched layer names with a loose substring rule, which paired *Deslizamientos
PRMaria* with the unrelated `layer_deslizamiento` and inflated the "already
loaded" group to 46. The second pass found 25 tables that no live registry row
pointed at and read them as lost data; they are superseded duplicates, each with
a newer registered copy. **No layer data is unreachable.** The PREPA grid, the
census blocks and the hydrography are all live under their newer table names.

---

## 1. Duplicate catalogue rows (17)

The layer works. The catalogue simply lists it twice, under two GIS IDs, and the
second row has nothing behind it. Agroturismo 2021 appears three times.

Retiring these rows changes nothing a user can see; it makes the catalogue
honest, and it removes 17 from the "missing" figure that has been quoted to
everyone including La Maraña.

| GIS ID | Layer | Live table holding the data |
|---|---|---|
| GIS-017 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-032 | Refugios 2023 | `layer_refugios_2023` |
| GIS-033 | ResidencialesPublicos 2009 | `layer_residenciales_publicos_2009` |
| GIS-114 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-216 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-328 | Hospitales | `layer_hospitales` |
| GIS-343 | proteccion epa facility registry system 2011 | `layer_g11_proteccion_epa_facility_registry_system_2011` |
| GIS-349 | refugios 2023 | `layer_refugios_2023` |
| GIS-368 | Huellas de Edificios PR USVI 2018 | `layer_huellas_de_edificios_pr_usvi_2018` |
| GIS-375 | Residenciales publicos 2009 | `layer_residenciales_publicos_2009` |
| GIS-392 | electorales dist representativos 2012 | `layer_electorales_dist_representativos_2012` |
| GIS-393 | electorales dist senatoriales 2012 | `layer_electorales_dist_senatoriales_2012` |
| GIS-394 | electorales precintos 2004 | `layer_electorales_precintos_2004` |
| GIS-395 | electorales unidades electorales 2004 | `layer_electorales_unidades_electorales_2004` |
| GIS-397 | legales municipios 2015 | `layer_legales_municipios_2015` |
| GIS-556 | turismo balnearios | `layer_turismo_balnearios` |
| GIS-596 | carreteras estatales segmentadas agosto 2021 | `layer_carreteras_estatales_segmentadas_agosto_2021` |

---

## 2. Found in their Drive — and 13 of 16 turn out to be loaded already

These 16 were found by name in their Drive. Checked against the database by
*meaning* rather than by name, **13 are already loaded**. A `.gdb` or a folder is
a container: the catalogue row describes the container, while the data inside it
was loaded as several layers under their own names. `download_prepa_geodata_2014.gdb`
is one catalogue row and roughly forty live layers — transmission lines,
distribution structures, switching units, generation sites.

**Already live (13)** — the catalogue row describes a container whose contents are loaded:

| GIS ID | Catalogue row | Where the data is |
|---|---|---|
| GIS-016 | Areas Protegidas 2018 (PACAT) | `pacat_2018_areas_protegidas_terrestres`, `_marinas`, `_zonas_amortiguamientos` |
| GIS-019, GIS-077 | Census2020 | `censo_2020` |
| GIS-024 | FincasAdmTerrenos 2014 | `bienes_raices_propiedades_admin_terrenos_2014` |
| GIS-025 | Corredor agrícola del sur | `corredor_agricola_de_project_exportfeatures` |
| GIS-027 | Desalojo Tsunami 2003/2012 | `areas_desalojo_tsunami_2003_2014` |
| GIS-029 | InfraestructuraAEE | 18 AEE layers — transmission, distribution, substations |
| GIS-030 | Parcelas PRIDCO | `propiedades_pridco_parcelas`, `_estructuras` |
| GIS-037 | ZonasInundables 2009 | `inundacion_fema_firms_2009` |
| GIS-038 | Tsunami Flood Zone 2012 | `areas_de_inundacion_por_tsunami_de_puerto_rico` |
| GIS-088 | download_prepa_geodata_2014.gdb | the PREPA 2014 set — ~40 layers |
| GIS-090 | GDB_NAD83_2011.gdb | `cdt_2011`, `hospitales2011`, `tanques_almac_soterrados_2011` |
| GIS-106 | DependenciasDRNA 2010 | `dotacional_dependencias_dept_recursos_naturales_2010` |

These rows are not marked in the database yet. The one-to-one cases are clear,
but a container mapping to several layers is a judgement worth a second look
before it is recorded as fact.

**Genuinely not loaded (3)** — the file is in their Drive and nothing in the
database corresponds:

| GIS ID | Layer | Folder in their Drive |
|---|---|---|
| GIS-031 | PlazasPublicas 2010 | `Capas GIS/GIS/PlazasPublicas_2010` |
| GIS-034 | Response Report | `Capas GIS/GIS/Response_Report` |
| GIS-035 | SHP-LIDAR | `Capas GIS/GIS/SHP-LIDAR` |

`SHP-LIDAR` is likely large and may be elevation tiles rather than vector data;
worth opening before committing to load it.

---

## 3. PDFs catalogued as layers (15)

Map *images* — "Mapa de clasificación de suelo de la Reserva Agrícola del Valle
de Lajas" and similar. Documents, not spatial data. They belong in the document
corpus, where their text becomes searchable.

| GIS ID | Title |
|---|---|
| GIS-001 | Mapa clasificacion de suelo de la Reserva Agrícola Costa Norte |
| GIS-002 | Mapa calificacion de suelo y delimitacion de la Reserva Natural Camuy |
| GIS-003 | Mapa de clasificacion de suelo Mar Chiquita |
| GIS-004 | Mapa de calificacion de suelo y delimitacion Mar Chiquita |
| GIS-005 | Mapa delimitacion y clasificacion de suelo de Plan Sectorial de La Reserva Natural San Cristobal |
| GIS-006 | Mapa delimitacion y calificacion de suelo del Cañon San Cristobal y delimitación de La Reserva Natural San Cristobal |
| GIS-007 | Mapa de calificacion de suelo y delimitacion de la Reserva Natural Punta Guilarte |
| GIS-008 | Mapa de clasificacion de suelo de la Reserva Natural Punta Guilarte |
| GIS-009 | Mapa de delimitacion y designación Reserva Natural Finca Nolla |
| GIS-010 | Mapas ampliados de delimitacion y designación Reserva Natural Finca Nolla |
| GIS-011 | Mapa de calificacion de suelo y enmienda de delimitacion de la Reserva Natural Punta Petrona |
| GIS-012 | Mapa de clasificacion de suelo de la Reserva Natural Punta Petrona |
| GIS-013 | Mapa de calificacion de suelo y delimitacion de la Reserva Natural Punta Cabullones |
| GIS-014 | Mapa de clasificacion de suelo de la Reserva Natural Punta Cabullones |
| GIS-015 | Mapa de delimitacion, clasificacion y calificación Plan Sectorial Reserva Natural Planadas Yeyesa |

---

## 4. No data found (71)

Searched by catalogue name and by the filename their inventory gives, across every
folder shared with us.

**La Maraña said on 11 September:** *"This is the completed gdb and we are not
planning on adding anything else given the scale of it (contains 600 layers)."*
We hold 603 layers with data. So these are almost certainly **older inventory rows
that never made it into the final geodatabase**, rather than files still to come.

That makes this a question about the catalogue, not a chase for missing files:
*should these rows be retired, or do they describe something you still intend to
produce?*

| GIS ID | Layer | Format claimed |
|---|---|---|
| GIS-018 | barrios 2015 | Geodatabase |
| GIS-021 | Deslizamientos PRMaria | Geodatabase |
| GIS-022 | Deslizamientos rainfall-induced 2022/2023 | CSV |
| GIS-023 | Finca Eólica de Santa Isabel | — |
| GIS-026 | Hidrografía 2006 | Shapefile |
| GIS-028 | Hospitales CDTs | Shapefile |
| GIS-036 | Vertederos | Shapefile |
| GIS-039 | Sequia 2026 | CSV |
| GIS-040 | landslide susceptibility | Tif |
| GIS-041 | Cobertura de terrenos | — |
| GIS-042 | PR Sea Level rise | gdb |
| GIS-043 | Rainfall, maximum and minimum temperature climatic scenario | gdb |
| GIS-044 | PUT | — |
| GIS-045 | FwsInterest and Approved PRVI | Shapefile |
| GIS-047 | g01 conserv gap stewardship | Shapefile |
| GIS-048 | g01 conserv linea vegetacion permanente 2007 | Shapefile |
| GIS-059 | geology 24jul18 | gdb |
| GIS-069 | g11 proteccion empresas pecuarias 2008 | Shapefile |
| GIS-070 | g11 proteccion epa facility registry system 2011 | Shapefile |
| GIS-071 | g11 proteccion fincas receptoras 2010 | Shapefile |
| GIS-075 | g09 puntuales alturas | — |
| GIS-078 | g03 electorales dist representativos 2012 | Shapefile |
| GIS-079 | g03 electorales dist senatoriales 2012 | Shapefile |
| GIS-080 | g03 electorales precintos 2004 | Shapefile |
| GIS-081 | g03 electorales unidades electorales 2004 | Shapefile |
| GIS-083 | g03 legales municipios 2015 | Shapefile |
| GIS-089 | g23 agricultura canal riego isabela | Shapefile |
| GIS-091 | g07 industrial urbanizaciones industriales | Shapefile |
| GIS-092 | g33 dotacional centros de gobierno aut edificios publicos 2010 | Shapefile |
| GIS-093 | g33 seguridad refugios 2023 | Shapefile |
| GIS-094 | Hospitales y CDT | Shapefile |
| GIS-096 | g35 colectiva tren urbano estaciones 2000 | Shapefile |
| GIS-097 | g35 maritima puertos 2010 | Shapefile |
| GIS-098 | g35 viales carreteras estatales segmentadas agosto 2021 | Shapefile |
| GIS-099 | tiger rds2006se | — |
| GIS-100 | USGS National Transportation Dataset (NTD) for Puerto Rico (published 20260212) | GDB |
| GIS-101 | ComunidadesEspeciales 2006 | Shapefile |
| GIS-102 | arpe permisos 1999 2010.gdb | GDB |
| GIS-105 | g33 dotacional educacion escuelas 2021 | Shapefile |
| GIS-107 | g07 turismo balnearios | Shapefile |
| GIS-110 | g31 recreacion bosque estatal monte choca centro visit 2012 | Shapefile |
| GIS-111 | g33 vivienda residenciales 2009 | Shapefile |
| GIS-126 | valles agricolas | Shapefile |
| GIS-191 | Areas aprobadas por el Servicio de Pesca y Vida Silvestre FWS en Puerto Rico e Is | Shapefile |
| GIS-194 | Areas de interes del Servicio de Pesca y Vida Silvestre FWS en Puerto Rico e Islas | Shapefile |
| GIS-195 | areas de manejo | Shapefile |
| GIS-205 | Cuevas Junta de Planificacion | Shapefile |
| GIS-210 | PRcosta2007 14April2010 editado 25nov2016 | Shapefile |
| GIS-246 | POSTES KM 2012 | Shapefile |
| GIS-270 | Cuevas | Shapefile |
| GIS-293 | Islotes y cayos | Shapefile |
| GIS-296 | Playas | Shapefile |
| GIS-316 | Centros Gobierno AEP 2007 | Shapefile |
| GIS-319 | Comunidades especiales centros | Shapefile |
| GIS-324 | escuela | Shapefile |
| GIS-330 | Hoteles OCT2014 | Shapefile |
| GIS-338 | merge rcra | Shapefile |
| GIS-351 | tanques soterrados | Shapefile |
| GIS-352 | Terrenos DVyAgencias puntos | Shapefile |
| GIS-360 | Yacimientos arqueologicos de Puerto Rico | Shapefile |
| GIS-373 | Proyectos estrategicos | Shapefile |
| GIS-376 | Superfunds sites | Shapefile |
| GIS-377 | Terrenos DVyAgencias | Shapefile |
| GIS-378 | Terrenos Excedentes AEP 2007 | Shapefile |
| GIS-381 | Vertederos de la Autoridad de Desperdicios Solidos | Shapefile |
| GIS-572 | Marejada Coclonica | Shapefile |
| GIS-605 | NUMEROS SALIDAS AUTOPISTAS | Shapefile |
| GIS-610 | Puentes REVISION abril 2016 | Shapefile |
| GIS-618 | Rutas de transporte publico SIMETRO | Shapefile |
| GIS-621 | RUTAS PUBLICOS TERMINALES 2010 | Shapefile |
| GIS-664 | Zona de interes turistico SanJuan | Shapefile |

**What the search does not prove.** A file stored under a different name, or
inside a geodatabase whose own name does not mention it, would not be found.
The honest claim is *not present under any name we know to look for*.

---

# The metadata workbooks

Five workbooks, **61 layer tabs**, of which 15 attach to a layer. The other 46:

## Describe a layer we have, under a different name (16)

Their files say `Hidrante`; our catalogue says `hidrantes`. An alias, not a
conversation. Each of these layers currently carries *inferred* metadata when
their team had already established the real source.

| Their tab | Our layer |
|---|---|
| Hidrante | `layer_hidrantes` |
| Contador | `layer_contadores` |
| habitat_1 | `layer_habitat` |
| mamiferos_marinos_1 | `layer_mamiferos_marinos` |
| mamiferos_terrestres_1 | `layer_mamiferos_terrestres` |
| peces_1 | `layer_peces` |
| reptiles_1 | `layer_reptiles` |
| Critical_Wildlife_Areas_20 | `layer_critical_wildlife_areas` |
| Balnearios | `layer_turismo_balnearios` |
| Comunidades_Especiales | `layer_comunidades_especiales_area` |
| Critical_wildlife | `layer_g01_conserv_critical_wildlife_areas` |
| Corredor_Agricola | `layer_corredor_agricola_de_project_exportfeatures` |
| Desalojo | `layer_zonas_desalojo_all_project` |
| Refugios | `layer_dotaciones_seguridad_refugios_2009` |
| Residenciales | `layer_residenciales_2009` |
| TREN_URBANO_DETALLE | `layer_tren_urbano` |

## Describe a layer we do not have (30)

`Línea_de_Gravedad`, `Tubería_Bombeo`, `Acometida_Sanitaria`, `Línea_Matriz`, `Línea_de_Servicio`, `Accesorio_de_Conexión`, `Estructura_Red`, `Estación_de_bombas`, `Estación_Bomba`, `Planta_Alcantarillado_Sani`, `Planta_de_filtracion`, `Punto_de_Muestreo`, `PuntoServicio`, `Metadata`, `invertebrados_poligonos_1`, `pajaros`, `esilr_1`, `esip_1`, `esile_1`, `CRIM`, `Empresas pecuarias`, `Flooding_Areas`, `Flood_1.00`, `Flood_0.2`, `Fincas_receptoras`, `geology_2018`, `Huellas_vertederos`, `Linea_vegetación`, `SistemaVial`, `RUTAS_AMA`

Thirteen are the **AAA water and sewer network** — gravity lines, pump stations,
filtration plants, sampling points. Their team documented the whole network and
we hold none of the data. It is the largest block of described-but-absent data,
and it is infrastructure a planning assistant gets asked about.

`Metadata` is the ACT highways workbook, which has one sheet rather than one per
layer — a format the importer does not read. Ours to fix.
