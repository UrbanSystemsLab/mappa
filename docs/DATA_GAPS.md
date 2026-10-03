# Where the missing layer data actually is

Measured 3 October 2026, against their Drive and our database.

The catalogue said **119 layers have no data**. That number was never examined,
and it turns out to be four different problems with four different owners. Only
42 of them are a question for La Maraña. The rest are ours.

| | count | whose |
|---|---|---|
| Data is already loaded — the catalogue row just is not linked to it | **46** | ours, today |
| The file is in their Drive and we never loaded it | **16** | ours, this week |
| Catalogued as a layer but it is a PDF map image, not GIS data | **15** | ours, re-file |
| Not found anywhere in their Drive under any name we can match | **42** | **ask them** |

---

## 1. Already loaded, not linked (46 layers)

The data is in the database and working. The catalogue row points at nothing, so
the layer is invisible to the map and the assistant. This is the same registry
drift that removed 26 layers from the map in September — loading their second
GeoPackage re-matched rows onto the new file's copies and stranded the rest.

Nothing needs to be asked or downloaded. These can be relinked today.

| GIS ID | Layer | Table that holds its data |
|---|---|---|
| GIS-017 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-018 | barrios 2015 | `layer_barrios_2015_corrected_16_nov17` |
| GIS-021 | Deslizamientos PRMaria | `layer_deslizamiento` |
| GIS-022 | Deslizamientos rainfall-induced 2022/2023 | `layer_deslizamiento` |
| GIS-026 | Hidrografía 2006 | `layer_mapa_base_crim_ogp_hidrografia_2006` |
| GIS-028 | Hospitales CDTs | `layer_hospitales` |
| GIS-032 | Refugios 2023 | `layer_refugios_2023` |
| GIS-033 | ResidencialesPublicos 2009 | `layer_residenciales_publicos_2009` |
| GIS-036 | Vertederos | `layer_vertederos_en_operacion` |
| GIS-070 | g11 proteccion epa facility registry system 2011 | `layer_g11_proteccion_epa_facility_registry_system_2011` |
| GIS-078 | g03 electorales dist representativos 2012 | `layer_g03_electorales_dist_representativos_2012` |
| GIS-079 | g03 electorales dist senatoriales 2012 | `layer_g03_electorales_dist_senatoriales_2012` |
| GIS-080 | g03 electorales precintos 2004 | `layer_g03_electorales_precintos_2004` |
| GIS-081 | g03 electorales unidades electorales 2004 | `layer_g03_electorales_unidades_electorales_2004` |
| GIS-083 | g03 legales municipios 2015 | `layer_g03_legales_municipios_2015` |
| GIS-089 | g23 agricultura canal riego isabela | `layer_canal_riego_isabela` |
| GIS-091 | g07 industrial urbanizaciones industriales | `layer_urbanizaciones_industriales` |
| GIS-092 | g33 dotacional centros de gobierno aut edificios publicos 2010 | `layer_edificios_publicos_2010` |
| GIS-093 | g33 seguridad refugios 2023 | `layer_refugios_2023` |
| GIS-094 | Hospitales y CDT | `layer_hospitales` |
| GIS-096 | g35 colectiva tren urbano estaciones 2000 | `layer_tren_urbano_estaciones_2000` |
| GIS-097 | g35 maritima puertos 2010 | `layer_puertos_2010` |
| GIS-098 | g35 viales carreteras estatales segmentadas agosto 2021 | `layer_carreteras_estatales_segmentadas_agosto_2021` |
| GIS-101 | ComunidadesEspeciales 2006 | `layer_g31_asentamientos_delim_comunidades_especiales_2006` |
| GIS-105 | g33 dotacional educacion escuelas 2021 | `layer_dotacional_educacion_escuelas_2021` |
| GIS-107 | g07 turismo balnearios | `layer_turismo_balnearios` |
| GIS-111 | g33 vivienda residenciales 2009 | `layer_residenciales_2009` |
| GIS-114 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-126 | valles agricolas | `layer_conservacion_de_valles_agricolas_1` |
| GIS-191 | Areas aprobadas por el Servicio de Pesca y Vida Silvestre FWS en Puerto Rico e Is | `layer_areas_aprobadas_por_el_servicio_de_pesca_y_vida_silvestre` |
| GIS-194 | Areas de interes del Servicio de Pesca y Vida Silvestre FWS en Puerto Rico e Islas | `layer_areas_de_interes_del_servicio_de_pesca_y_vida_silvestre_f` |
| GIS-216 | Agroturismo 2021 | `layer_agroturismo_2021` |
| GIS-328 | Hospitales | `layer_hospitales` |
| GIS-343 | proteccion epa facility registry system 2011 | `layer_proteccion_epa_facility_registry_system_2011` |
| GIS-349 | refugios 2023 | `layer_refugios_2023` |
| GIS-351 | tanques soterrados | `layer_tanques` |
| GIS-368 | Huellas de Edificios PR USVI 2018 | `layer_huellas_de_edificios_pr_usvi_2018` |
| GIS-375 | Residenciales publicos 2009 | `layer_residenciales_publicos_2009` |
| GIS-392 | electorales dist representativos 2012 | `layer_electorales_dist_representativos_2012` |
| GIS-393 | electorales dist senatoriales 2012 | `layer_electorales_dist_senatoriales_2012` |
| GIS-394 | electorales precintos 2004 | `layer_electorales_precintos_2004` |
| GIS-395 | electorales unidades electorales 2004 | `layer_electorales_unidades_electorales_2004` |
| GIS-397 | legales municipios 2015 | `layer_legales_municipios_2015` |
| GIS-556 | turismo balnearios | `layer_turismo_balnearios` |
| GIS-572 | Marejada Coclonica | `layer_marejada_coclonica_general` |
| GIS-596 | carreteras estatales segmentadas agosto 2021 | `layer_carreteras_estatales_segmentadas_agosto_2021` |

---

## 2. In their Drive, never loaded (16 layers)

Found by searching their Drive on 3 October. Every one of these exists as a
folder or geodatabase under `Capas GIS`. We loaded two GeoPackages and stopped;
these were never picked up.

| GIS ID | Layer | Folder in their Drive |
|---|---|---|
| GIS-016 | Areas Protegidas 2018 | `Areas_protegidas2018_PACAT` |
| GIS-019 | Census2020 | `Census2020.lpkx` |
| GIS-024 | FincasAdmTerrenos 2014 | `FincasAdmTerrenos` |
| GIS-025 | Corredor agricola del sur 2010 | `corredor_agricola_del_sur` |
| GIS-027 | Desalojo Tsunami 2003/2012 | `DesalojoTsunami_2003_2012.gdb` |
| GIS-029 | InfraestructuraAEE | `InfraestructuraAEE` |
| GIS-030 | Parcelas PRIDCO | `Parcelas_PRIDCO` |
| GIS-031 | PlazasPublicas 2010 | `PlazasPublicas_2010` |
| GIS-034 | Response Report | `Response_Report` |
| GIS-035 | SHP-LIDAR | `SHP-LIDAR` |
| GIS-037 | ZonasInundables 2009 | `ZonasInundables_2009` |
| GIS-038 | Tsunami Flood Zone 2012 | `Tsunami_Flood_Zone_2012.gdb` |
| GIS-077 | Census2020 | `Census2020.lpkx` |
| GIS-088 | download prepa geodata 2014.gdb | `download_prepa_geodata_2014.gdb` |
| GIS-090 | GDB NAD83 2011.gdb | `GDB_NAD83_2011.gdb` |
| GIS-106 | DependenciasDRNA 2010 | `DependenciasDRNA_2010` |

Two caveats worth stating before anyone counts these as solved:

- **`Census2020.lpkx` is an ArcGIS layer package**, not a shapefile or a
  geodatabase. It needs converting before it can be loaded, and the conversion
  is lossy in ways we should check with them rather than guess at.
- Their own folder names flag several as unfinished: `Datos Censo_INCOMPLETO`,
  `DesalojoTsunami_2014 INCOMPLETO`, `AreasNaturalesProtegidasTerrestres_2019_INCOMPLETO`,
  `CorredorAgricolaSur_INCOMPLETO`. They already know these are partial.

---

## 3. Catalogued as layers, but they are PDFs (15 rows)

These are map *images* — "Mapa de clasificación de suelo de la Reserva Agrícola
del Valle de Lajas" and similar. They are documents, not spatial data, and no
amount of loading will turn them into layers. They belong in the document corpus,
where their text would be searchable.

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

## 4. Not found in their Drive (42 layers)

**This is the only list that is a question for La Maraña.** Each was searched for
by its catalogue name and by the filename their inventory gives, across every
folder shared with us. Nothing matched.

| GIS ID | Layer | Format the inventory claims |
|---|---|---|
| GIS-023 | Finca Eólica de Santa Isabel | — |
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
| GIS-071 | g11 proteccion fincas receptoras 2010 | Shapefile |
| GIS-075 | g09 puntuales alturas | — |
| GIS-099 | tiger rds2006se | — |
| GIS-100 | USGS National Transportation Dataset (NTD) for Puerto Rico (published 20260212) | GDB |
| GIS-102 | arpe permisos 1999 2010.gdb | GDB |
| GIS-110 | g31 recreacion bosque estatal monte choca centro visit 2012 | Shapefile |
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
| GIS-352 | Terrenos DVyAgencias puntos | Shapefile |
| GIS-360 | Yacimientos arqueologicos de Puerto Rico | Shapefile |
| GIS-373 | Proyectos estrategicos | Shapefile |
| GIS-376 | Superfunds sites | Shapefile |
| GIS-377 | Terrenos DVyAgencias | Shapefile |
| GIS-378 | Terrenos Excedentes AEP 2007 | Shapefile |
| GIS-381 | Vertederos de la Autoridad de Desperdicios Solidos | Shapefile |
| GIS-605 | NUMEROS SALIDAS AUTOPISTAS | Shapefile |
| GIS-610 | Puentes REVISION abril 2016 | Shapefile |
| GIS-618 | Rutas de transporte publico SIMETRO | Shapefile |
| GIS-621 | RUTAS PUBLICOS TERMINALES 2010 | Shapefile |
| GIS-664 | Zona de interes turistico SanJuan | Shapefile |

**How this was searched, and what that does not prove.** Each name was searched
across the whole Drive, not only the folders we were pointed at. A file stored
under a different name, or inside a geodatabase whose own name does not mention
it, would not be found this way. So the honest claim is: *not present under any
name we know to look for* — not *does not exist*.

---

# The metadata workbooks

Their team spent months reconstructing where each layer came from. Five workbooks,
**61 layer tabs**. Only 15 attach to a layer. The other 46 split in two:

## 4a. Describe a layer we have, under a different name (16 tabs)

Their GIS files call it `Hidrante`; our catalogue calls it `hidrantes`. These need
an alias, not a conversation. Each is a layer already on the system that is
carrying inferred metadata when their team had already established the real
source.

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

## 4b. Describe a layer we do not have (30 tabs)

`Línea_de_Gravedad`, `Tubería_Bombeo`, `Acometida_Sanitaria`, `Línea_Matriz`, `Línea_de_Servicio`, `Accesorio_de_Conexión`, `Estructura_Red`, `Estación_de_bombas`, `Estación_Bomba`, `Planta_Alcantarillado_Sani`, `Planta_de_filtracion`, `Punto_de_Muestreo`, `PuntoServicio`, `Metadata`, `invertebrados_poligonos_1`, `pajaros`, `esilr_1`, `esip_1`, `esile_1`, `CRIM`, `Empresas pecuarias`, `Flooding_Areas`, `Flood_1.00`, `Flood_0.2`, `Fincas_receptoras`, `geology_2018`, `Huellas_vertederos`, `Linea_vegetación`, `SistemaVial`, `RUTAS_AMA`

Thirteen of these are the AAA water and sewer network — gravity lines, pump
stations, filtration plants, sampling points. Their team documented that whole
network, and we hold none of it. That is worth asking about directly: it is the
single largest block of described-but-absent data, and it is infrastructure a
planning assistant would be asked about.

The tab called `Metadata` is the ACT highways workbook, which has one sheet rather
than one per layer — a format the importer does not read. That one is ours to fix.
