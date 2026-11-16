# Region boundaries

`regions.json` contains public geographical boundaries, not review observations.
It is derived from Natural Earth **5.1.2**, **1:50m admin-0 map units**:

- [Source GeoJSON](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_50m_admin_0_map_units.geojson)
- [Public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/)

The export keeps polygon rings rounded to four decimal places, bounding boxes,
and continent groups. African map units with `SUBREGION = Northern Africa` are
North Africa; the other African units are Sub-Saharan Africa. This includes Sudan
in North Africa and South Sudan in Sub-Saharan Africa, following the source's
[UN regional grouping](https://unstats.un.org/unsd/methodology/m49/).

Lookup uses the original observation coordinate on the server. If a coordinate
falls just outside the polygons, the nearest coast within approximately 200 km
supplies its region. More remote points are Other / offshore. Continent membership
follows Natural Earth's map-unit grouping, including its treatment of countries
that span continents. The boundary data is bundled so lookup needs no network
service and sends no observation coordinates to another service.

Rebuild with a downloaded copy of the linked GeoJSON:

```bash
python -m tools.prepare_map_regions SOURCE.geojson apps/review_map/geography/regions.json
```
